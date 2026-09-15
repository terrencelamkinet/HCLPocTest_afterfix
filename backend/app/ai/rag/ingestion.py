"""Vector ingestion pipeline for CRM record content.

Splits long-form CRM text into overlapping chunks, generates embeddings
via the configured provider, and persists them to ``vector_document_chunks``
with a parent ``vector_documents`` record for each source entity.

Usage::

    pipeline = IngestionPipeline()
    await pipeline.process_source(
        source_entity_type="deal_note",
        source_entity_id=some_uuid,
        title="Meeting notes",
        content="Very long text …",
        metadata={"author": "alice", "category": "follow-up"},
        tenant_id=tenant_uuid,
        workspace_id=workspace_uuid,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, cast
from uuid import UUID, uuid4

from sqlalchemy import select, delete, text
from sqlalchemy.exc import SQLAlchemyError

from app.ai.providers.base import get_provider
from app.db import async_session
from app.models.ai import VectorDocument, VectorDocumentChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ChunkConfig:
    """Configuration for the text-chunking strategy.

    Attributes
    ----------
    chunk_size:
        Target number of characters per chunk (soft boundary — a chunk may
        be slightly larger if it ends on a paragraph/sentence boundary).
    overlap:
        Number of characters of overlap between consecutive chunks.
    batch_size:
        Number of chunks to process in a single embedding + DB-write batch.
    embedding_model:
        The model name passed to ``ProviderAdapter.embed()``.
        Defaults to ``"text-embedding-3-small"``.
    min_content_length:
        Minimum character length for *content* to be processed at all.
        Texts shorter than this are silently skipped.
    """

    chunk_size: int = 500
    overlap: int = 50
    batch_size: int = 20
    embedding_model: str = "text-embedding-3-small"
    min_content_length: int = 20


DEFAULT_CHUNK_CONFIG = ChunkConfig()


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------


class IngestionPipeline:
    """Orchestrates end-to-end vector ingestion for a single source entity.

    Call ``process_source()`` with the raw CRM record content; the pipeline
    handles chunking, embedding generation (batched), and persistence.
    """

    def __init__(self, cfg: Optional[ChunkConfig] = None) -> None:
        self.cfg = cfg or DEFAULT_CHUNK_CONFIG

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_source(
        self,
        *,
        source_entity_type: str,
        source_entity_id: UUID,
        title: Optional[str] = None,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> Optional[UUID]:
        """Ingest a single CRM record as a vector document + chunks.

        Steps
        -----
        1. Skip records whose ``content`` is ``None`` or shorter than
           ``cfg.min_content_length``.
        2. Upsert (create-or-reuse) a parent ``VectorDocument``.
        3. Chunk the text.
        4. Generate embeddings in batches via ``asyncio.gather``.
        5. Delete stale chunks for the document.
        6. Bulk-insert fresh chunks with embeddings.

        Returns
        -------
        UUID or None
            The ``VectorDocument.id`` that was created/updated, or ``None``
            if the content was skipped.
        """
        # --- guard: short / empty content ---------------------------------
        if not content or len(content) < self.cfg.min_content_length:
            logger.debug(
                "Skipping ingestion for %s/%s: content too short (%d chars)",
                source_entity_type,
                source_entity_id,
                len(content) if content else 0,
            )
            return None

        logger.info(
            "Ingesting %s/%s (%s) — %d chars",
            source_entity_type,
            source_entity_id,
            title or "untitled",
            len(content),
        )

        async with async_session() as session:
            try:
                # RLS: vector_documents / vector_document_chunks have FORCE
                # RLS — set the tenant GUC so upserts/inserts pass WITH CHECK.
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
                # --- upsert parent document --------------------------------
                doc = await self._upsert_document(
                    session,
                    source_entity_type=source_entity_type,
                    source_entity_id=source_entity_id,
                    title=title,
                    metadata=metadata or {},
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )

                # --- chunk the text ----------------------------------------
                chunks_text = _chunk_text(content, self.cfg.chunk_size, self.cfg.overlap)
                logger.debug(
                    "Split into %d chunks (size=%d, overlap=%d)",
                    len(chunks_text),
                    self.cfg.chunk_size,
                    self.cfg.overlap,
                )

                # --- generate embeddings in batches -----------------------
                all_vectors: list[list[float] | None] = [None] * len(chunks_text)
                provider = get_provider("openai")
                usage_reports: list = []  # core rule G08: central token collection

                try:
                    for batch_start in range(0, len(chunks_text), self.cfg.batch_size):
                        batch_end = min(batch_start + self.cfg.batch_size, len(chunks_text))
                        batch_texts = chunks_text[batch_start:batch_end]

                        vectors = await self._embed_batch(provider, batch_texts, usage_reports)
                        all_vectors[batch_start:batch_end] = vectors
                finally:
                    await provider.close()

                # ── Record usage events (rag_ingestion module) ───────────
                for report in usage_reports:
                    try:
                        from app.models.ai.usage import UsageEvent
                        session.add(UsageEvent(
                            session_id=None,
                            user_id=uuid4(),  # system-level ingestion
                            tenant_id=tenant_id,
                            provider=report.provider or "openai",
                            model=report.model or self.cfg.embedding_model,
                            input_tokens=report.input_tokens,
                            output_tokens=report.output_tokens,
                            cost_estimate=float(report.cost_usd) if report.cost_usd else None,
                            result_status="success",
                            module="rag_ingestion",
                            currency="USD",
                        ))
                    except Exception:
                        pass  # usage recording is best-effort

                # --- delete stale chunks -----------------------------------
                await session.execute(
                    delete(VectorDocumentChunk).where(
                        VectorDocumentChunk.document_id == doc.id
                    )
                )

                # --- insert fresh chunks -----------------------------------
                chunk_rows = [
                    VectorDocumentChunk(
                        document_id=doc.id,
                        chunk_index=idx,
                        content=text,
                        embedding=all_vectors[idx],
                        metadata=metadata or {},
                    )
                    for idx, text in enumerate(chunks_text)
                ]
                session.add_all(chunk_rows)
                await session.commit()

                logger.info(
                    "Successfully ingested %s/%s: %d chunks, document=%s",
                    source_entity_type,
                    source_entity_id,
                    len(chunk_rows),
                    doc.id,
                )
                return cast(UUID, doc.id)

            except SQLAlchemyError:
                await session.rollback()
                logger.exception(
                    "DB error ingesting %s/%s",
                    source_entity_type,
                    source_entity_id,
                )
                return None
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected error ingesting %s/%s",
                    source_entity_type,
                    source_entity_id,
                )
                return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _upsert_document(
        self,
        session: Any,  # AsyncSession
        *,
        source_entity_type: str,
        source_entity_id: UUID,
        title: Optional[str],
        metadata: dict[str, Any],
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> VectorDocument:
        """Find an existing document for this entity or create a new one."""
        result = await session.execute(
            select(VectorDocument).where(
                VectorDocument.tenant_id == tenant_id,
                VectorDocument.workspace_id == workspace_id,
                VectorDocument.source_entity_type == source_entity_type,
                VectorDocument.source_entity_id == source_entity_id,
            )
        )
        doc = result.scalar_one_or_none()

        if doc is not None:
            # Update mutable fields
            doc.title = title
            doc.metadata = metadata
        else:
            doc = VectorDocument(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                source_entity_type=source_entity_type,
                source_entity_id=source_entity_id,
                title=title,
                metadata=metadata,
            )
            session.add(doc)

        # Flush so the document has an ID before chunk inserts
        await session.flush()
        return doc

    async def _embed_batch(
        self,
        provider: Any,  # ProviderAdapter
        texts: list[str],
        usage_out: list | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts via the provider.

        ``usage_out`` (optional list) collects the UsageReport of each LLM
        embed call — recorded centrally by the caller (core rule G08).
        """
        try:
            vectors, report = await provider.embed(
                texts,
                model=self.cfg.embedding_model,
            )
            if usage_out is not None:
                usage_out.append(report)
            return vectors
        except Exception:
            logger.exception(
                "Embedding batch of %d texts failed; returning zero vectors",
                len(texts),
            )
            # Fall back to zero vectors so the pipeline doesn't lose chunks
            dims = 1536
            return [[0.0] * dims] * len(texts)


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split *text* into overlapping character-length chunks.

    The algorithm respects natural boundaries in this priority order:

    1. Paragraph boundaries  (``\\n\\n``)
    2. Sentence boundaries   (``.``, ``!``, ``?`` + whitespace)
    3. Word boundaries       (space)
    4. Hard character split  (fallback)

    Each chunk is trimmed of leading/trailing whitespace.
    """
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text.strip()]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        # Determine the end of this chunk
        end = _find_split_point(text, start, chunk_size)

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Advance: move past the chunk, then back up by *overlap* characters
        # but always move forward by at least 1 to prevent infinite loops.
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


def _find_split_point(text: str, start: int, chunk_size: int) -> int:
    """Return the best index to split at, within ``[start + 1, start + chunk_size]``."""
    end = min(start + chunk_size, len(text))

    # If we're at the end, return the end
    if end == len(text):
        return end

    # 1. Try paragraph boundary (double newline) — search backwards from end
    paragraph = text.rfind("\n\n", start, end)
    if paragraph > start:
        return paragraph + 2  # include the newlines in the chunk

    # 2. Try sentence boundary (. ! ? followed by space or newline)
    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        pos = text.rfind(sep, start, end)
        if pos > start:
            return pos + len(sep)

    # 3. Try newline
    newline = text.rfind("\n", start, end)
    if newline > start:
        return newline + 1

    # 4. Try last space
    space = text.rfind(" ", start, end)
    if space > start:
        return space + 1

    # 5. Hard split at chunk_size
    return end


__all__ = [
    "ChunkConfig",
    "IngestionPipeline",
    "DEFAULT_CHUNK_CONFIG",
]

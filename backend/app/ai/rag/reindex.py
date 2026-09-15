"""Bulk text re-indexer for RAG vector store.

Reads all CRM entities (companies, contacts, deals, etc.) and creates
vector documents + chunks with embeddings.

Uses raw SQL to match the actual DB schema (nexus_ai.vector_documents
and nexus_ai.vector_document_chunks).
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.search import DEFAULT_EMBEDDING_DIMS, embed_query, embed_texts

logger = logging.getLogger(__name__)

# 2026-09-12（跨 document 批量）：一次 request 塞 64 段文字。
# 逐 doc 一次 request ≈1.4s／記錄（Kinetix 634 份 ≈15 分鐘）；跨 doc 批量之後
# call 數由 ~760 減到 ~12。
EMBED_BATCH = 64

# ---------------------------------------------------------------------------
# Entity queries — extract text to index from each CRM module
# ---------------------------------------------------------------------------

CRMDoc = dict[str, Any]

ENTITY_QUERIES: list[tuple[str, str, str]] = [
    (
        "company",
        "nexus_crm.companies",
        """
        SELECT id, name, industry, notes, status
        FROM nexus_crm.companies
        WHERE tenant_id = :tenant_id
        """,
    ),
    (
        "contact",
        "nexus_crm.contacts",
        """
        SELECT id, name, email, phone, job_title, notes, status
        FROM nexus_crm.contacts
        WHERE tenant_id = :tenant_id
        """,
    ),
    (
        "deal",
        "nexus_crm.deals",
        """
        SELECT id, name, amount, notes, status
        FROM nexus_crm.deals
        WHERE tenant_id = :tenant_id
        """,
    ),
    (
        "task",
        "nexus_crm.tasks",
        """
        SELECT id, title, description, status
        FROM nexus_crm.tasks
        WHERE tenant_id = :tenant_id
        """,
    ),
    (
        "touchpoint",
        "nexus_crm.touchpoints",
        """
        SELECT id, title, description
        FROM nexus_crm.touchpoints
        WHERE tenant_id = :tenant_id
        """,
    ),
    (
        "project",
        "nexus_crm.projects",
        """
        SELECT id, name, description, status
        FROM nexus_crm.projects
        WHERE tenant_id = :tenant_id
        """,
    ),
]

NOTES_QUERY = """
    SELECT n.id AS note_id, n.content, n.company_id, n.contact_id, n.title
    FROM nexus_crm.notes n
    WHERE n.tenant_id = :tenant_id
"""

# Notes V2 (T1.5) — 私人筆記「暫時唔可以入 RAG 索引」。
# 原因：nexus_ai.vector_documents 係 **tenant 級共享**索引，而 app/ai/rag/search.py 嘅
# vector_search() 完全冇 owner_user_id / visibility_scope filter。原本嘅 INSERT 仲要
# 硬編 visibility_scope='workspace' + owner_user_id=NULL，即係索引咗就等於：
# tenant 內任何一個同事（或任何 AI 檢索）都撈得返你私人筆記嘅內容。
# 要開返嘅前置條件：vector_search() 加 owner/visibility filter + 所有 caller 傳 user_id
# + 呢度改成寫入 owner_user_id = n.created_by 同 visibility_scope='private'。
NOTE_INDEXING_ENABLED = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_row(module: str, row: dict[str, Any]) -> str:
    """Format a CRM record row into indexable text."""
    parts: list[str] = []

    if module == "company":
        parts.append(f"Company: {row.get('name', '')}")
        if row.get("industry"):
            parts.append(f"Industry: {row['industry']}")
        if row.get("notes"):
            parts.append(f"Notes: {row['notes']}")

    elif module == "contact":
        parts.append(f"Contact: {row.get('name', '')}")
        if row.get("email"):
            parts.append(f"Email: {row['email']}")
        if row.get("phone"):
            parts.append(f"Phone: {row['phone']}")
        if row.get("job_title"):
            parts.append(f"Position: {row['job_title']}")
        if row.get("notes"):
            parts.append(f"Notes: {row['notes']}")

    elif module == "deal":
        parts.append(f"Deal: {row.get('name', '')}")
        if row.get("amount"):
            parts.append(f"Value: {row['amount']}")
        if row.get("notes"):
            parts.append(f"Notes: {row['notes']}")

    elif module == "task":
        parts.append(f"Task: {row.get('title', '')}")
        if row.get("description"):
            parts.append(f"Description: {row['description']}")

    elif module == "touchpoint":
        parts.append(f"Touchpoint: {row.get('title', '')}")
        if row.get("description"):
            parts.append(f"Description: {row['description']}")

    elif module == "project":
        parts.append(f"Project: {row.get('name', '')}")
        if row.get("description"):
            parts.append(f"Description: {row['description']}")

    elif module == "note":
        parts.append(f"Note: {row.get('content', '')}")
        parts.append(f"On: {row.get('company_id', '')} / {row.get('contact_id', '')}")

    return "\n".join(parts)


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Simple text chunking by character count with overlap."""
    if not text or len(text) <= chunk_size:
        return [text.strip()] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            for sep in (". ", "! ", "? ", "\n\n", "\n", " "):
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end].strip())
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return chunks


# ---------------------------------------------------------------------------
# Re-indexer
# ---------------------------------------------------------------------------


async def purge_record_vectors(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_module: str,
    source_record_id: UUID,
) -> int:
    """清走某條來源記錄現有嘅 vector document（chunks 靠 FK ON DELETE CASCADE 跟走）。

    T2：令重建 idempotent。原本每次重建都用新 uuid 插入、`ON CONFLICT (id)` 永遠唔會
    fire → 每跑一次就多一份，索引重複膨脹。
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    result = await db.execute(
        text(
            """
            DELETE FROM nexus_ai.vector_documents
            WHERE tenant_id = :t AND source_module = :m AND source_record_id = :r
            """
        ),
        {"t": tenant_id, "m": source_module, "r": source_record_id},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def reindex_tenant(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID | None = None,
    source_modules: list[str] | None = None,
) -> dict[str, Any]:
    """Bulk re-index all CRM entities for a tenant into the vector store.

    Returns a summary dict with counts per module.
    """
    now = datetime.now(timezone.utc)
    stats: dict[str, Any] = {"total_docs": 0, "total_chunks": 0}
    module_summary: dict[str, int] = {}
    # (doc_id, chunk_text) 緩衝 —— 跨 document 批量 embed（兩個迴圈共用）
    pending: list[tuple[UUID, str]] = []

    # Set RLS context for the connection (needed after any commit)
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})

    # ── Process each entity type ───────────────────────────────────
    for module_name, source_table, query_sql in ENTITY_QUERIES:
        if source_modules and module_name not in source_modules:
            continue

        result = await db.execute(text(query_sql), {"tenant_id": tenant_id})
        rows = result.mappings().fetchall()
        if not rows:
            continue

        module_count = 0
        for row in rows:
            row_dict = dict(row)
            source_record_id = row_dict["id"]
            text_content = _format_row(module_name, row_dict)
            if not text_content or len(text_content) < 20:
                continue

            chunks_text = _chunk_text(text_content)
            if not chunks_text:
                continue

            # T2：重建要 idempotent — 同一記錄舊 doc 先清走（chunks 靠 FK CASCADE），
            # 否則每跑一次就多一份，索引會重複膨脹。
            await purge_record_vectors(
                db,
                tenant_id=tenant_id,
                source_module=module_name,
                source_record_id=source_record_id,
            )

            doc_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO nexus_ai.vector_documents
                        (id, tenant_id, workspace_id, team_id, owner_user_id,
                         visibility_scope, source_module, source_record_id, created_at)
                    VALUES
                        (:id, :tenant_id, :workspace_id, NULL, NULL,
                         'workspace', :source_module, :source_record_id, :created_at)
                    ON CONFLICT (id) DO UPDATE SET
                        source_module = EXCLUDED.source_module
                """),
                {
                    "id": doc_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id or tenant_id,
                    "source_module": module_name,
                    "source_record_id": source_record_id,
                    "created_at": now,
                },
            )

            # 2026-09-12（跨 doc 批量）：唔喺呢度 embed —— 收集埋一次過做，減少 API call
            pending.extend((doc_id, ct) for ct in chunks_text)

            module_count += len(chunks_text)
            stats["total_docs"] += 1
            stats["total_chunks"] += len(chunks_text)

        # ── 跨 document 批量 embed，再一次過插入 chunks ──
        if pending:
            texts = [ct for _doc, ct in pending]
            vecs: list[list[float]] = []
            for i in range(0, len(texts), EMBED_BATCH):
                vecs.extend(await embed_texts(texts[i : i + EMBED_BATCH]))
            for (pending_doc_id, ctext), vec in zip(pending, vecs):
                await db.execute(
                    text("""
                        INSERT INTO nexus_ai.vector_document_chunks
                            (id, document_id, chunk_text, embedding,
                             tenant_id, workspace_id, visibility_scope)
                        VALUES
                            (:id, :document_id, :chunk_text, CAST(:embedding AS vector),
                             :tenant_id, :workspace_id, 'workspace')
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": uuid4(),
                        "document_id": pending_doc_id,
                        "chunk_text": ctext,
                        "embedding": str(vec),
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id or tenant_id,
                    },
                )
            pending = []

        module_summary[module_name] = module_count
        await db.commit()
        # Re-set RLS context after commit (transaction ended)
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})

    # ── Process notes separately（T1.5：預設關閉，見 NOTE_INDEXING_ENABLED 註解）──
    if NOTE_INDEXING_ENABLED and (not source_modules or "note" in source_modules):
        notes_result = await db.execute(text(NOTES_QUERY), {"tenant_id": tenant_id})
        notes_rows = notes_result.mappings().fetchall()
        note_count = 0
        for row in notes_rows:
            row_dict = dict(row)
            text_content = _format_row("note", row_dict)
            if not text_content or len(text_content) < 20:
                continue

            chunks_text = _chunk_text(text_content)
            if not chunks_text:
                continue

            # 🔴 2026-09-12 double check：呢度原本冇 purge → 每次重建都 append 多一份
            # （同主迴圈一樣嘅 bug，之前只修咗主迴圈）。而家一齊修。
            await purge_record_vectors(
                db,
                tenant_id=tenant_id,
                source_module="note",
                source_record_id=row_dict["note_id"],
            )

            doc_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO nexus_ai.vector_documents
                        (id, tenant_id, workspace_id, team_id, owner_user_id,
                         visibility_scope, source_module, source_record_id, created_at)
                    VALUES
                        (:id, :tenant_id, :workspace_id, NULL, NULL,
                         'workspace', 'note', :source_record_id, :created_at)
                    ON CONFLICT (id) DO UPDATE SET
                        source_module = EXCLUDED.source_module
                """),
                {
                    "id": doc_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id or tenant_id,
                    "source_record_id": row_dict["note_id"],
                    "created_at": now,
                },
            )

            # 同主迴圈一致：收集埋一次過批量 embed
            pending.extend((doc_id, ct) for ct in chunks_text)

            note_count += len(chunks_text)
            stats["total_chunks"] += len(chunks_text)
            stats["total_docs"] += 1

        if pending:
            texts = [ct for _doc, ct in pending]
            vecs: list[list[float]] = []
            for i in range(0, len(texts), EMBED_BATCH):
                vecs.extend(await embed_texts(texts[i : i + EMBED_BATCH]))
            for (pending_doc_id, ctext), vec in zip(pending, vecs):
                await db.execute(
                    text("""
                        INSERT INTO nexus_ai.vector_document_chunks
                            (id, document_id, chunk_text, embedding,
                             tenant_id, workspace_id, visibility_scope)
                        VALUES
                            (:id, :document_id, :chunk_text, CAST(:embedding AS vector),
                             :tenant_id, :workspace_id, 'workspace')
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": uuid4(),
                        "document_id": pending_doc_id,
                        "chunk_text": ctext,
                        "embedding": str(vec),
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id or tenant_id,
                    },
                )
            pending = []

        if note_count > 0:
            module_summary["note"] = note_count
            await db.commit()
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})

    stats["modules"] = module_summary
    return stats


async def delete_tenant_vectors(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_modules: list[str] | None = None,
) -> int:
    """Delete all vector data for a tenant (or specific modules)."""
    if source_modules:
        result = await db.execute(
            text("""
                DELETE FROM nexus_ai.vector_document_chunks
                WHERE tenant_id = :tenant_id
                  AND document_id IN (
                      SELECT id FROM nexus_ai.vector_documents
                      WHERE tenant_id = :tenant_id
                        AND source_module = ANY(:modules)
                  )
            """),
            {"tenant_id": tenant_id, "modules": source_modules},
        )
        chunk_count = result.rowcount
        result = await db.execute(
            text("""
                DELETE FROM nexus_ai.vector_documents
                WHERE tenant_id = :tenant_id
                  AND source_module = ANY(:modules)
            """),
            {"tenant_id": tenant_id, "modules": source_modules},
        )
        doc_count = result.rowcount
    else:
        result = await db.execute(
            text("DELETE FROM nexus_ai.vector_document_chunks WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        chunk_count = result.rowcount
        result = await db.execute(
            text("DELETE FROM nexus_ai.vector_documents WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        doc_count = result.rowcount

    await db.commit()

    # Re-set RLS context after commit (transaction ended)
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})
    return chunk_count + doc_count

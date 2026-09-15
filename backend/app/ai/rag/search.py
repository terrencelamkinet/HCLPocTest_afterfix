"""RAG vector search — embed query → pgvector cosine similarity → ranked results.

Uses raw SQL for pgvector's ``<=>`` (cosine distance) operator since the
SQLAlchemy model doesn't match the actual DB schema. All queries are
tenant-scoped via explicit ``tenant_id`` filter.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import get_provider
from app.ai.rag.audit import record_retrieval as _audit_retrieval

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMS = 1536
DEFAULT_TOP_K = 10

# 2026-09-12 T1（語意檢索）：實證 Vertex gemini-embedding-001 @1536 可用
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
# 語意 provider 嘗試次序（local tf-idf 只做最後 fallback，見 embed_query）
SEMANTIC_PROVIDERS = (("gemini", GEMINI_EMBEDDING_MODEL), ("openai", DEFAULT_EMBEDDING_MODEL))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RAGResult:
    """A single vector search hit."""

    chunk_id: UUID
    document_id: UUID
    chunk_text: str
    score: float              # cosine similarity (higher = more similar)
    source_module: str
    source_record_id: UUID
    visibility_scope: str
    source_title: str | None = None   # T4：引用用（file → 檔名；其他 → module 名）

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "chunk_text": self.chunk_text,
            "score": round(self.score, 4),
            "source_module": self.source_module,
            "source_record_id": str(self.source_record_id),
            "visibility_scope": self.visibility_scope,
            "source_title": self.source_title,
        }


@dataclass
class SearchConfig:
    """Search configuration."""

    top_k: int = DEFAULT_TOP_K
    min_score: float = 0.35       # below this, results are discarded
    embedding_model: str = DEFAULT_EMBEDDING_MODEL


DEFAULT_SEARCH_CONFIG = SearchConfig()


# ---------------------------------------------------------------------------
# Core search
# ---------------------------------------------------------------------------


async def embed_query(
    query: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
    usage_out: list | None = None,
) -> list[float]:
    """Generate embedding vector for a text query.

    Priority（2026-09-12 T1 改 — 語意優先）:
    1. Gemini / Vertex（gemini-embedding-001 @1536 — 實證可用）
    2. OpenAI（text-embedding-3-small, 1536）
    3. Local tf-idf（HashingVectorizer + SVD — 零依賴，但**冇語意理解**，只做最後 fallback）
    4. Deterministic zero vector（全部 provider 都唔得）

    改動原因：原本 local tf-idf 排第一而且「行得通就用」，令索引同查詢實際全部係
    字面 n-gram 向量 —— 用同義詞問問題會檢索唔到本應搵到嘅內容。

    ``usage_out`` (optional list) receives the UsageReport of the LLM call
    that succeeded — the caller records it centrally (core rule G08).

    ``model`` 保留只為向後兼容（舊 caller 會傳）；實際用邊個 model 由
    ``SEMANTIC_PROVIDERS`` 決定。
    """
    # 1-2. Semantic providers（順序：gemini → openai）
    for provider_name, provider_model in SEMANTIC_PROVIDERS:
        try:
            adapter = get_provider(provider_name)
        except Exception:
            continue
        try:
            vectors, report = await adapter.embed([query], model=provider_model)
            if vectors and vectors[0] and any(v != 0.0 for v in vectors[0]):
                if usage_out is not None:
                    usage_out.append(report)
                return vectors[0]
        except Exception:
            pass
        finally:
            try:
                await adapter.close()
            except Exception:
                pass

    # 3. Local tf-idf — 最後 fallback（質素明顯較低，log 出嚟免得靜默降級）
    try:
        from app.ai.rag.local_embed import local_embed
        vectors = local_embed([query])
        if vectors and vectors[0] and any(v != 0.0 for v in vectors[0]):
            logger.warning(
                "Semantic embedding providers unavailable — falling back to local tf-idf "
                "(retrieval quality degraded)"
            )
            return vectors[0]
    except Exception:
        pass

    logger.warning("All embedding providers unavailable; returning zero vector")
    return [0.0] * DEFAULT_EMBEDDING_DIMS


async def vector_search(
    db: AsyncSession,
    *,
    query_vector: list[float],
    tenant_id: UUID,
    workspace_id: UUID | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = 0.35,
    source_module: str | None = None,
) -> list[RAGResult]:
    """Search vector chunks by cosine similarity, tenant-scoped.

    Uses pgvector's ``<=>`` operator (cosine distance).
    Only returns chunks with score >= *min_score*.
    """
    # Build the WHERE clause dynamically
    # RLS: vector_document_chunks / vector_documents now have FORCE RLS —
    # set the tenant GUC so the row-level policy matches (the explicit
    # tenant_id filter below is belt-and-braces app-layer isolation).
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    filters = [
        "c.tenant_id = :tenant_id",
        # T5（spec §7.1 pre-filter）：停用／未批准／受限嘅內容唔准入 retrieval，
        # 亦唔會去到 rerank 或 LLM context。狀態由 documents 取（chunks 唔複製，避免漂移）。
        "d.ai_enabled = true",
        "d.document_status = 'approved'",
        "(d.classification IS NULL OR d.classification NOT IN ('restricted', 'archived', 'deleted'))",
    ]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "query_vector": str(query_vector),
        "top_k": top_k,
    }

    if workspace_id:
        filters.append("c.workspace_id = :workspace_id")
        params["workspace_id"] = workspace_id

    if source_module:
        filters.append("d.source_module = :source_module")
        params["source_module"] = source_module

    where_clause = " AND ".join(filters)

    sql = text(f"""
        SELECT
            c.id              AS chunk_id,
            c.document_id     AS document_id,
            c.chunk_text      AS chunk_text,
            1 - (c.embedding <=> (:query_vector)::vector) AS score,
            d.source_module   AS source_module,
            d.source_record_id AS source_record_id,
            c.visibility_scope AS visibility_scope,
            -- T4：引用標題 —— file 類型用原始檔名，其他用 module 名
            CASE WHEN d.source_module = 'file' THEN f.original_filename END AS source_title
        FROM nexus_ai.vector_document_chunks c
        JOIN nexus_ai.vector_documents d ON d.id = c.document_id
        LEFT JOIN nexus_crm.files f
               ON d.source_module = 'file' AND f.id = d.source_record_id
        WHERE {where_clause}
          AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> (:query_vector)::vector
        LIMIT :top_k
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
    except Exception:
        logger.exception("Vector search SQL failed")
        return []

    hits: list[RAGResult] = []
    for row in rows:
        score = float(row.score) if row.score is not None else 0.0
        if score < min_score:
            continue
        hits.append(RAGResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            chunk_text=row.chunk_text,
            score=score,
            source_module=row.source_module,
            source_record_id=row.source_record_id,
            visibility_scope=row.visibility_scope,
            source_title=getattr(row, "source_title", None),
        ))

    return hits


async def retrieve_context(
    db: AsyncSession,
    *,
    query: str,
    tenant_id: UUID,
    workspace_id: UUID | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = 0.35,
    source_module: str | None = None,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
) -> str:
    """High-level: embed query → search → return formatted text for LLM context.

    Returns a markdown-formatted string of top chunks, or an empty string
    if nothing relevant was found.
    """
    usage_out: list = []
    _t0 = time.perf_counter()
    query_vector = await embed_query(query, usage_out=usage_out)
    hits = await vector_search(
        db,
        query_vector=query_vector,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        top_k=top_k,
        min_score=min_score,
        source_module=source_module,
    )

    # ── Record usage event (rag_search module) — central token collection ──
    if usage_out and user_id is not None:
        try:
            from app.models.ai.usage import UsageEvent
            report = usage_out[0]
            # 🔴 2026-09-12 double check：原本只 db.add()（排隊），INSERT 會延到之後
            # 嘅 flush/commit —— 但 transaction-scoped GUC 到時可能已經 reset
            # → usage_events RLS violation → 成個 caller transaction 變 aborted。
            # （舊 audit 喺 caller session commit 啱啱好沖咗呢個 INSERT，所以一直冇爆；
            #   改 audit 用自己 session 之後即刻現形。）修：明確 set GUC + 即刻 flush。
            await db.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            db.add(UsageEvent(
                session_id=None,
                user_id=user_id,
                tenant_id=tenant_id,
                provider=report.provider or "openai",
                model=report.model or DEFAULT_EMBEDDING_MODEL,
                input_tokens=report.input_tokens,
                output_tokens=report.output_tokens,
                cost_estimate=float(report.cost_usd) if report.cost_usd else None,
                result_status="success",
                module="rag_search",
                currency="USD",
            ))
            await db.flush()
        except Exception:
            # best-effort：唔可以留低 aborted transaction 毒害之後嘅語句
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning("rag_search usage event not recorded (best-effort)", exc_info=True)

    if not hits:
        # spec §11：冇命中都要審計（denied）—— 否則「AI 答唔到」查唔到原因
        await _audit_retrieval(
            tenant_id=tenant_id, user_id=user_id, query=query, hits=[],
            latency_ms=int((time.perf_counter() - _t0) * 1000), session_id=session_id,
        )
        return ""

    # spec §11：檢索審計（best-effort，唔會影響回答）
    await _audit_retrieval(
        tenant_id=tenant_id, user_id=user_id, query=query, hits=hits,
        latency_ms=int((time.perf_counter() - _t0) * 1000), session_id=session_id,
    )

    lines: list[str] = []
    for i, hit in enumerate(hits, 1):
        # T4：引用標題（file → 檔名）+ doc id，令答案可以標明出處
        title = hit.source_title or hit.source_module
        lines.append(f"{i}. **[{hit.source_module}] {title}** (score: {hit.score:.3f}) [doc:{hit.document_id}]")
        lines.append(f"   > {hit.chunk_text[:400]}")
        lines.append("")

    context_str = "\n".join(lines)

    # ── DLP（出站邊界）：餵去 LLM 之前掃敏感資料，命中就遮蔽 + 寫審計 ──
    # （BYOK + DLP + 審計報告 之三；刻意保守：只捉 secrets / HKID / 信用卡（過 Luhn））
    from app.services.dlp import audit_dlp, redact_text, scan_text

    verdict = scan_text(context_str)
    if verdict.hit:
        await audit_dlp(
            None, tenant_id=tenant_id, user_id=user_id, verdict=verdict, source="rag_context"
        )
        context_str = redact_text(context_str)

    return (
        "**📋 RELEVANT CRM RECORDS (semantic search):**\n"
        f"{context_str}"
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量 embed（一個 API call 處理多段）—— reindex 用。

    逐段 call embed_query 會令全量重建慢到 timeout（實測：302 docs 用 > 560s 未完成）。
    Provider 本身支援一次過 embed 多段文字，所以直接批量。
    """
    if not texts:
        return []

    for provider_name, provider_model in SEMANTIC_PROVIDERS:
        try:
            adapter = get_provider(provider_name)
        except Exception:
            continue
        try:
            vectors, _report = await adapter.embed(texts, model=provider_model)
            if vectors and len(vectors) == len(texts):
                return [
                    v if (v and any(x != 0.0 for x in v)) else [0.0] * DEFAULT_EMBEDDING_DIMS
                    for v in vectors
                ]
        except Exception:
            logger.warning("Batch embed via %s failed; trying next provider", provider_name)
        finally:
            try:
                await adapter.close()
            except Exception:
                pass

    logger.warning(
        "Batch semantic embed unavailable — falling back to local tf-idf (quality degraded)"
    )
    try:
        from app.ai.rag.local_embed import local_embed
        return local_embed(texts)
    except Exception:
        return [[0.0] * DEFAULT_EMBEDDING_DIMS for _ in texts]


__all__ = [
    "embed_query",
    "embed_texts",
    "vector_search",
    "retrieve_context",
    "RAGResult",
    "SearchConfig",
    "DEFAULT_SEARCH_CONFIG",
]

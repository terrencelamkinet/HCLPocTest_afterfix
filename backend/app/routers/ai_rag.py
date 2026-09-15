"""RAG (Retrieval-Augmented Generation) router — /api/v1/ai/rag/* endpoints.

Provides semantic search across vector-embedded CRM records.
Tenant-scoped via JWT auth middleware.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.ai.rag.search import (
    embed_query,
    vector_search,
    retrieve_context,
)
from app.ai.rag.ingest import (
    IngestError,
    delete_file,
    get_citation,
    ingest_file,
    list_files,
    set_file_controls,
)
from app.ai.rag.reindex import reindex_tenant, delete_tenant_vectors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/rag", tags=["AI RAG"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    min_score: float = 0.35
    source_module: str | None = None


class ReindexRequest(BaseModel):
    """Trigger re-indexing for specific modules or all CRM entities."""
    source_modules: list[str] | None = None  # None = all


# ---------------------------------------------------------------------------
# Knowledge-base files (T3) — upload / list / delete
# ---------------------------------------------------------------------------


@router.post("/files")
async def rag_upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_session),
):
    """上載一份文件入知識庫（PDF / txt / md / docx / xlsx）。

    All-or-nothing：抽取或 embed 失敗唔會留低半生半死嘅文件。
    同一內容重複上載 → status="duplicate"（唔會靜默重複入庫）。
    """
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")

    data = await file.read()
    try:
        return await ingest_file(
            db,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            user_id=getattr(ctx, "user_id", None),
            filename=file.filename or "",
            mime=file.content_type,
            data=data,
        )
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/files")
async def rag_list_files(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """知識庫文件一覽（含每份文件嘅索引段落數）。"""
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")
    files = await list_files(db, tenant_id=ctx.tenant_id)
    return {"files": files, "total": len(files)}


@router.delete("/files/{file_id}")
async def rag_delete_file(
    file_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """刪文件 → 即刻停止檢索（同一問題唔會再引用佢）。"""
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")
    removed = await delete_file(db, tenant_id=ctx.tenant_id, file_id=file_id)
    return {"deleted_documents": removed, "file_id": str(file_id)}


class FileControlsRequest(BaseModel):
    """T5：文件層 AI 控制。"""
    ai_enabled: bool | None = None
    classification: str | None = None


@router.patch("/files/{file_id}")
async def rag_set_file_controls(
    file_id: UUID,
    body: FileControlsRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """切換某份文件准唔准 AI 用／機密級別 —— **即時生效**（下一次檢索就唔會出現）。"""
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")
    try:
        updated = await set_file_controls(
            db,
            tenant_id=ctx.tenant_id,
            file_id=file_id,
            ai_enabled=body.ai_enabled,
            classification=body.classification,
        )
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"updated": updated, "file_id": str(file_id),
            "ai_enabled": body.ai_enabled, "classification": body.classification}


@router.get("/citations/{document_id}")
async def rag_get_citation(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """T4：引用再驗證 —— 文件仍然存在、未刪除、可檢索（spec §7.2）。

    唔存在／唔屬當前 tenant → 404（唔會透露其他 tenant 嘅文件存在與否）。
    """
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")
    citation = await get_citation(db, tenant_id=ctx.tenant_id, document_id=document_id)
    if citation is None:
        raise HTTPException(404, "找不到此來源（可能已刪除或不屬於你）")
    return citation


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


@router.post("/search")
async def rag_search(
    body: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Semantic search across vector-embedded CRM records.

    Returns ranked chunks with cosine similarity scores.
    All results are tenant-scoped.
    """
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")

    if not body.query.strip():
        return {"results": [], "query": body.query}

    # Embed the query
    query_vector = await embed_query(body.query)

    # Search
    hits = await vector_search(
        db,
        query_vector=query_vector,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        top_k=body.top_k,
        min_score=body.min_score,
        source_module=body.source_module,
    )

    return {
        "query": body.query,
        "results": [h.to_dict() for h in hits],
        "total": len(hits),
    }


# ---------------------------------------------------------------------------
# Context retrieval endpoint (for frontend / LLM pre-fetch)
# ---------------------------------------------------------------------------


@router.post("/context")
async def rag_context(
    body: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get RAG context as formatted text for LLM injection.

    Returns a markdown-formatted string ready to insert into a system prompt.
    """
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")

    if not body.query.strip():
        return {"context": ""}

    context_str = await retrieve_context(
        db,
        query=body.query,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        top_k=body.top_k,
        min_score=body.min_score,
        source_module=body.source_module,
        user_id=ctx.user_id,
    )

    return {"context": context_str}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
async def rag_health():
    """Check RAG module readiness."""
    # Quick test: can we import and call embed?
    try:
        vec = await embed_query("test", model="text-embedding-3-small")
        vec_ok = len(vec) == 1536 and any(v != 0.0 for v in vec)
    except Exception:
        vec_ok = False

    return {
        "status": "ok" if vec_ok else "degraded",
        "embedding_ready": vec_ok,
        "embedding_dims": 1536,
        # 2026-09-12 T1：同 search.py 嘅 SEMANTIC_PROVIDERS 保持一致（唔好報假狀態）
        "default_embedding_model": "gemini-embedding-001",
        "vector_index": "pgvector HNSW (cosine distance)",
    }


# ---------------------------------------------------------------------------
# Re-index all CRM entities for the current tenant
# ---------------------------------------------------------------------------


@router.post("/reindex")
async def rag_reindex(
    body: ReindexRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Bulk re-index all CRM entities into the vector store.

    Deletes existing vectors for the tenant first, then re-creates them.
    May take 30-120s depending on data volume.
    """
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")

    # Delete existing vectors
    deleted = await delete_tenant_vectors(
        db,
        tenant_id=ctx.tenant_id,
        source_modules=body.source_modules,
    )

    # Re-index
    stats = await reindex_tenant(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        source_modules=body.source_modules,
    )

    return {
        "status": "ok",
        "deleted": deleted,
        "documents_created": stats["total_docs"],
        "chunks_created": stats["total_chunks"],
        "modules": stats["modules"],
    }


@router.delete("/vectors")
async def rag_delete_vectors(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
    source_modules: str | None = Query(None, description="Comma-separated module names"),
):
    """Delete all vector data for the current tenant (or specific modules)."""
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")

    modules = source_modules.split(",") if source_modules else None
    deleted = await delete_tenant_vectors(
        db,
        tenant_id=ctx.tenant_id,
        source_modules=modules,
    )

    return {"status": "ok", "deleted": deleted}

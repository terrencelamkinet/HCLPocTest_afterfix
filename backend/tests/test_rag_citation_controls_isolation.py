"""T4 / T5 / T6 — 引用再驗證、文件控制、隔離矩陣（紅燈先行）。

覆蓋 one-user-one-tenant spec §12.1 隔離矩陣可測項目：
  #1 User A 搜 B 獨有 phrase → 0 結果
  #2 用 B 嘅 document id 直接取 → 拒絕（唔透露存在與否）
  #3 刪除後唔再檢索到
  #4 ai_enabled=false → 唔入 retrieval
  #5 connection 重用唔會帶舊 tenant 身份
"""

import uuid

import pytest
from sqlalchemy import text

from app.ai.rag.ingest import (
    delete_file,
    get_citation,
    ingest_file,
    set_file_controls,
)
from app.ai.rag.search import embed_query, vector_search
from app.db import async_session

A = uuid.UUID("00000000-0000-0000-0000-0000000aaaaa")  # tenant A
B = uuid.UUID("00000000-0000-0000-0000-0000000bbbbb")  # tenant B
PHRASE_B = "zzB專屬片段：量子糾纏物流保險條款 nine-vector-free"
PHRASE_A = "zzA專屬片段：客戶退款流程與十四日退貨安排"


@pytest.fixture(autouse=True)
async def _dispose_db_engine():
    """避免 pytest-asyncio 換 loop 之後用返舊 pooled connection。"""
    yield
    from app.db import engine
    await engine.dispose()


async def _cleanup(db):
    for t in (A, B):
        await db.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)}
        )
        await db.execute(
            text("DELETE FROM nexus_ai.vector_documents WHERE tenant_id = :t"), {"t": t}
        )
        await db.execute(text("DELETE FROM nexus_crm.files WHERE tenant_id = :t"), {"t": t})
    await db.commit()


async def _upload(db, tenant, phrase, name="doc.txt"):
    return await ingest_file(
        db,
        tenant_id=tenant,
        workspace_id=tenant,
        user_id=None,
        filename=name,
        mime="text/plain",
        data=phrase.encode(),
    )


@pytest.mark.asyncio
async def test_citation_revalidation_and_controls():
    """T4 + T5：引用再驗證；停用／刪除之後唔再可檢索。"""
    async with async_session() as db:
        try:
            up = await _upload(db, A, PHRASE_A, "a-policy.txt")
            vec = await embed_query("客戶退款流程")

            hits = await vector_search(db, query_vector=vec, tenant_id=A, top_k=5)
            assert hits, "上載之後應該檢索到"
            assert hits[0].source_title == "a-policy.txt", hits[0]

            # T4：引用再驗證
            cit = await get_citation(db, tenant_id=A, document_id=hits[0].document_id)
            assert cit and cit["retrievable"] is True

            # T5：停用 → 即時唔再檢索到（spec §12.1 #4）
            n = await set_file_controls(
                db, tenant_id=A, file_id=uuid.UUID(up["file_id"]), ai_enabled=False
            )
            assert n == 1
            assert await vector_search(db, query_vector=vec, tenant_id=A, top_k=5) == []

            # 重新啟用 → 返返嚟
            await set_file_controls(
                db, tenant_id=A, file_id=uuid.UUID(up["file_id"]), ai_enabled=True
            )
            assert await vector_search(db, query_vector=vec, tenant_id=A, top_k=5)

            # classification=restricted 同樣唔准入 retrieval
            await set_file_controls(
                db, tenant_id=A, file_id=uuid.UUID(up["file_id"]), classification="restricted"
            )
            assert await vector_search(db, query_vector=vec, tenant_id=A, top_k=5) == []

            # T6 #3：刪除之後引用驗證失敗
            await delete_file(db, tenant_id=A, file_id=uuid.UUID(up["file_id"]))
            assert await get_citation(db, tenant_id=A, document_id=hits[0].document_id) is None
        finally:
            await _cleanup(db)


@pytest.mark.asyncio
async def test_cross_tenant_isolation():
    """T6 #1 + #2：A 搜唔到 B 嘅獨有內容；用 B 嘅 doc id 取唔到。"""
    async with async_session() as db:
        try:
            await _upload(db, B, PHRASE_B, "b-secret.txt")
            vec = await embed_query("量子糾纏物流保險條款")

            # B 自己搵得到（證明資料真係入咗）
            own = await vector_search(db, query_vector=vec, tenant_id=B, top_k=5)
            assert own, "B 應該檢索到自己嘅文件"

            # A 搵唔到 B 嘅嘢（#1）
            other = await vector_search(db, query_vector=vec, tenant_id=A, top_k=5)
            assert other == [], f"A 唔應該見到 B 嘅內容，實際 {len(other)} 個 hit"

            # A 用 B 嘅 document id 直接取 → 拒絕（#2）
            assert await get_citation(db, tenant_id=A, document_id=own[0].document_id) is None
        finally:
            await _cleanup(db)


@pytest.mark.asyncio
async def test_rls_context_does_not_leak_between_sessions():
    """T6 #5：一個 session 設過 tenant GUC，唔會令另一個 session 見到其他 tenant。"""
    async with async_session() as db:
        try:
            await _upload(db, B, PHRASE_B, "b-leak-check.txt")
        finally:
            pass

    # 新 session，冇設過 GUC → RLS 應該全部擋（見唔到任何 doc）
    async with async_session() as db2:
        try:
            visible = (
                await db2.execute(text("SELECT count(*) FROM nexus_ai.vector_documents"))
            ).scalar()
            assert visible == 0, f"冇 tenant context 嘅 session 唔應該見到任何 doc，實際 {visible}"
        finally:
            await _cleanup(db2)

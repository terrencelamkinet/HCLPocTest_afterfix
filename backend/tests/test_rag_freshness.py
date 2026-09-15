"""T2 — 索引新鮮度：紅燈先行（未實作之前應該 fail）。

契約：
 1. 重建索引要 idempotent：同一記錄重建兩次，索引唔可以有重複（現行 append → RED）
 2. 要有「邊個 tenant 有嘢改過未入索引」嘅偵測，而且係 tenant-scoped
 3. 索引落後超閾值要判斷得出（唔准靜默落後）
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ai.rag.freshness import (
    detect_stale_tenants,
    dirty_tenants,
    purge_record_vectors,
)
from app.config import settings
from app.db import async_session

# 用隨機 fake tenant id — 唔會撞到任何真實 tenant 嘅資料，測試自己收尾
FAKE_TENANT = uuid.UUID("00000000-0000-0000-0000-00000000dead")


@pytest.fixture(autouse=True)
async def _dispose_db_engine():
    """每個 test 之後 dispose engine。

    pytest-asyncio 每個 test 用新 event loop，但 app.db.engine 係 module-level，
    pool 會握住上一個（已關）loop 嘅連線 → RuntimeError: Event loop is closed /
    Future attached to a different loop（跑多個 test 檔時必中）。
    """
    yield
    from app.db import engine
    await engine.dispose()


async def _seed_doc(db, record_id: uuid.UUID) -> uuid.UUID:
    """直接種一份 vector_document（+1 chunk）代表「同一記錄已索引過」。"""
    doc_id = uuid.uuid4()
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(FAKE_TENANT)}
    )
    await db.execute(
        text("""
            INSERT INTO nexus_ai.vector_documents
                (id, tenant_id, workspace_id, visibility_scope, source_module,
                 source_record_id, created_at)
            VALUES (:id, :t, :t, 'workspace', 'company', :rec, now())
        """),
        {"id": doc_id, "t": FAKE_TENANT, "rec": record_id},
    )
    await db.execute(
        text("""
            INSERT INTO nexus_ai.vector_document_chunks
                (id, document_id, chunk_text, embedding, tenant_id, workspace_id, visibility_scope)
            VALUES (:id, :doc, 'seed', CAST(:vec AS vector), :t, :t, 'workspace')
        """),
        {"id": uuid.uuid4(), "doc": doc_id, "t": FAKE_TENANT, "vec": str([0.0] * 1536)},
    )
    await db.commit()
    return doc_id


@pytest.mark.asyncio
async def test_purge_removes_existing_vectors_for_a_record():
    """purge_record_vectors 要清走該記錄所有舊 doc + chunk（令重建 idempotent）。"""
    rec = uuid.uuid4()
    async with async_session() as db:
        try:
            await _seed_doc(db, rec)
            await _seed_doc(db, rec)  # 模擬已重建過一次 → 兩份

            async with async_session() as db2:
                await purge_record_vectors(
                    db2, tenant_id=FAKE_TENANT, source_module="company", source_record_id=rec
                )
                await db2.commit()

            left = (
                await db.execute(
                    text("""
                        SELECT count(*) FROM nexus_ai.vector_documents
                        WHERE tenant_id = :t AND source_module = 'company'
                          AND source_record_id = :rec
                    """),
                    {"t": FAKE_TENANT, "rec": rec},
                )
            ).scalar()
            assert left == 0, f"purge 之後應該 0 份，實際 {left} 份（會令索引重複膨脹）"
        finally:
            await db.execute(
                text("DELETE FROM nexus_ai.vector_documents WHERE tenant_id = :t"),
                {"t": FAKE_TENANT},
            )
            await db.commit()


@pytest.mark.asyncio
async def test_dirty_tenants_detects_recent_changes():
    """dirty_tenants 要搵到「最近有改動」嘅 tenant。

    跨 tenant 掃描一定要用 admin session（BYPASSRLS）—— app role 受 RLS 限制，
    正常情況只會見到自己 tenant（呢個就係點解 job 要 admin session 做偵測）。
    唔改真實資料：用時間窗對比 —— 未來時間窗應該冇 tenant，好遠嘅過去應該有。
    """
    if not settings.nexus_admin_database_url:
        pytest.skip("NEXUS_ADMIN_DATABASE_URL 未設定 — 跨 tenant 偵測用唔到")

    from app.db_admin import _get_admin_sessionmaker

    async with _get_admin_sessionmaker()() as adb:
        recently = await dirty_tenants(adb, since=datetime.now(timezone.utc) + timedelta(days=1))
        assert not recently, "未來時間窗唔應該有 dirty tenant"

        long_ago = await dirty_tenants(
            adb, since=datetime.now(timezone.utc) - timedelta(days=3650)
        )
        assert long_ago, "過去 10 年應該有 tenant 改過 CRM 記錄（否則偵測壞咗）"

        # 隔離：偵測出嚟嘅一定係真 tenant_id，唔會係空 / 亂值
        assert all(isinstance(t, uuid.UUID) for t in long_ago)


def test_detect_stale_tenants_flags_lag():
    """落後超閾值要判斷得出；閾值內唔算 stale。"""
    now = datetime.now(timezone.utc)
    state = {
        "t-fresh": now - timedelta(minutes=5),
        "t-lagging": now - timedelta(hours=48),
    }
    stale = detect_stale_tenants(state, now=now, max_lag=timedelta(hours=24))
    assert stale == ["t-lagging"], f"應該只有 t-lagging 超標，實際 {stale}"

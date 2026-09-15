"""Error monitoring — 紅燈先行（migration 026 未上之前應該 fail）。

契約：
 1. 未處理 exception / 5xx → 寫一筆 error_events
 2. 噪音路徑（/health 等）唔記
 3. 記錄失敗唔可以令原本嘅請求再爆（best-effort）
 4. admin 可以跨 tenant 讀（list_errors）
"""

import uuid

import pytest
from sqlalchemy import text

from app.db import async_session
from app.db_admin import _get_admin_sessionmaker
from app.services.error_monitor import (
    ErrorMonitorMiddleware,
    error_count_recent,
    list_errors,
    record_error,
)

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000f0001")
MARK = "/api/v1/__test_boom__"


@pytest.fixture(autouse=True)
async def _dispose_db_engine():
    """兩個 engine 都要 dispose（**跑之前 + 跑之後**）—— pytest-asyncio 每個 test 用新
    event loop，module-level engine 嘅 pool 會握住上一個 loop 嘅連線；跑全 suite 時
    （多個 test 檔共用一個 process）就會 `RuntimeError: Event loop is closed`。
    開始前先 dispose 係關鍵。"""
    from app.db import engine

    await engine.dispose()
    try:
        from app.db_admin import _get_admin_sessionmaker

        admin_engine = getattr(_get_admin_sessionmaker(), "kw", {}).get("bind")
        if admin_engine is not None:
            await admin_engine.dispose()
    except Exception:
        pass
    yield
    await engine.dispose()
    try:
        from app.db_admin import _get_admin_sessionmaker

        admin_engine = getattr(_get_admin_sessionmaker(), "kw", {}).get("bind")
        if admin_engine is not None:
            await admin_engine.dispose()
    except Exception:
        pass


async def _count(path_mark: str = MARK, tenant=None) -> int:
    async with _get_admin_sessionmaker()() as adb:
        if tenant is not None:
            return int((await adb.execute(
                text("SELECT count(*) FROM nexus_ai.error_events WHERE tenant_id = :t"),
                {"t": tenant})).scalar() or 0)
        return int((await adb.execute(
            text("SELECT count(*) FROM nexus_ai.error_events WHERE path = :p"), {"p": path_mark})).scalar() or 0)


async def _cleanup():
    async with _get_admin_sessionmaker()() as adb:
        await adb.execute(text("DELETE FROM nexus_ai.error_events WHERE tenant_id = :t"), {"t": TENANT})
        await adb.execute(text("DELETE FROM nexus_ai.error_events WHERE path = :p"), {"p": MARK})
        await adb.commit()


@pytest.mark.asyncio
async def test_record_error_writes_row():
    await _cleanup()
    try:
        await record_error(
            method="GET", path=MARK, status_code=500,
            error_type="ValueError", message="boom", tenant_id=TENANT, user_id=None,
        )
        assert await _count(tenant=TENANT) == 1
        assert await _count() == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_health_paths_are_not_recorded():
    await _cleanup()
    try:
        await record_error(path="/api/v1/ai/health", status_code=500, error_type="X", message="noise")
        async with _get_admin_sessionmaker()() as adb:
            n = (await adb.execute(text(
                "SELECT count(*) FROM nexus_ai.error_events WHERE path = '/api/v1/ai/health'"))).scalar()
        assert int(n or 0) == 0, "噪音路徑唔應該記錄"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_middleware_captures_unhandled_exception():
    """真 ASGI middleware：入面 raise → 記錄 + 照樣 re-raise（唔吞錯）。"""
    await _cleanup()

    async def boom_app(scope, receive, send):
        raise RuntimeError("middleware boom")

    mw = ErrorMonitorMiddleware(boom_app)
    scope = {"type": "http", "method": "POST", "path": MARK, "headers": []}
    try:
        with pytest.raises(RuntimeError):
            await mw(scope, None, None)
        assert await _count() == 1, "middleware 應該記錄未處理 exception"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_middleware_records_5xx_without_exception():
    """冇 exception 但 response 500 → 都要記錄。"""
    await _cleanup()

    async def five_xx_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": b"err"})

    sent = []

    async def fake_send(message):
        sent.append(message)

    mw = ErrorMonitorMiddleware(five_xx_app)
    scope = {"type": "http", "method": "GET", "path": MARK, "headers": []}
    try:
        await mw(scope, None, fake_send)
        assert sent and sent[0]["status"] == 500, "response 要照樣傳落去"
        assert await _count() == 1, "5xx 應該記錄"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_list_errors_and_recent_count():
    await _cleanup()
    try:
        await record_error(method="GET", path=MARK, status_code=500,
                           error_type="Boom", message="m", tenant_id=TENANT)
        async with _get_admin_sessionmaker()() as adb:
            data = await list_errors(adb, hours=24)
            assert data["total"] >= 1
            assert any(r["path"] == MARK for r in data["recent"])
            assert await error_count_recent(adb, minutes=60) >= 1
    finally:
        await _cleanup()

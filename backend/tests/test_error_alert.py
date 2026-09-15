"""Error 告警 + retention — 紅燈先行。

契約：
 1. 窗口內錯誤 ≥ 閾值 → 告警（通知 owner），並寫 cooldown 檔
 2. 未達閾值 → 唔告警
 3. Cooldown 期內 → 抑制（唔會洗版），但**仍然出 warning log**（唔准靜默）
 4. Retention 刪 >N 日嘅 row，唔會誤刪新 row

2026-09-15：check_and_alert 加 tenant 參數，test 一律傳自己嘅 tenant（T），
否則其他 test 產生嘅真錯誤（例如 oauth callback 嘅 502）會計入全局窗口，
令 below-threshold 測試隨機紅。
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db_admin import _get_admin_sessionmaker
from app.services.error_alert_job import (
    COOLDOWN_PATH,
    THRESHOLD,
    check_and_alert,
    run_retention,
)

T = uuid.UUID("00000000-0000-0000-0000-0000000ea001")


@pytest.fixture(autouse=True)
async def _dispose_and_reset():
    """每個 test 之前：先 dispose engine（清走上一個 loop 嘅連線，跑全 suite 必需要）
    + 清 cooldown 檔；之後：清測試資料 + 再 dispose。"""
    from app.db import engine

    await engine.dispose()
    for p in (COOLDOWN_PATH, "/tmp/error_alert.lock"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    yield
    async with _get_admin_sessionmaker()() as adb:
        await adb.execute(text("DELETE FROM nexus_ai.error_events WHERE tenant_id = :t"), {"t": T})
        await adb.execute(text(
            "DELETE FROM nexus_ai.error_events WHERE error_type = 'ALERT_THRESHOLD'"))
        await adb.commit()
    for p in (COOLDOWN_PATH, "/tmp/error_alert.lock"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    from app.db import engine
    await engine.dispose()
    try:
        eng = getattr(_get_admin_sessionmaker(), "kw", {}).get("bind")
        if eng is not None:
            await eng.dispose()
    except Exception:
        pass


async def _seed(n: int, *, age_days: int = 0):
    # 用 app session（有 INSERT 權）+ 設 RLS GUC —— 唔靠 admin session INSERT
    # （nexus_admin 刻意只有 SELECT+DELETE，最小權限）
    from app.db import async_session

    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        for i in range(n):
            await db.execute(
                text("""
                    INSERT INTO nexus_ai.error_events
                        (tenant_id, method, path, status_code, error_type, message, occurred_at)
                    VALUES (:t, 'GET', :p, 500, 'Boom', 'x', now() - make_interval(days => :d))
                """),
                {"t": T, "p": f"/api/v1/alert-test-{i}", "d": age_days},
            )
        await db.commit()


@pytest.mark.asyncio
async def test_alert_when_over_threshold():
    await _seed(THRESHOLD + 1)
    res = await check_and_alert(tenant_id=str(T))
    assert res["total"] >= THRESHOLD + 1
    assert res["alerted"] is True, res
    assert os.path.exists(COOLDOWN_PATH), "應該寫咗 cooldown 檔"
    # 告警要真係落地（會出現在 admin Errors 頁）
    async with _get_admin_sessionmaker()() as adb:
        n = (await adb.execute(text(
            "SELECT count(*) FROM nexus_ai.error_events WHERE error_type = 'ALERT_THRESHOLD'"))).scalar()
    assert int(n or 0) >= 1, "告警應該寫入 error_events"


@pytest.mark.asyncio
async def test_no_alert_below_threshold():
    await _seed(max(1, THRESHOLD - 1))
    res = await check_and_alert(tenant_id=str(T))
    assert res["alerted"] is False
    assert res["skipped"] is None


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeat_alert():
    await _seed(THRESHOLD + 2)
    first = await check_and_alert(tenant_id=str(T))
    assert first["alerted"] is True
    second = await check_and_alert(tenant_id=str(T))
    assert second["alerted"] is False
    assert second["skipped"] == "cooldown", "第二次應該被 cooldown 抑制"


@pytest.mark.asyncio
async def test_retention_only_deletes_old_rows():
    await _seed(2, age_days=0)
    await _seed(1, age_days=45)
    before = None
    async with _get_admin_sessionmaker()() as adb:
        before = (await adb.execute(text(
            "SELECT count(*) FROM nexus_ai.error_events WHERE tenant_id = :t"), {"t": T})).scalar()
    assert int(before) == 3

    deleted = await run_retention(days=30)
    assert deleted >= 1

    async with _get_admin_sessionmaker()() as adb:
        left = (await adb.execute(text(
            "SELECT count(*) FROM nexus_ai.error_events WHERE tenant_id = :t"), {"t": T})).scalar()
    assert int(left) == 2, "只應該刪走 45 日前嗰條"

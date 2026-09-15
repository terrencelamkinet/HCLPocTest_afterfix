"""Status page（uptime + incident）— 紅燈先行。

設計取捨：
  - **唔加 incident 表** —— incident「由連續失敗推導」（查詢時計）→ 冇 state 可以漂移，
    亦唔使兩個表同步
  - **唔加 tenant_id / RLS** —— uptime 係平台基建數據，唔屬任何 tenant（唔好為咗一致而硬加）
  - probe 嘅 HTTP client **可注入** → 測試唔會真打 network（但 CLI 會真打）

契約：
 1. 探到 200 → `ok=True`；探到 503 → `ok=False`（唔可以當成功）
 2. **目標連唔到（raise）都要照記錄成失敗** —— probe 一個 down 咗嘅服務唔可以自己炸
 3. 連續失敗（≥ min_consecutive）→ 1 個 incident window；單次失敗唔算（避免誤報）
 4. uptime %  = ok / total
 5. report 要有 per-probe uptime、平均 latency、最新狀態、incidents
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db import async_session
from app.services.uptime_probe import (
    PROBES,
    derive_incidents,
    probe_once,
    uptime_pct,
    uptime_report,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    """可注入嘅假 HTTP client：按 URL 回狀態，或者 raise。"""

    def __init__(self, behaviour: dict):
        self.behaviour = behaviour

    async def get(self, url, timeout=None):
        b = self.behaviour.get(url)
        if isinstance(b, Exception):
            raise b
        if b is None:
            raise RuntimeError("no behaviour configured")
        return FakeResponse(b)


@pytest.fixture(autouse=True)
async def _db_fixture():
    from app.db import engine

    await engine.dispose()
    yield
    try:
        async with async_session() as db:
            await db.execute(text("DELETE FROM nexus_ai.uptime_probes WHERE probe_name LIKE 'test_%'"))
            await db.commit()
    except Exception:
        pass
    await engine.dispose()


# ── 1/2. probe_once ──

@pytest.mark.asyncio
async def test_probe_once_records_success_and_failure():
    targets = [
        {"name": "test_up", "url": "http://x/up", "expect": 200},
        {"name": "test_down", "url": "http://x/down", "expect": 200},
    ]
    client = FakeClient({"http://x/up": 200, "http://x/down": 503})

    results = await probe_once(targets=targets, client=client)

    assert len(results) == 2
    by_name = {r["probe_name"]: r for r in results}
    assert by_name["test_up"]["ok"] is True
    assert by_name["test_down"]["ok"] is False, "503 唔可以當成功"
    assert by_name["test_up"]["latency_ms"] is not None


@pytest.mark.asyncio
async def test_probe_once_survives_connection_error():
    targets = [{"name": "test_dead", "url": "http://x/dead", "expect": 200}]
    client = FakeClient({"http://x/dead": ConnectionError("Connection refused")})

    results = await probe_once(targets=targets, client=client)  # 唔應該 raise

    assert results[0]["ok"] is False
    assert "Connection refused" in (results[0]["error"] or "")


# ── 3. incident 推導（純函數）──

def test_derive_incidents_from_consecutive_failures():
    rows = [
        {"probe_name": "main_api", "ok": True, "checked_at": NOW},
        {"probe_name": "main_api", "ok": False, "checked_at": NOW + timedelta(minutes=1)},
        {"probe_name": "main_api", "ok": False, "checked_at": NOW + timedelta(minutes=2)},
        {"probe_name": "main_api", "ok": False, "checked_at": NOW + timedelta(minutes=3)},
        {"probe_name": "main_api", "ok": True, "checked_at": NOW + timedelta(minutes=4)},
    ]
    inc = derive_incidents(rows, min_consecutive=2)
    assert len(inc) == 1, inc
    assert inc[0]["probe_name"] == "main_api"
    assert inc[0]["failed_probes"] == 3
    assert inc[0]["started_at"] == NOW + timedelta(minutes=1)
    assert inc[0]["resolved"] is True


def test_single_blip_is_not_an_incident():
    rows = [
        {"probe_name": "main_api", "ok": True, "checked_at": NOW},
        {"probe_name": "main_api", "ok": False, "checked_at": NOW + timedelta(minutes=1)},
        {"probe_name": "main_api", "ok": True, "checked_at": NOW + timedelta(minutes=2)},
    ]
    assert derive_incidents(rows, min_consecutive=2) == [], "單次失敗唔應該報 incident"


def test_unresolved_incident_still_open():
    rows = [
        {"probe_name": "admin_api", "ok": False, "checked_at": NOW},
        {"probe_name": "admin_api", "ok": False, "checked_at": NOW + timedelta(minutes=1)},
    ]
    inc = derive_incidents(rows, min_consecutive=2)
    assert len(inc) == 1
    assert inc[0]["resolved"] is False, "仍然失敗 = 未解決"


# ── 4. uptime % ──

def test_uptime_pct():
    rows = [
        {"probe_name": "a", "ok": True},
        {"probe_name": "a", "ok": True},
        {"probe_name": "a", "ok": True},
        {"probe_name": "a", "ok": False},
    ]
    s = uptime_pct(rows)
    assert s["a"]["total"] == 4
    assert s["a"]["ok"] == 3
    assert abs(s["a"]["pct"] - 75.0) < 0.01


# ── 5. 落庫 + report ──

@pytest.mark.asyncio
async def test_probe_writes_rows_and_report_reads_them():
    targets = [{"name": "test_live", "url": "http://x/up", "expect": 200}]
    client = FakeClient({"http://x/up": 200})

    async with async_session() as db:
        await probe_once(targets=targets, client=client, db=db, persist=True)
        rep = await uptime_report(db, hours=1, probes=[{"name": "test_live", "url": "http://x/up"}])

    assert rep["probes"]["test_live"]["total"] >= 1
    assert rep["probes"]["test_live"]["pct"] == 100.0
    assert rep["probes"]["test_live"]["latest_ok"] is True
    assert isinstance(rep["incidents"], list)


def test_probes_registry_has_the_three_services():
    names = {p["name"] for p in PROBES}
    assert {"main_api", "admin_api", "admin_web"} <= names, names

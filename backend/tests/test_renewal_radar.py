"""Renewal Radar — 紅燈先行。

**為咩存在**：CRM 用戶會唔記得客戶合約／訂閱／licence 幾時到期 → 白白走失續約生意。
完全冇任何 renewal 概念（DB 冇表、model 冇 field）。

契約：
 1. `days_left` / `is_due` 純函數：`renewal_date - notice_days` 到咗就要提醒；
    已過期但唔太久（≤30 日）**都要提醒**（overdue 警告）；太舊（>30 日）當死線已過，唔再嘈
 2. `scan_renewals` 只返 status='active' 且 due 嘅
 3. `notify_due_renewals` 寫通知 + stamp `last_notified_at`
 4. **Idempotent（7 日窗口）**：同一張唔應該日日再發 → 唔係日日嘈
 5. 冇 owner 就唔發（唔可以通知「冇人」）
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.db import async_session
from app.services.renewal_radar import (
    days_left,
    is_due,
    notify_due_renewals,
    scan_renewals,
)

T = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.UUID("a77d12c5-c02f-4335-88b2-1f293a74fe6f")  # 真 user（FK 要求）
TODAY = date(2026, 9, 12)
_IDS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _db_fixture():
    from app.db import engine

    await engine.dispose()
    _IDS.clear()
    yield
    try:
        if _IDS:
            async with async_session() as db:
                await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
                await db.execute(
                    text("DELETE FROM nexus_crm.renewals WHERE tenant_id = :t AND id = ANY(:ids)"),
                    {"t": T, "ids": _IDS},
                )
                await db.execute(
                    text("DELETE FROM nexus_crm.notifications WHERE source_record_id = ANY(:ids)"),
                    {"ids": _IDS},
                )
                await db.commit()
    except Exception:
        pass
    _IDS.clear()
    await engine.dispose()


async def _ws(db) -> uuid.UUID:
    row = (
        await db.execute(
            text("SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :t LIMIT 1"), {"t": T}
        )
    ).first()
    return row[0] if row else uuid.uuid4()


async def _add(db, *, name, renewal_date, notice_days=30, status="active", owner=USER) -> uuid.UUID:
    rid = uuid.uuid4()
    _IDS.append(rid)
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
    await db.execute(
        text("""
            INSERT INTO nexus_crm.renewals
                (id, tenant_id, workspace_id, name, renewal_date, notice_days, status, owner_id,
                 amount, currency, created_by)
            VALUES (:id, :t, :ws, :name, :rd, :nd, :st, :owner, 12000, 'HKD', :owner)
        """),
        {"id": rid, "t": T, "ws": await _ws(db), "name": name, "rd": renewal_date,
         "nd": notice_days, "st": status, "owner": owner},
    )
    await db.commit()
    return rid


# ── 1. 純函數 ──

def test_days_left():
    assert days_left(date(2026, 10, 12), TODAY) == 30
    assert days_left(date(2026, 9, 2), TODAY) == -10


def test_is_due_window():
    assert is_due(date(2026, 10, 12), 30, TODAY) is True, "30 日後到期、提前 30 日通知 → due"
    assert is_due(date(2026, 12, 1), 30, TODAY) is False, "仲有 80 日 → 未 due"
    assert is_due(date(2026, 9, 2), 30, TODAY) is True, "過期 10 日 → 要提醒（overdue）"
    assert is_due(date(2026, 6, 1), 30, TODAY) is False, "過期 100 日 → 死線已過，唔再嘈"


# ── 2. scan ──

@pytest.mark.asyncio
async def test_scan_only_returns_due_active():
    async with async_session() as db:
        due_id = await _add(db, name="到期合約", renewal_date=TODAY + timedelta(days=10))
        await _add(db, name="未到期合約", renewal_date=TODAY + timedelta(days=200))
        await _add(db, name="已取消", renewal_date=TODAY + timedelta(days=5), status="cancelled")

        rows = await scan_renewals(db, T, today=TODAY)

        names = [r["name"] for r in rows]
        assert "到期合約" in names
        assert "未到期合約" not in names
        assert "已取消" not in names, "cancelled 唔應該提醒"
        assert str(due_id) in [str(r["id"]) for r in rows]


# ── 3/4. 通知 + idempotency ──

@pytest.mark.asyncio
async def test_notify_then_does_not_renotify_same_day():
    async with async_session() as db:
        rid = await _add(db, name="通知測試合約", renewal_date=TODAY + timedelta(days=7))

        r1 = await notify_due_renewals(db, T, today=TODAY)
        assert r1["notified"] >= 1, r1

        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        n = (
            await db.execute(
                text("SELECT count(*) FROM nexus_crm.notifications WHERE source_record_id = :id"),
                {"id": rid},
            )
        ).scalar()
        assert n == 1, f"應該寫 1 個通知（實際 {n}）"

        r2 = await notify_due_renewals(db, T, today=TODAY)
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        n2 = (
            await db.execute(
                text("SELECT count(*) FROM nexus_crm.notifications WHERE source_record_id = :id"),
                {"id": rid},
            )
        ).scalar()
        assert n2 == 1, f"同一日唔應該再發（實際 {n2}；r2={r2}）"


@pytest.mark.asyncio
async def test_no_owner_no_notification():
    async with async_session() as db:
        rid = await _add(db, name="冇 owner 合約", renewal_date=TODAY + timedelta(days=3), owner=None)
        await notify_due_renewals(db, T, today=TODAY)
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        n = (
            await db.execute(
                text("SELECT count(*) FROM nexus_crm.notifications WHERE source_record_id = :id"),
                {"id": rid},
            )
        ).scalar()
        assert n == 0, "冇 owner 唔應該發通知"

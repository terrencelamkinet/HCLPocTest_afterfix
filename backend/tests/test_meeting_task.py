"""Meeting → Task 自動轉換 — 紅燈先行。

背景：`calendar_followup.py` 嘅 T+30 engine 只係**問用戶**「有冇跟進」（出 touchpoint 草稿），
**從來冇建立 Task** → 跟進事項唔會入任務清單，即係冇人會做。呢個 module 補嗰忽。

設計（用返 tasks 表本身為此而設嘅欄）：
  - `auto_suggested=True` + `suggestion_confidence` → UI 分得出「AI 建議」vs「人手建立」
  - `linked_via_signal = <event id>` → **去重鍵**（同一會議唔可以出兩張 task）

⚠️ 呢個 test 用**真 tenant**（`tasks.tenant_id` 有 FK 去 `nexus_auth.nexus_auth_tenants`，
塞假 tenant 會 IntegrityError —— 2026-09-12 踩過）。
清理**只按本 test 自己 generate 嘅 event id**（`linked_via_signal`）→ 絕對唔會誤刪真 task。
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.db import async_session
from app.services.meeting_task import create_task_from_meeting

# 真 tenant + 真 user（`tasks.tenant_id` / `assignee_id` / `created_by` 全部有 FK 去
# `nexus_auth` 表，塞假 id 會 ForeignKeyViolationError —— 2026-09-12 踩過）。
# 清理只針對下方 _CREATED_EVENTS 記住嘅 event id。
T = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT = uuid.UUID("00000000-0000-0000-0000-0000000f1002")
USER = uuid.UUID("a77d12c5-c02f-4335-88b2-1f293a74fe6f")  # terrence_lam@kinetix.com.hk

_CREATED_EVENTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _db_fixture():
    from app.db import engine

    await engine.dispose()
    _CREATED_EVENTS.clear()
    yield
    try:
        if _CREATED_EVENTS:
            async with async_session() as db:
                await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
                await db.execute(
                    text(
                        "DELETE FROM nexus_crm.tasks "
                        "WHERE tenant_id = :t AND linked_via_signal = ANY(:ids)"
                    ),
                    {"t": T, "ids": _CREATED_EVENTS},
                )
                await db.commit()
    except Exception:
        pass
    _CREATED_EVENTS.clear()
    await engine.dispose()


async def _workspace_id(db) -> uuid.UUID:
    """攞一個真實 workspace（`tasks.workspace_id` NOT NULL；表喺 `nexus_auth.workspaces`，
    唔係 nexus_crm —— 2026-09-12 踩過 UndefinedTableError）。"""
    row = (
        await db.execute(
            text("SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :t LIMIT 1"), {"t": T}
        )
    ).first()
    return row[0] if row else uuid.uuid4()


def _new_event() -> uuid.UUID:
    e = uuid.uuid4()
    _CREATED_EVENTS.append(e)
    return e


@pytest.mark.asyncio
async def test_creates_task_from_meeting():
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        ws = await _workspace_id(db)
        event_id = _new_event()
        due = date.today() + timedelta(days=1)

        res = await create_task_from_meeting(
            db, tenant_id=T, user_id=USER, workspace_id=ws,
            event_id=event_id, event_title="與三六零數字安全開會",
            company_id=None, contact_id=None, due_date=due,
        )
        assert res["created"] is True, res

        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        row = (
            await db.execute(
                text("""
                    SELECT title, due_date, auto_suggested, suggestion_confidence,
                           linked_via_signal, assignee_id, status, workspace_id
                    FROM nexus_crm.tasks WHERE id = :id
                """),
                {"id": res["task_id"]},
            )
        ).mappings().first()

        assert row is not None, "應該建立到 task"
        assert "三六零數字安全" in row["title"], f"title 要帶出會議內容：{row['title']}"
        assert row["due_date"] == due
        assert row["auto_suggested"] is True, "要標記為 AI 建議"
        assert row["linked_via_signal"] == event_id, "linked_via_signal 要記住個 event"
        assert row["suggestion_confidence"] is not None
        assert float(row["suggestion_confidence"]) > 0
        assert row["assignee_id"] == USER
        assert row["status"] == "pending"
        assert row["workspace_id"] == ws


@pytest.mark.asyncio
async def test_idempotent_same_event_creates_one_task():
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        ws = await _workspace_id(db)
        event_id = _new_event()
        due = date.today() + timedelta(days=1)

        r1 = await create_task_from_meeting(
            db, tenant_id=T, user_id=USER, workspace_id=ws, event_id=event_id,
            event_title="重複測試會議", company_id=None, contact_id=None, due_date=due,
        )
        r2 = await create_task_from_meeting(
            db, tenant_id=T, user_id=USER, workspace_id=ws, event_id=event_id,
            event_title="重複測試會議", company_id=None, contact_id=None, due_date=due,
        )
        assert r1["created"] is True
        assert r2["created"] is False, f"第二次唔應該再建：{r2}"
        assert r2["reason"] == "exists"

        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM nexus_crm.tasks "
                    "WHERE tenant_id = :t AND linked_via_signal = :e"
                ),
                {"t": T, "e": event_id},
            )
        ).scalar()
        assert n == 1, f"同一 event 只可以有一張 task（實際 {n}）"


@pytest.mark.asyncio
async def test_blank_event_title_still_produces_valid_task():
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        ws = await _workspace_id(db)

        res = await create_task_from_meeting(
            db, tenant_id=T, user_id=USER, workspace_id=ws, event_id=_new_event(),
            event_title="   ", company_id=None, contact_id=None,
            due_date=date.today() + timedelta(days=1),
        )
        assert res["created"] is True
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        title = (
            await db.execute(
                text("SELECT title FROM nexus_crm.tasks WHERE id = :id"), {"id": res["task_id"]}
            )
        ).scalar()
        assert title and title.strip(), f"title 唔可以空白：{title!r}"


@pytest.mark.asyncio
async def test_ask_followup_creates_task(monkeypatch):
    """**接線驗證**：`ask_followup` 應該真係建立 Task（唔止 service 自己 work）。

    通知函數 monkeypatch 走（唔想發真通知俾用戶），亦用 fake event id → 唔會改到真 event。
    """
    import app.services.calendar_followup as cf

    async def fake_notify(db, tenant_id, user_id, ev, body, title=None):
        return True

    async def fake_channel_enabled(db, tenant_id, user_id, ch):
        return False

    monkeypatch.setattr(cf, "_inapp_notify", fake_notify)
    monkeypatch.setattr(cf, "_channel_enabled", fake_channel_enabled)

    event_id = _new_event()

    class FakeEvent:
        id = event_id
        title = "接線測試會議"
        project_id = None
        workspace_id = None
        contact_id = None

    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        res = await cf.ask_followup(db, T, USER, FakeEvent())
        await db.commit()

        assert res["asked"] is True, res
        assert res.get("task") is not None, f"ask_followup 應該帶 task 結果返嚟：{res}"
        assert res["task"]["created"] is True, res["task"]

        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM nexus_crm.tasks "
                    "WHERE tenant_id = :t AND linked_via_signal = :e AND auto_suggested = true"
                ),
                {"t": T, "e": event_id},
            )
        ).scalar()
        assert n == 1, f"應該由會議建立到 1 張 task（實際 {n}）"


@pytest.mark.asyncio
async def test_tenant_isolation():
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        ws = await _workspace_id(db)
        await create_task_from_meeting(
            db, tenant_id=T, user_id=USER, workspace_id=ws, event_id=_new_event(),
            event_title="隔離測試會議", company_id=None, contact_id=None, due_date=date.today(),
        )

    async with async_session() as db2:
        await db2.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(OTHER_TENANT)}
        )
        n = (
            await db2.execute(
                text("SELECT count(*) FROM nexus_crm.tasks WHERE tenant_id = :t"), {"t": T}
            )
        ).scalar()
        assert n == 0, f"第二個 tenant 唔應該睇到（實際 {n}）"

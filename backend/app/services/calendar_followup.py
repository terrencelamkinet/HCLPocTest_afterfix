"""Calendar T+30 touchpoint follow-up engine (P3, 2026-09-09).

Design: docs/calendar-crm-integration-design-v3-2026-09-09.md §1/§5 + §11:
- T+30 (event end + 30min): check whether a touchpoint already exists for the
  event (linked company/contact within the event window). If yes → silent
  (status 'created'). If no → ASK the user once (unified tone per Q4; no
  auto-mute per Q1 — but only asks once per event).
- Reply handling routes through telegram_inbound (see _handle_pending_followup)
  — "唔使" → skipped; content → AI composes a touchpoint draft (reusing the
  draft→confirm flow), confirm executes and links the resolved company.
- WhatsApp channel bypassed (user 2026-09-09).
"""
from datetime import timedelta

from sqlalchemy import text

from app.services.calendar_lifecycle_job import (  # noqa: E402
    _channel_enabled,
    _inapp_notify,
    _push_channel,
    _utcnow,
)

FOLLOWUP_DELAY_MIN = 30       # event end + 30 min → ask
FOLLOWUP_WINDOW_HOURS = 24    # user reply window before auto-expire


import logging

logger = logging.getLogger(__name__)


async def _event_company_id(db, ev) -> str | None:
    """Resolve the CRM company linked to this event (via project_id)."""
    pid = getattr(ev, "project_id", None)
    if not pid:
        return None
    row = (
        await db.execute(
            text("SELECT company_id FROM nexus_crm.projects WHERE id = :pid"),
            {"pid": str(pid)},
        )
    ).fetchone()
    return str(row[0]) if row and row[0] else None


async def _touchpoint_exists(db, tenant_id, user_id, ev, company_id: str | None) -> bool:
    """A touchpoint recorded for this event/company in the event window counts
    as 'already logged' (user may have added it manually in CRM)."""
    rows = (
        await db.execute(
            text(
                "SELECT id FROM nexus_crm.touchpoints "
                "WHERE (company_id = :cid OR (company_id IS NULL AND :cid IS NULL)) "
                "  AND date >= :start AND date <= :window "
                "LIMIT 1"
            ),
            {
                "cid": company_id,
                "start": getattr(ev, "start", None),
                "window": getattr(ev, "end", None) + timedelta(minutes=FOLLOWUP_DELAY_MIN)
                if getattr(ev, "end", None) else _utcnow(),
            },
        )
    ).fetchall()
    return len(rows) > 0


def _compose_ask(ev, company_name: str | None) -> str:
    head = (
        f"🤖 你啱啱開完會（{getattr(ev, 'end', None).astimezone().strftime('%H:%M') if getattr(ev, 'end', None) else ''}完）\n"
        f"📋 {getattr(ev, 'title', '')}"
    )
    if company_name:
        head += f"\n🏢 {company_name}"
    head += (
        "\n\nCRM 未有今次 meeting 嘅記錄。要唔要我幫你記低？\n"
        "直接講內容（例如「傾咗續約，佢話下個月決定」），或者覆「唔使」。"
    )
    return head


async def scan_followups(db, tenant_id, user_id, now) -> list[dict]:
    """T+30 due check — returns list of due follow-up events (P3a).

    Only events that ended within the last 48h are asked about (older ones
    auto-expire below — no spam from historical events).
    """
    # Old pending follow-ups (ended > 48h ago) → expired (cleanup, idempotent).
    try:
        await db.execute(
            text(
                "UPDATE nexus_crm.project_calendar_events SET followup_status = 'expired' "
                "WHERE owner_user_id = :uid AND followup_status = 'pending' "
                "  AND \"end\" < :recent"
            ),
            {"uid": str(user_id), "recent": now - timedelta(hours=48)},
        )
    except Exception:
        pass
    due: list[dict] = []
    rows = (
        await db.execute(
            text(
                "SELECT id, title, start, \"end\", project_id, followup_status, "
                "       followup_asked_at "
                "FROM nexus_crm.project_calendar_events "
                "WHERE owner_user_id = :uid "
                "  AND is_all_day = false "
                "  AND followup_status = 'pending' "
                "  AND \"end\" + interval '30 minutes' <= :now "
                "  AND \"end\" >= :recent "
                "ORDER BY \"end\" LIMIT 10"
            ),
            {"uid": str(user_id), "now": now, "recent": now - timedelta(hours=48)},
        )
    ).fetchall()
    for row in rows:
        ev = type("E", (), {
            "id": row[0], "title": row[1], "start": row[2], "end": row[3],
            "project_id": row[4], "fp_status": row[5], "fp_asked_at": row[6],
        })()
        due.append(ev)
    return due


async def ask_followup(db, tenant_id, user_id, ev) -> dict:
    """Run the T+30 ask for one event (P3a). Returns result dict."""
    company_id = await _event_company_id(db, ev)
    company_name = None
    if company_id:
        comp = (
            await db.execute(
                text("SELECT name FROM nexus_crm.companies WHERE id = :cid"),
                {"cid": company_id},
            )
        ).fetchone()
        company_name = comp[0] if comp else None

    # Already logged by the user in CRM → silent (status created).
    if await _touchpoint_exists(db, tenant_id, user_id, ev, company_id):
        await db.execute(
            text(
                "UPDATE nexus_crm.project_calendar_events SET followup_status = 'created' "
                "WHERE id = :eid"
            ),
            {"eid": ev.id},
        )
        return {"asked": False, "reason": "touchpoint_exists", "company_id": company_id}

    body = _compose_ask(ev, company_name)

    # ── Meeting → Task（2026-09-12）──
    # T+30 engine 以前只係「問用戶」，跟進事項**從來冇入任務清單**（只出 touchpoint 草稿）
    # → 所以跟進永遠冇人做。呢度補上：由會議建立一張真 Task。
    # Idempotent（靠 linked_via_signal = event id）→ 重複 scan 都唔會出兩張。
    task_result = None
    try:
        from app.services.meeting_task import create_task_from_meeting

        ws_id = getattr(ev, "workspace_id", None)
        if not ws_id:
            ws_id = (
                await db.execute(
                    text(
                        "SELECT id FROM nexus_auth.workspaces "
                        "WHERE tenant_id = :t ORDER BY created_at LIMIT 1"
                    ),
                    {"t": tenant_id},
                )
            ).scalar()
        if ws_id:
            task_result = await create_task_from_meeting(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                workspace_id=ws_id,
                event_id=ev.id,
                event_title=getattr(ev, "title", None),
                company_id=company_id,
                contact_id=getattr(ev, "contact_id", None),
            )
    except Exception:
        # best-effort：建 task 失敗唔可以斷咗個 follow-up ask
        logger.exception("meeting_task creation failed (event=%s)", getattr(ev, "id", None))

    inapp_ok = await _inapp_notify(
        db, tenant_id, user_id, ev, body, title=f"📝 記錄 Touchpoint：{getattr(ev, 'title', '')}"
    )
    tg_result = "skipped"
    if await _channel_enabled(db, tenant_id, user_id, "telegram"):
        tg_result = await _push_channel(db, tenant_id, user_id, "telegram", body)
    await db.execute(
        text(
            "UPDATE nexus_crm.project_calendar_events "
            "SET followup_status = 'asked', followup_asked_at = :ts "
            "WHERE id = :eid"
        ),
        {"ts": _utcnow(), "eid": ev.id},
    )
    return {
        "asked": True,
        "company_id": company_id,
        "task": task_result,
        "channels": {"inapp": inapp_ok, "telegram": tg_result},
    }

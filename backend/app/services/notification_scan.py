"""
Notification Scan Loop — periodic reminder notifications.

Runs every N minutes inside the FastAPI lifespan (single worker via file lock).
Scans three reminder sources and pushes per-user in-app notifications:

  1. Tasks due today        → notify assignee (once per task, group_key dedup)
  2. Project deadlines      → notify PM/owner at T-3 and T-1 days (once per key)
  3. Calendar events        → notify owner 30 min before start (once per event)

Dedup: every notification carries a stable group_key; if a row with the same
group_key already exists for that user, skip (prevents re-sending on every tick).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models.crm import Task, Project, ProjectCalendarEvent
from app.models.notification import Notification
from app.services.notification_service import notify

log = logging.getLogger("notification_scan")

SCAN_INTERVAL_SECONDS = 300          # 5 min
DUE_TODAY_KEY = "task-due-{date}-{task_id}"
DEADLINE_KEY = "project-deadline-{tminus}-{project_id}"
EVENT_KEY = "cal-remind-{event_id}"


async def _exists(db, tenant_id, user_id, group_key: str) -> bool:
    row = await db.execute(
        select(Notification.id).where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.group_key == group_key,
        ).limit(1)
    )
    return row.scalar_one_or_none() is not None


async def _scan_tasks_due_today(db, tenant_id) -> int:
    """Tasks with due_date == today or tomorrow (HKT) → notify the assignee once.

    SPEC notifications-revamp T4 (2026-09-06): 擴展做今日或聽日 due（原版淨
    today — 用戶極少 today-due tasks → 長年 0 通知；聽日 due 提早一日提）。
    逾期 tasks 唔 spam（唔 trigger）。
    """
    now = datetime.now(timezone.utc)
    hk_today = (now + timedelta(hours=8)).date()
    hk_tomorrow = hk_today + timedelta(days=1)
    rows = (
        await db.execute(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.due_date.in_([hk_today, hk_tomorrow]),
                Task.status.notin_(["done", "cancelled"]),
                Task.assignee_id.isnot(None),
            )
        )
    ).scalars().all()

    sent = 0
    for t in rows:
        key = DUE_TODAY_KEY.format(date=t.due_date.isoformat(), task_id=t.id)
        if await _exists(db, t.tenant_id, t.assignee_id, key):
            continue
        _when = "今日" if t.due_date == hk_today else "聽日"
        await notify(
            db,
            tenant_id=t.tenant_id,
            user_id=t.assignee_id,
            module="task",
            title=f"⏰ {_when}到期任務：{t.title}",
            body=f"Due {t.due_date} · Priority: {t.priority or 'medium'}",
            priority="HIGH" if t.priority == "urgent" else "NORMAL",
            action_url="/tasks",
            group_key=key,
            source_record_type="task",
            source_record_id=t.id,
        )
        sent += 1
    return sent


async def _scan_project_deadlines(db, tenant_id) -> int:
    """Project deadlines at T-3 and T-1 (HKT dates) → notify PM/owner."""
    now = datetime.now(timezone.utc)
    hk_today = (now + timedelta(hours=8)).date()
    targets = {3: "3 日後", 1: "明日"}

    sent = 0
    for tminus, label in targets.items():
        target_date = hk_today + timedelta(days=tminus)
        rows = (
            await db.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.deadline.isnot(None),
                    Project.status.notin_(["done", "cancelled", "archived"]),
                )
            )
        ).scalars().all()
        for p in rows:
            dl = p.deadline
            p_date = (dl + timedelta(hours=8)).date() if isinstance(dl, datetime) and dl.tzinfo else (dl.date() if hasattr(dl, "date") else None)
            if p_date != target_date:
                continue
            owner = p.project_manager_id or p.sales_owner_id
            if not owner:
                continue
            key = DEADLINE_KEY.format(tminus=tminus, project_id=p.id)
            if await _exists(db, p.tenant_id, owner, key):
                continue
            await notify(
                db,
                tenant_id=p.tenant_id,
                user_id=owner,
                module="project",
                title=f"🚩 項目到期（{label}）：{p.name}",
                body=f"Deadline: {p.deadline.strftime('%Y-%m-%d %H:%M')}",
                priority="HIGH" if tminus == 1 else "NORMAL",
                action_url="/projects",
                group_key=key,
                source_record_type="project",
                source_record_id=p.id,
            )
            sent += 1
    return sent


async def _scan_calendar_reminders(db, tenant_id) -> int:
    """Events starting in the next 30 min → notify owner."""
    now = datetime.now(timezone.utc)
    soon = now + timedelta(minutes=30)
    rows = (
        await db.execute(
            select(ProjectCalendarEvent).where(
                ProjectCalendarEvent.tenant_id == tenant_id,
                ProjectCalendarEvent.owner_user_id.isnot(None),
                ProjectCalendarEvent.start > now,
                ProjectCalendarEvent.start <= soon,
            )
        )
    ).scalars().all()

    sent = 0
    for ev in rows:
        key = EVENT_KEY.format(event_id=ev.id)
        if await _exists(db, ev.tenant_id, ev.owner_user_id, key):
            continue
        await notify(
            db,
            tenant_id=ev.tenant_id,
            user_id=ev.owner_user_id,
            module="calendar",
            title=f"📅 30 分鐘後：{ev.title}",
            body=f"開始時間：{ev.start.strftime('%H:%M')}{' · ' + ev.location if ev.location else ''}",
            priority="HIGH",
            action_url="/calendar",
            group_key=key,
            source_record_type="calendar_event",
            source_record_id=ev.id,
        )
        sent += 1
    return sent


async def scan_once(db) -> dict[str, int]:
    """Run all three scans once, iterating per tenant.

    `tasks` has FORCE RLS (`relforcerowsecurity=t`) — a bare SELECT without the
    `app.tenant_id` GUC returns 0 rows. So we loop all tenants, set the GUC per
    tenant (transaction-scoped), and scan that tenant's rows.
    """
    stats = {"tasks_due_today": 0, "project_deadlines": 0, "calendar_reminders": 0}

    tenant_ids = (
        await db.execute(text("SELECT id FROM nexus_auth.nexus_auth_tenants"))
    ).scalars().all()

    for tid in tenant_ids:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tid)},
        )
        stats["tasks_due_today"] += await _scan_tasks_due_today(db, tid)
        stats["project_deadlines"] += await _scan_project_deadlines(db, tid)
        stats["calendar_reminders"] += await _scan_calendar_reminders(db, tid)

    return stats


async def run_scan_loop(stop: asyncio.Event) -> None:
    """Infinite loop — called from lifespan (single worker, file-lock guarded)."""
    while not stop.is_set():
        try:
            from app.db import async_session
            async with async_session() as db:
                stats = await scan_once(db)
                if any(stats.values()):
                    log.info("notification_scan sent: %s", stats)
        except Exception as e:  # noqa: BLE001 — must never crash the app
            log.exception("notification_scan crashed: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=SCAN_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue

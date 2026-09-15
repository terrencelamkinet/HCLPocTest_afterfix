"""
Central Notification Service — single entry point for ALL in-app notifications.

Every module (task / project / calendar / ai / system) calls `notify()` instead
of constructing Notification rows directly. This guarantees:
  - per-user targeting (each notification carries one user_id)
  - preference enforcement (muted modules, priority threshold, quiet hours)
  - consistent fields (module, action_url, group_key) for the frontend

Quiet hours (default 23:00–08:00): notification is STORED (user sees it in the
list) but the frontend is expected to skip the toast popup during that window.
"""

from datetime import datetime, time, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationPreference

# ── module registry (also used by frontend filter tabs + settings UI) ──
MODULES = ("task", "project", "calendar", "ai", "system")

# priority rank for threshold comparison (higher = more urgent)
_PRIORITY_RANK = {"CRITICAL": 3, "HIGH": 2, "NORMAL": 1, "LOW": 0}

DEFAULT_QUIET_START = time(23, 0)
DEFAULT_QUIET_END = time(8, 0)


def is_quiet_hours(now: Optional[datetime] = None) -> bool:
    """True if `now` (default: current UTC→HK time) falls in quiet hours."""
    now = now or datetime.now(timezone.utc)
    # HK = UTC+8; compare local wall-clock time against the quiet window.
    local = (now.astimezone(timezone.utc) + __import__("datetime").timedelta(hours=8)).time()
    if DEFAULT_QUIET_START <= DEFAULT_QUIET_END:  # same-day window (23:00–08:00 wraps)
        return local >= DEFAULT_QUIET_START or local < DEFAULT_QUIET_END
    return DEFAULT_QUIET_START <= local < DEFAULT_QUIET_END


async def notify(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    module: str,
    title: str,
    body: Optional[str] = None,
    priority: str = "NORMAL",
    action_url: Optional[str] = None,
    group_key: Optional[str] = None,
    source_record_type: Optional[str] = None,
    source_record_id: Optional[UUID] = None,
    is_ai_generated: bool = False,
    generated_by_agent_id: Optional[str] = None,
) -> Optional[Notification]:
    """Create one in-app notification for one user, respecting preferences.

    Returns the created Notification, or None when suppressed by preference
    (muted module / below priority threshold).
    """
    if module not in MODULES:
        module = "system"

    # Load per-user preference for this module (lazily created defaults).
    pref = await _get_pref(db, tenant_id, user_id, module)

    if pref is not None and pref.is_muted is True:
        return None
    min_rank = 1
    if pref is not None and pref.priority_min is not None:
        min_rank = _PRIORITY_RANK.get(str(pref.priority_min), 1)
    if _PRIORITY_RANK.get(priority, 1) < min_rank:
        return None

    n = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        source_module=module,
        source_record_type=source_record_type,
        source_record_id=source_record_id,
        title=title,
        body=body,
        priority=priority,
        group_key=group_key,
        is_ai_generated=is_ai_generated,
        generated_by_agent_id=generated_by_agent_id,
        action_url=action_url,
        status="UNREAD",
    )
    db.add(n)
    # NOTE: flush only — NOT commit. The caller owns the transaction (router
    # sessions commit on request end; the scan loop commits per tenant). A
    # commit here would invalidate the caller's pending objects (e.g. a Task
    # being created → `db.refresh(task)` after notify() raises
    # InvalidRequestError "Could not refresh instance").
    await db.flush()
    await db.refresh(n)
    return n


async def _get_pref(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    module: str,
) -> Optional[NotificationPreference]:
    """Fetch the user's preference row for a module; create defaults if missing."""
    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == tenant_id,
            NotificationPreference.user_id == user_id,
            NotificationPreference.module_key == module,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is not None:
        return pref

    # Create default preference row (IN_APP channel, NORMAL threshold, realtime).
    pref = NotificationPreference(
        tenant_id=tenant_id,
        user_id=user_id,
        module_key=module,
        channels=["IN_APP"],
        priority_min="NORMAL",
        is_muted=False,
        digest="REALTIME",
        quiet_start=DEFAULT_QUIET_START,
        quiet_end=DEFAULT_QUIET_END,
        timezone="Asia/Hong_Kong",
        agent_push_enabled=True,
        agent_digest_enabled=True,
    )
    db.add(pref)
    await db.flush()
    return pref


async def ensure_default_preferences(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
    """Create default preference rows for all modules (called on user signup)."""
    # ⚠️ Register flow has NO JWT → no tenant middleware → RLS GUC unset →
    # INSERT into FORCE-RLS notification_preferences raises InsufficientPrivilegeError.
    # Set tenant/user GUC explicitly (transaction-local, same pattern as get_tenant_session).
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
        {"t": str(tenant_id), "u": str(user_id)},
    )
    for module in MODULES:
        await _get_pref(db, tenant_id, user_id, module)

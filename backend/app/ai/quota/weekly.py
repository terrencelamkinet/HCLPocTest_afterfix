"""Weekly AI usage quota — DB-backed per-user weekly request limit.

SPEC: docs/ai-usage-quota-SPEC.md (grill 2026-09-04)

Design
------
- Tenant plan (``free`` / ``pro``) stored in ``nexus_auth.tenants.settings->>'plan'``
  (JSONB, admin-set).  Default = ``free``.
- Per-user weekly request allowance (free = 50/week, pro = unlimited/-1).
- Period = fixed calendar week in HKT (resets Monday 00:00 HKT); key
  ``YYYY-Www`` (ISO week) — matches the ``ai_usage_quotas`` unique index
  ``(user_id, tenant_id, period_key)``.
- Counting = reserve-then-refund: ``reserve_request`` atomically increments
  with a conditional UPDATE (``WHERE requests_used < requests_limit``) so a
  race can never oversell; callers refund on failed LLM calls so errors don't
  consume quota.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

HKT = timezone(timedelta(hours=8))

DEFAULT_PLAN = "free"
PLAN_LIMITS: dict[str, int] = {
    "free": 50,
    "pro": -1,  # -1 = unlimited
}

# Table used by the atomic reserve UPDATE (kept in one place for tests)
QUOTA_TABLE = "nexus_ai.ai_usage_quotas"


class QuotaExceededError(Exception):
    """Raised when the weekly request allowance is exhausted."""

    def __init__(self, used: int, limit: int, reset_on: date) -> None:
        self.used = used
        self.limit = limit
        self.reset_on = reset_on
        super().__init__(f"weekly quota exceeded: {used}/{limit} (resets {reset_on})")


def _now_hkt() -> datetime:
    return datetime.now(HKT)


def weekly_period_key(now: datetime | None = None) -> str:
    """ISO-week key for `now` (HKT), e.g. ``2026-W37``."""
    now = now or _now_hkt()
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def reset_at(now: datetime | None = None) -> date:
    """Date of the next Monday 00:00 HKT (period rollover)."""
    now = now or _now_hkt()
    days_until_monday = (7 - now.weekday()) % 7  # Monday=0
    if days_until_monday == 0:
        days_until_monday = 7  # already Monday → next week
    nxt = (now + timedelta(days=days_until_monday)).date()
    return nxt


def plan_limit(plan: str | None) -> int:
    """Weekly request limit for a plan. Unknown plan → free default."""
    return PLAN_LIMITS.get(plan or "", PLAN_LIMITS[DEFAULT_PLAN])


# ---------------------------------------------------------------------------
# Tenant plan (settings JSONB)
# ---------------------------------------------------------------------------
async def get_tenant_plan(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    row = (
        await db.execute(
            text(
                "SELECT settings->>'plan' AS plan "
                "FROM nexus_auth.nexus_auth_tenants WHERE id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar_one_or_none()
    return row or DEFAULT_PLAN


async def set_tenant_plan(db: AsyncSession, tenant_id: uuid.UUID, plan: str) -> None:
    if plan not in PLAN_LIMITS:
        raise ValueError(f"unknown plan: {plan!r} (expected one of {sorted(PLAN_LIMITS)})")
    await db.execute(
        text(
            "UPDATE nexus_auth.nexus_auth_tenants "
            "SET settings = jsonb_set(COALESCE(settings::jsonb, '{}'::jsonb), '{plan}', :plan_val)::json "
            "WHERE id = :tid"
        ),
        {"plan_val": f'"{plan}"', "tid": tenant_id},
    )


# ---------------------------------------------------------------------------
# Reserve / refund / usage
# ---------------------------------------------------------------------------
async def reserve_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> None:
    """Atomically reserve one AI request for (user, tenant, week).

    Raises QuotaExceededError when the weekly allowance is exhausted —
    callers must NOT invoke the LLM in that case.
    """
    now = now or _now_hkt()
    pk = weekly_period_key(now)
    plan = await get_tenant_plan(db, tenant_id)
    limit = plan_limit(plan)

    # 1) Ensure a row exists for this period (sync limit — plan change applies
    # immediately; row limit is display-only, enforcement uses :limit below)
    await db.execute(
        text(
            f"INSERT INTO {QUOTA_TABLE} "
            "(user_id, tenant_id, period_key, requests_used, requests_limit) "
            "VALUES (:uid, :tid, :pk, 0, :limit) "
            "ON CONFLICT (user_id, tenant_id, period_key) "
            "DO UPDATE SET requests_limit = :limit"
        ),
        {"uid": user_id, "tid": tenant_id, "pk": pk, "limit": limit},
    )
    # 2) Atomic conditional increment — limit comes from the CURRENT plan
    # (not the stored row value) so an admin plan change is immediate.
    # 0 rows = allowance exhausted.
    row = (
        await db.execute(
            text(
                f"UPDATE {QUOTA_TABLE} "
                "SET requests_used = requests_used + 1 "
                "WHERE user_id = :uid AND tenant_id = :tid AND period_key = :pk "
                "AND (:limit < 0 OR requests_used < :limit) "
                "RETURNING requests_used"
            ),
            {"uid": user_id, "tid": tenant_id, "pk": pk, "limit": limit},
        )
    ).scalar_one_or_none()
    if row is None:
        used = await _current_used(db, tenant_id, user_id, pk)
        raise QuotaExceededError(used=used, limit=limit, reset_on=reset_at(now))


async def refund_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> None:
    """Give back one reserved request after a failed LLM call."""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        await db.execute(
            text("SELECT set_config('app.user_id', :u, true)"),
            {"u": str(user_id)},
        )
    except Exception:
        pass  # RLS GUC best-effort（同 enforce_weekly_quota）
    pk = weekly_period_key(now or _now_hkt())
    await db.execute(
        text(
            f"UPDATE {QUOTA_TABLE} "
            "SET requests_used = GREATEST(requests_used - 1, 0) "
            "WHERE user_id = :uid AND tenant_id = :tid AND period_key = :pk"
        ),
        {"uid": user_id, "tid": tenant_id, "pk": pk},
    )


async def current_usage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read usage for the current week: {used, limit, period_key, plan, reset_on}."""
    now = now or _now_hkt()
    pk = weekly_period_key(now)
    plan = await get_tenant_plan(db, tenant_id)
    limit = plan_limit(plan)
    row = (
        await db.execute(
            text(
                f"SELECT requests_used FROM {QUOTA_TABLE} "
                "WHERE user_id = :uid AND tenant_id = :tid AND period_key = :pk"
            ),
            {"uid": user_id, "tid": tenant_id, "pk": pk},
        )
    ).scalar_one_or_none()
    used = int(row) if row is not None else 0
    return {
        "used": used,
        "limit": limit,
        "period_key": pk,
        "plan": plan,
        "reset_on": reset_at(now).isoformat(),
    }


async def enforce_weekly_quota(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Reserve one weekly AI request for this user.

    Returns ``None`` when the reservation succeeded (caller may invoke the
    LLM).  Returns a user-facing block dict when the weekly allowance is
    exhausted — caller must NOT call the LLM (SPEC Q8B: message + upgrade CTA).
    """
    # ── RLS fix: GUC 係 transaction-scoped — SSE generator / background 段執行時
    # 之前 handler transaction 已 commit → GUC reset → ai_usage_quotas（FORCE RLS）
    # INSERT 會 InsufficientPrivilege。自己 set（只影響當前 transaction）。
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        await db.execute(
            text("SELECT set_config('app.user_id', :u, true)"),
            {"u": str(user_id)},
        )
    except Exception:
        pass  # set_config best-effort — 冇 RLS 嘅環境照行
    try:
        await reserve_request(db, tenant_id, user_id, now=now)
        return None
    except QuotaExceededError as e:
        # SPEC notifications-revamp T2: quota 用晒 → 系統通知（group_key 每日一寫）
        try:
            from app.services.notification_writer import notify_event
            await notify_event(
                db, tenant_id, user_id,
                source_module="system",
                title="本週 AI 用量已用完",
                body=f"已用 {e.used}/{e.limit}，{e.reset_on} 重置。升級 Pro 可享無限用量（即將推出）",
                group_key=f"quota_exhausted:{e.reset_on}",
                priority="HIGH",
            )
        except Exception:
            pass
        return {
            "error": "weekly_quota_exceeded",
            "message": (
                f"本週 AI 用量已用完（{e.used}/{e.limit}），{e.reset_on} 重置。"
                "升級 Pro 可享無限用量（即將推出）"
            ),
            "reset_on": str(e.reset_on),
            "used": e.used,
            "limit": e.limit,
        }


async def _current_used(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, pk: str
) -> int:
    row = (
        await db.execute(
            text(
                f"SELECT requests_used FROM {QUOTA_TABLE} "
                "WHERE user_id = :uid AND tenant_id = :tid AND period_key = :pk"
            ),
            {"uid": user_id, "tid": tenant_id, "pk": pk},
        )
    ).scalar_one_or_none()
    return int(row) if row is not None else 0

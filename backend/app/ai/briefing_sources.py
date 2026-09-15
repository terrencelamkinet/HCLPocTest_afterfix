"""AI Secretary briefing module data sources.

Each enabled module maps to one async function here. Functions receive
the AI session context + DB session and return serializable dicts ready
for the briefing response. RLS (app.tenant_id GUC set by
get_tenant_session) enforces per-tenant isolation at the DB layer.

Convention: return [] / {} on any failure — a module data source must
never crash the whole briefing.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.session.context import AISessionContext
from app.ai.tool_registry import _row_to_dict
from app.models.crm import Company, Project, Touchpoint
from app.models.crm_module_b import Deal, Quote

_UTC = timezone.utc
HKT = timezone(timedelta(hours=8))


def _now_hkt() -> datetime:
    return datetime.now(HKT)


# ── v2 T2.1: Item P 級規則計（SPEC §Solution — 唔靠 LLM 判斷）──
def _parse_due(value: Any) -> datetime | None:
    """Parse due date (date/datetime/str) → HKT-aware datetime at 00:00."""
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, date):
            dt = datetime(value.year, value.month, value.day)
        else:
            s = str(value)[:10]
            dt = datetime.strptime(s, "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HKT)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        return None


def compute_p_level(entity_type: str, due: Any, today: datetime | None = None) -> str:
    """Item-level P by rule — task / project / invoice.

    SPEC 2026-09-04（v2 §Solution）：
      task:    overdue > 7日 → P0；overdue ≤7 或 今日到期 → P1；有 deadline → P2；冇日期 → P3
      project: overdue > 90日 → P3；overdue ≤90 → P2；今日/聽日 deadline → P1
      invoice: 到期 ≤3日 → P0；其餘有到期 → P1；冇日期 → P3
    """
    today_dt = (today or _now_hkt()).replace(hour=0, minute=0, second=0, microsecond=0)
    d = _parse_due(due)
    if d is None:
        return "P3"
    overdue = (today_dt - d).days  # >0 = 已逾期
    if entity_type == "task":
        if overdue > 7:
            return "P0"
        if overdue >= 0:  # 逾期 0-7 或今日到期
            return "P1"
        return "P2"  # 未來 deadline
    if entity_type == "project":
        if overdue > 90:
            return "P3"
        if overdue >= 0:
            return "P2"
        if overdue >= -1:  # 聽日 deadline
            return "P1"
        return "P2"
    # invoice / quote / expense — 到期前 3 日升 P0
    if entity_type == "invoice":
        if overdue >= 0:  # 已到期
            return "P0"
        if overdue >= -3:  # 3 日內到期
            return "P0"
        return "P1"
    return "P2"


def _liturgical_season(now: datetime) -> dict[str, str]:
    """簡單教會年曆計算：復活節（Gregorian computus）+ 節期判斷。

    返回 {"season": "聖靈降臨期" 等, "day": "第90日" 等}
    """
    y = now.year
    # 復活節（Anonymous Gregorian algorithm）
    a, b, c = y % 19, y // 100, y % 100
    d = (19 * a + b - b // 4 - (b - (b + 8) // 25 + 1) // 3 + 15) % 30
    e = (2 * (b % 4) + 2 * (c // 4) - d - (c % 4) + 32) % 7
    month = (d + e - 7 * ((a + 11 * d + 22 * e) // 451) + 114) // 31
    day = ((d + e - 7 * ((a + 11 * d + 22 * e) // 451) + 114) % 31) + 1
    easter = datetime(y, month, day, tzinfo=HKT)
    date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def days_since(ref: datetime) -> int:
        return (date - ref.replace(tzinfo=HKT)).days

    seasons = [
        (easter - timedelta(days=46), "大齋期", 40),          # Ash Wed
        (easter - timedelta(days=7), "聖週", 7),              # Palm Sunday
        (easter, "復活節期", 50),
        (easter + timedelta(days=50), "聖靈降臨期", 9999),    # Pentecost
    ]
    # Advent（將臨期）— 聖誕前第4個星期日開始
    christmas = datetime(y, 12, 25, tzinfo=HKT)
    advent = christmas - timedelta(days=christmas.weekday() + 21)  # 4th Sunday before
    if date >= advent:
        seasons.append((advent, "將臨期", 24))
    elif date < datetime(y, 1, 6, tzinfo=HKT):  # 1月6日前仍屬聖誕節期
        seasons.append((datetime(y, 12, 25, tzinfo=HKT), "聖誕節期", 12))

    best = ("常年期", "第1日")
    for start, name, length in seasons:
        if date >= start:
            d = days_since(start) + 1
            if name == "聖靈降臨期":
                best = ("聖靈降臨期", f"第{d}日")
            elif name in ("復活節期", "大齋期", "將臨期"):
                best = (name, f"第{d}日")
            else:
                best = (name, f"第{d}日")
    return {"season": best[0], "day": best[1]}


def _hkt_iso(dt: Any) -> str:
    """Serialize a datetime as HKT wall-clock ISO ('YYYY-MM-DDTHH:MM:SS')."""
    if dt.tzinfo:
        dt = dt.astimezone(HKT)
    else:
        dt = dt.replace(tzinfo=HKT)
    return dt.isoformat()


async def project_status(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Active projects (not done/cancelled), nearest deadline first.

    Deep options:
      - ownership: 'mine' (project_manager_id == user) / 'all'
      - count: '3' | '5' | '8' | '10' (limit)
    """
    opts = options or {}
    ownership = opts.get("ownership", "mine")
    limit = int(opts.get("count", 8) or 8)

    q = (
        select(Project, Company.name)
        .join(Company, Company.id == Project.company_id, isouter=True)
        .where(
            Project.tenant_id == ctx.tenant_id,
            Project.status.notin_(["done", "cancelled", "archived"]),
        )
        .order_by(Project.deadline.asc().nulls_last())
        .limit(limit)
    )
    if ownership == "mine":
        q = q.where(Project.project_manager_id == ctx.user_id)
    rows = (await db.execute(q)).all()

    items = []
    for r, company_name in rows:
        d = _row_to_dict(r)
        d["company_name"] = company_name
        d["p_level"] = compute_p_level("project", d.get("deadline"))
        items.append(d)
    return items


async def stale_deals(ctx: AISessionContext, db: AsyncSession, days: int = 14, options: dict | None = None) -> list[dict[str, Any]]:
    """Open deals with no activity for `days` — stalled opportunities.

    Deep options:
      - days: '7' | '14' | '30' (staleness cutoff; overrides positional days)
      - sort: 'amount' | 'staleness' (updated_at asc)
    """
    opts = options or {}
    days = int(opts.get("days", days) or days)
    sort = opts.get("sort", "staleness")
    cutoff = datetime.now(_UTC) - timedelta(days=days)
    order_col = Deal.amount.desc().nulls_last() if sort == "amount" else Deal.updated_at.asc()
    rows = (
        await db.execute(
            select(Deal, Company.name)
            .join(Company, Company.id == Deal.company_id, isouter=True)
            .where(
                Deal.tenant_id == ctx.tenant_id,
                Deal.status == "open",
                Deal.updated_at < cutoff,
            )
            .order_by(order_col)
            .limit(8)
        )
    ).all()

    items = []
    for r, company_name in rows:
        d = _row_to_dict(r)
        d["company_name"] = company_name
        items.append(d)
    return items


async def quote_tracking(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Pending quotes (sent / draft), expiring soonest first.

    Deep options:
      - statuses: subset of ['draft','sent','expiring'] or 'all'
      - sort: 'valid_until' | 'amount'
    """
    opts = options or {}
    statuses = opts.get("statuses")
    if statuses in (None, "all", ["all"]):
        statuses = ["draft", "sent", "expiring"]
    sort = opts.get("sort", "valid_until")
    order_col = Quote.total.desc().nulls_last() if sort == "amount" else Quote.valid_until.asc().nulls_last()
    rows = (
        await db.execute(
            select(Quote, Deal.name)
            .join(Deal, Deal.id == Quote.deal_id, isouter=True)
            .where(
                Quote.tenant_id == ctx.tenant_id,
                Quote.status.in_(statuses),
            )
            .order_by(order_col)
            .limit(8)
        )
    ).all()

    items = []
    for r, deal_name in rows:
        d = _row_to_dict(r)
        d["deal_name"] = deal_name
        items.append(d)
    return items


async def overdue_followup(ctx: AISessionContext, db: AsyncSession, days: int = 7, options: dict | None = None) -> list[dict[str, Any]]:
    """Contacts with no touchpoint in the last `days` — follow-up due.

    Deep options:
      - days: '3' | '7' | '14' (inactivity cutoff)
      - contact_type: 'all' | 'vip' | 'lead' (contact status filter)
    """
    opts = options or {}
    days = int(opts.get("days", days) or days)
    contact_type = opts.get("contact_type", "all")
    cutoff = datetime.now(_UTC) - timedelta(days=days)
    rows = (
        await db.execute(
            select(Touchpoint)
            .where(
                Touchpoint.tenant_id == ctx.tenant_id,
                Touchpoint.date >= cutoff,
            )
            .order_by(Touchpoint.date.desc())
            .limit(200)
        )
    ).scalars().all()

    # contacts who HAVE had activity — invert to find who's been quiet
    active_contact_ids = {str(t.contact_id) for t in rows if t.contact_id is not None}
    from app.models.crm import Contact

    contacts = (
        await db.execute(
            select(Contact, Company.name)
            .join(Company, Company.id == Contact.company_id, isouter=True)
            .where(
                Contact.tenant_id == ctx.tenant_id,
                Contact.status.notin_(["churned", "other"]),
                *(
                    [Contact.status == "lead"]
                    if contact_type == "lead"
                    else [Contact.status.in_(["customer", "active", "vip"])]
                    if contact_type == "vip"
                    else []
                ),
            )
            .order_by(Contact.updated_at.asc())
            .limit(50)
        )
    ).all()

    items = []
    for c, company_name in contacts:
        if str(c.id) in active_contact_ids:
            continue
        d = _row_to_dict(c)
        d["company_name"] = company_name
        items.append(d)
        if len(items) >= 8:
            break
    return items


async def birthday_reminders(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Contacts with a birthday in the current HKT month (custom field `birthday_month`, 1-12).

    Deep options:
      - range: 'today' | 'week' | 'month' (default month — backward compatible)
      - type: 'all' | 'customer' | 'colleague' (contact status / category filter)
    """
    from zoneinfo import ZoneInfo
    from app.models.crm import Contact

    opts = options or {}
    range_sel = opts.get("range", "month")
    ctype = opts.get("type", "all")
    hkt_now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    month = hkt_now.month
    day = hkt_now.day

    type_filters = []
    if ctype == "customer":
        type_filters.append(Contact.status.notin_(["lead", "other"]))
    elif ctype == "colleague":
        type_filters.append(Contact.status.in_(["lead", "other"]))  # 非客戶當同事（寬鬆）

    # range 過濾：month 一定有；today 需要 birthday_day custom field
    # （week 暫用 month 行為 — birthday_day 未有正規化 data）
    range_filter = Contact.custom_fields.op("->>")("birthday_month") == str(month)
    if range_sel == "today":
        range_filter = Contact.custom_fields.op("->>")("birthday_day") == str(day)

    rows = (
        await db.execute(
            select(Contact, Company.name)
            .join(Company, Company.id == Contact.company_id, isouter=True)
            .where(
                Contact.tenant_id == ctx.tenant_id,
                Contact.status.notin_(["churned", "other"]) if ctype != "colleague" else Contact.tenant_id == ctx.tenant_id,
                range_filter,
                *type_filters,
            )
            .order_by(Contact.updated_at.desc())
            .limit(20)
        )
    ).all()

    items = []
    for c, company_name in rows:
        d = _row_to_dict(c)
        d["company_name"] = company_name
        d["birthday_month"] = month
        items.append(d)
    return items


async def hot_leads(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """High-intent deals: open deals with probability >= threshold, biggest first.

    Deep options:
      - threshold: '50' | '70' | '90' (probability %)
      - sort: 'amount' | 'probability' | 'updated' (updated_at desc)
    """
    opts = options or {}
    threshold = int(opts.get("threshold", 70) or 70)
    sort = opts.get("sort", "amount")
    order_map = {
        "amount": (Deal.amount.desc().nulls_last(),),
        "probability": (Deal.probability.desc(), Deal.amount.desc().nulls_last()),
        "updated": (Deal.updated_at.desc(),),
    }
    order_cols = order_map.get(sort, order_map["amount"])
    rows = (
        await db.execute(
            select(Deal, Company.name)
            .join(Company, Company.id == Deal.company_id, isouter=True)
            .where(
                Deal.tenant_id == ctx.tenant_id,
                Deal.status == "open",
                Deal.probability >= threshold,
            )
            .order_by(*order_cols)
            .limit(8)
        )
    ).all()

    items = []
    for r, company_name in rows:
        d = _row_to_dict(r)
        d["company_name"] = company_name
        items.append(d)
    return items


async def sales_kpi(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Sales target progress: won deals value vs the user's current-period target.

    Deep options:
      - period: 'week' | 'month' | 'quarter' — 用嚟兜底揀 target
        （user_targets 本身有 period_start/end；冇 target 時唔會 fake data）
    """
    opts = options or {}
    period = opts.get("period", "month")
    from app.models.crm_module_c import UserTarget

    # user_targets.period_start/end are offset-naive TIMESTAMP (HKT wall-clock)
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Hong_Kong")).replace(tzinfo=None)
    rows = (
        await db.execute(
            select(UserTarget)
            .where(
                UserTarget.tenant_id == ctx.tenant_id,
                UserTarget.user_id == ctx.user_id,
                UserTarget.period_start <= now,
                UserTarget.period_end >= now,
            )
            .order_by(UserTarget.period_end.desc())
            .limit(3)
        )
    ).scalars().all()

    items = []
    for t in rows:
        d = _row_to_dict(t)
        # actual: sum of won deals in the period
        won = await db.execute(
            select(func.coalesce(func.sum(Deal.amount), 0))
            .where(
                Deal.tenant_id == ctx.tenant_id,
                Deal.status == "won",
                Deal.won_at >= t.period_start,
                Deal.won_at <= t.period_end,
            )
        )
        d["won_amount"] = float(won.scalar() or 0)
        tv = float(t.target_value or 0)
        d["progress_pct"] = round(d["won_amount"] / tv * 100, 1) if tv else 0
        items.append(d)
    return items


async def team_updates(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Recent task activity from the user's teams.

    Deep options:
      - scope: 'my_teams' | 'all_company'（all_company 唔限 team — 全 tenant 開放 tasks）
      - task_status: 'in_progress' | 'pending' | 'all'
    """
    opts = options or {}
    scope = opts.get("scope", "my_teams")
    task_status = opts.get("task_status", "all")
    from app.models.crm import Task
    from app.models.crm_module_c import Team, TeamMember

    # teams the current user belongs to
    if scope == "all_company":
        # TeamMember 冇 tenant_id — join teams 攞全 tenant 成員
        team_ids: list = []
        member_ids = (
            await db.execute(
                select(TeamMember.user_id)
                .join(Team, Team.id == TeamMember.team_id)
                .where(Team.tenant_id == ctx.tenant_id)
            )
        ).scalars().all()
        teams: dict = {}
    else:
        team_rows = (
            await db.execute(
                select(TeamMember.team_id)
                .where(TeamMember.user_id == ctx.user_id)
                .limit(10)
            )
        ).scalars().all()
        if not team_rows:
            return []
        team_ids = list(team_rows)
        teams = {
            t.id: t.name
            for t in (
                await db.execute(select(Team).where(Team.id.in_(team_ids)))
            ).scalars().all()
        }
        # members of those teams
        member_ids = (
            await db.execute(
                select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))
            )
        ).scalars().all()

    status_filter = ["pending", "in_progress"]
    if task_status == "pending":
        status_filter = ["pending"]
    elif task_status == "in_progress":
        status_filter = ["in_progress"]

    # recent open tasks assigned to any team member
    rows = (
        await db.execute(
            select(Task)
            .where(
                Task.tenant_id == ctx.tenant_id,
                Task.assignee_id.in_(member_ids),
                Task.status.in_(status_filter),
            )
            .order_by(Task.updated_at.desc())
            .limit(10)
        )
    ).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["team_names"] = list(teams.values())
        items.append(d)
    return items


async def invoice_reminders(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Outstanding quotations (DRAFT/PENDING) — invoice module proxy.

    Deep options:
      - statuses: subset of ['pending','sent','overdue'] or 'all'
    """
    from app.models.crm_module_c import Quotation

    opts = options or {}
    statuses = opts.get("statuses")
    if statuses in (None, "all", ["all"]):
        statuses = ["DRAFT", "PENDING", "SENT"]
    else:
        mapping = {"pending": "PENDING", "sent": "SENT", "overdue": "DRAFT"}
        statuses = [mapping.get(s, s.upper()) for s in statuses]

    rows = (
        await db.execute(
            select(Quotation)
            .where(
                Quotation.tenant_id == ctx.tenant_id,
                Quotation.status.in_(statuses),
            )
            .order_by(Quotation.valid_until.asc().nulls_last())
            .limit(8)
        )
    ).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        items.append(d)
    return items


# ═══════════════════════════════════════════════════════════════
# Batch B/C — external API + new-table sources (2026-08-01)
# ═══════════════════════════════════════════════════════════════
import asyncio
from defusedxml import ElementTree as ET  # 2026-09-15 SAST：defusedxml 擋 XXE / billion laughs（原本 raw xml.etree）

import httpx

_HTTP_TIMEOUT = httpx.Timeout(8.0)
_USER_AGENT = "Mozilla/5.0 (compatible; NexusCRM/1.0)"


async def weather(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Current HK weather from HKO Open Data (rhrread).

    Deep options:
      - region: ['hk_island'|'kowloon'|'nt_east'|'nt_west'|'all_hk'] —
        HKO rhrread 係全港 station 數據；region 用嚟揀最近 station（有 station 就先篩）
      - unit: 'celsius' | 'fahrenheit'（溫度轉換）
    """
    opts = options or {}
    unit = opts.get("unit", "celsius")
    regions = opts.get("region") or ["all_hk"]
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            r = await client.get(
                "https://data.weather.gov.hk/weatherAPI/opendata/weather.php",
                params={"dataType": "rhrread", "lang": "en"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    try:
        icon_raw = data.get("icon") or [0]
        icon = icon_raw[0] if isinstance(icon_raw, list) else icon_raw
        temp = data.get("temperature", {}).get("data", [{}])[0]
        humidity = data.get("humidity", {}).get("data", [{}])[0]
        temp_value = temp.get("value")
        if unit == "fahrenheit" and temp_value is not None:
            temp_value = round(float(temp_value) * 9 / 5 + 32, 1)
        items.append({
            "place": temp.get("place", "Hong Kong"),
            "temperature": temp_value,
            "unit": unit,
            "humidity": humidity.get("value"),
            "icon": icon,
            "updated_at": data.get("updateTime", ""),
        })
        # rainfall at HKO main station
        for s in data.get("rainfall", {}).get("data", []):
            if s.get("main") == "TRUE":
                items[0]["rainfall_mm"] = s.get("max")
                break
    except Exception:
        return []
    return items


async def unread_messages(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Unread inbox messages from connected mail providers (Gmail/Outlook).
    Returns [] when no mail integration is connected — graceful no-op.

    Deep options:
      - sources: ['gmail'|'outlook_mail'] subset or 'all'
      - count: '3' | '5' | '8'（每 provider 上限）
    """
    opts = options or {}
    sources = opts.get("sources")
    if sources in (None, "all", ["all"]):
        sources = ["gmail", "outlook_mail"]
    count = int(opts.get("count", 8) or 8)
    from app.models.integration import Integration

    rows = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.user_id == ctx.user_id,
                Integration.status == "active",
                Integration.provider.in_(sources),
            )
        )
    ).scalars().all()

    items: list[dict[str, Any]] = []
    for integ in rows:
        cfg = integ.config or {}
        token = cfg.get("access_token")
        if not token:
            continue
        try:
            if integ.provider == "gmail":
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    r = await client.get(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                        params={"q": "is:unread", "maxResults": count},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if r.status_code != 200:
                        continue
                    msg_list = r.json().get("messages", [])
                    for m in msg_list[:count]:
                        md = await client.get(
                            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                            params={"format": "metadata", "metadataHeaders": "From,Subject"},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if md.status_code != 200:
                            continue
                        payload = md.json().get("payload", {})
                        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                        items.append({
                            "provider": "gmail",
                            "id": m["id"],
                            "from": headers.get("from", ""),
                            "subject": headers.get("subject", ""),
                            "snippet": md.json().get("snippet", ""),
                        })
        except Exception:
            continue
    return items


async def calendar_conflicts(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Overlapping calendar events — schedule clash detection.

    Deep options:
      - range: 'today' | 'today_tomorrow'（檢測範圍）
    """
    from zoneinfo import ZoneInfo
    from app.models.crm import ProjectCalendarEvent

    opts = options or {}
    range_sel = opts.get("range", "today")

    hkt = ZoneInfo("Asia/Hong_Kong")
    day_start = datetime.now(hkt).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=2 if range_sel == "today_tomorrow" else 1)

    rows = (
        await db.execute(
            select(ProjectCalendarEvent)
            .where(
                ProjectCalendarEvent.tenant_id == ctx.tenant_id,
                ProjectCalendarEvent.start >= day_start,
                ProjectCalendarEvent.start < day_end,
                ProjectCalendarEvent.is_all_day.is_(False),
                # per-user isolation — own + shared events only
                (ProjectCalendarEvent.owner_user_id == ctx.user_id)
                | (ProjectCalendarEvent.owner_user_id.is_(None)),
            )
            .order_by(ProjectCalendarEvent.start.asc())
        )
    ).scalars().all()

    # T1.2: 已取消 event（sync prefix「Canceled: 」）唔參與衝突偵測 — 9/3
    # 實證：Canceled HPE Dinner 同正常版被當衝突報出「與已取消同名」
    rows = [r for r in rows if not str(r.title or "").startswith("Canceled: ")]

    # Cross-source duplicates（同一 event 被 Outlook + Google 各自 mirror —
    # title + start + end 完全一樣）唔可以當衝突：先按 (title, start, end) 去重
    seen_keys: set[tuple[str, str, str]] = set()
    deduped: list = []
    for row in rows:
        key = (
            str(row.title or ""),
            row.start.isoformat() if row.start is not None else "",
            row.end.isoformat() if row.end is not None else "",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)
    rows = deduped

    conflicts: list[dict[str, Any]] = []
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        a_end = a.end if a.end else a.start
        if b.start < a_end:
            conflicts.append({
                "event_a": a.title,
                "event_b": b.title,
                "overlap_start": _hkt_iso(b.start),
                "event_a_end": _hkt_iso(a_end),
            })
    return conflicts


async def news_industry(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Latest HK + business/industry headlines from public RSS feeds.

    Deep options:
      - topics: subset of ['tech','finance','logistics','retail'] or 'all'
        （keyword 篩選 title；'all' = 唔篩）
      - lang: 'zh' | 'en' | 'both'（zh = Yahoo HK + SCMP，en = BBC，both = 全部）
    """
    opts = options or {}
    topics = opts.get("topics")
    if topics in (None, "all", ["all"]):
        topics = []
    lang = opts.get("lang", "both")
    # feed → (source label, category hint) — 用戶 2026-09-01 要求新聞有分類 +
    # 來源標記（格式參考晨早新聞 Digest：🏙 香港要聞 / 💼 科技/商業 / 🌍 國際）
    feeds: list[tuple[str, str, str]] = []
    if lang in ("zh", "both"):
        feeds.append(("https://hk.news.yahoo.com/rss/", "Yahoo", "hk"))
        feeds.append(("https://hk.news.yahoo.com/rss/world", "Yahoo", "world"))
        feeds.append(("https://hk.news.yahoo.com/rss/business", "Yahoo財經", "biz"))
        feeds.append(("https://www.scmp.com/rss/91/feed", "SCMP", "biz"))
    if lang in ("en", "both"):
        feeds.append(("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC", "biz"))
        feeds.append(("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC", "world"))

    # topic keyword map（英文 + 中文 keyword 兜底）
    TOPIC_KEYWORDS = {
        "tech": ["tech", "ai", "software", "cloud", "digital", "科技", "人工智能", "軟件"],
        "finance": ["bank", "financ", "invest", "market", "stock", "金融", "銀行", "投資", "市場"],
        "logistics": ["shipping", "logistic", "supply", "cargo", "港口", "物流", "供應鏈", "貨運"],
        "retail": ["retail", "consumer", "shop", "e-commerce", "零售", "消費", "電商"],
    }
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    PER_FEED_MAX = 5  # 每 feed 最多 5 條 — 確保 world/business feed 都有 quota
    TOTAL_MAX = 15
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}, follow_redirects=True) as client:
            for url, source, hint in feeds:
                feed_count = 0
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    root = ET.fromstring(r.text)
                    for item in root.iter("item"):
                        if feed_count >= PER_FEED_MAX:
                            break
                        title = item.findtext("title") or ""
                        if topics:
                            tl = title.lower()
                            if not any(
                                kw.lower() in tl
                                for t in topics
                                for kw in TOPIC_KEYWORDS.get(t, [t])
                            ):
                                continue
                        tkey = title.strip().lower()
                        if tkey in seen_titles:
                            continue
                        seen_titles.add(tkey)
                        link = item.findtext("link") or ""
                        pub = item.findtext("pubDate") or ""
                        items.append({
                            "feed": url.split("/")[2],
                            "source": source,
                            "category_hint": hint,
                            "title": title.strip(),
                            "link": link.strip(),
                            "published": pub.strip(),
                        })
                        feed_count += 1
                        if len(items) >= TOTAL_MAX:
                            break
                except Exception:
                    continue
                if len(items) >= TOTAL_MAX:
                    break
    except Exception:
        return []
    return items


def _simplify_traffic(text: str, is_en: bool) -> str:
    """壓縮交通消息成「地點：事件」重點格式；無法分析時 fallback 用原文。"""
    t = (text or "").strip()
    if not t:
        return t
    if is_en:
        # e.g. "Due to a traffic accident, some lanes at the junction of Canton
        #       Road and Austin Road are now closed."
        m = re.match(
            r"(?:due to|owing to|because of)\s+(.+?)[,;]\s*(.+?)\s+(?:are|is|have been|has been)\s+(.+?)[.]?$",
            t,
            re.IGNORECASE,
        )
        if m:
            event = m.group(1).strip()
            loc = m.group(2).strip()
            cons = m.group(3).strip()
            mm = re.search(r"\b(?:at|on|near|along)\s+(.+)$", loc, re.IGNORECASE)
            if mm:
                loc = mm.group(1).strip()
            action = ""
            for kw in ("reopened", "resumed", "cleared", "closed", "blocked", "suspended", "flooded"):
                if kw in cons.lower():
                    action = f", {kw}"
                    break
            return f"{loc}: {event}{action}"
        return t

    # zh-HK / zh-TW：因/由於/因為 <事件>，<地點> 的 <結果>
    m = re.match(r"(?:因|由於|因為)(.+?)[，,]\s*([^，。]+?)(?:的|嘅)(.+?)[。]?$", t)
    if m:
        event = m.group(1).strip()
        loc = m.group(2).strip()
        result = m.group(3).strip()
        action = ""
        for kw in ("封閉", "封路", "受阻", "暫停", "改道", "擠塞", "關閉", "封鎖"):
            if kw in result:
                action = kw
                break
        if not action:
            for kw in ("重開", "恢復", "解封"):
                if kw in result:
                    action = kw
                    break
        return f"{loc}：{event}{action}"
    # 「較早前因 <事件> 而 <動作> 的 <地點> 已重開」類
    m2 = re.match(r"較?早前?因(.+?)而(.+?)的(.+?)(?:已|經)?(重開|恢復|解封)[。]?$", t)
    if m2:
        return f"{m2.group(3).strip()}：{m2.group(1).strip()}{m2.group(4)}"
    return t


# MTR 線 code → 中文名（data.gov.hk MTR ETA API 用）
_MTR_LINES: dict[str, str] = {
    "AEL": "機場快線", "DRL": "迪士尼線", "EAL": "東鐵線", "ISL": "港島線",
    "KTL": "觀塘線", "SIL": "南港島線", "TCL": "東涌線", "TKL": "將軍澳線",
    "TWL": "荃灣線", "WRL": "屯馬線",
}

# MTR 站 code → 中文名（常用站 — ETA dest 顯示用）
_MTR_STATIONS: dict[str, str] = {
    # 觀塘線 KTL
    "KWT": "觀塘", "NOP": "牛頭角", "KOB": "九龍灣", "NTK": "牛頭角",
    "DIA": "鑽石山", "HOM": "何文田", "WHA": "黃埔", "TIK": "調景嶺",
    "LAT": "藍田", "YAT": "油塘", "CHH": "彩虹", "SKM": "石硤尾",
    "PRE": "樂富", "KOT": "九龍塘", "LOF": "旺角", "YMT": "油麻地",
    "MOK": "旺角", "JOR": "佐敦", "TST": "尖沙咀", "ADM": "金鐘",
    "SOH": "上環", "SHM": "深水埗", "CKW": "長沙灣", "LCK": "荔枝角",
    "MEF": "美孚", "TSW": "荃灣", "TWH": "荃灣西",
    # 屯馬線 WRL
    "KSR": "錦上路", "TUM": "屯門", "SIH": "兆康", "TIS": "天水圍",
    "YUL": "元朗", "LKS": "朗屏", "TUN": "屯門", "TAP": "大埔墟",
    "UNI": "大學", "SHT": "沙田", "CIF": "城門河", "FOT": "火炭",
    "MOS": "馬鞍山", "HIK": "恆安", "SHW": "沙田圍", "STW": "沙田",
    "KAT": "啟德", "TKW": "土瓜灣", "SOH": "宋皇臺", "HOM": "何文田",
    "KOB": "九龍灣", "TIK": "調景嶺", "NAC": "南昌", "EXC": "會展",
    "TIH": "尖東", "KOT": "九龍塘",
    # 荃灣線 TWL
    "TST": "尖沙咀", "ADM": "金鐘", "CEN": "中環", "KOW": "九龍",
    "LKF": "荔枝角", "LCK": "荔枝角", "MEF": "美孚", "TSW": "荃灣",
    # 東鐵線 EAL
    "ADM": "金鐘", "EXC": "會展", "MKK": "旺角東", "KOT": "九龍塘",
    "TAI": "大圍", "SHT": "沙田", "UNI": "大學", "TAP": "大埔墟",
    "FAN": "粉嶺", "SHS": "上水", "LOW": "羅湖", "LMC": "落馬洲",
    # 港島線 ISL
    "KET": "堅尼地城", "HKU": "香港大學", "SYP": "西營盤", "SHW": "上環",
    "CEN": "中環", "ADM": "金鐘", "WAC": "灣仔", "CAB": "銅鑼灣",
    "TIH": "天后", "FOH": "炮台山", "NQU": "北角", "QUB": "鰂魚涌",
    "TAK": "太古", "SWH": "西灣河", "SKW": "筲箕灣", "HFC": "杏花邨",
    "CHW": "柴灣",
}


# ── 全球 geocoding（Photon/OSM — 同 geo router 一致，免費唔使 key）──
_PHOTON_HEADERS = {"User-Agent": "NexusCRM/1.0 (contact: terrence@kinetix.com.hk)"}
_OSRM_API = "https://router.project-osrm.org/route/v1/driving"


async def _geocode_place(query: str) -> dict[str, Any] | None:
    """Geocode 一個地址 → {label, lat, lng, city, country}（全球）。失敗 → None。"""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=_PHOTON_HEADERS) as client:
            r = await client.get(
                "https://photon.komoot.io/api/",
                params={"q": query, "limit": 1},
            )
            if r.status_code != 200:
                return None
            feats = (r.json().get("features") or [])
            if not feats:
                return None
            props = feats[0].get("properties") or {}
            geom = feats[0].get("geometry") or {}
            coords = geom.get("coordinates") or [0, 0]
            name = props.get("name") or ""
            street = props.get("street") or ""
            city = props.get("city") or props.get("district") or ""
            country = props.get("country") or ""
            parts = [x for x in (name or street, city, country) if x]
            return {
                "label": ", ".join(dict.fromkeys(parts)) or query,
                "lat": coords[1],
                "lng": coords[0],
                "city": city,
                "country": country,
            }
    except Exception:
        return None


async def _osrm_route(origin: dict, destination: dict) -> dict[str, Any] | None:
    """OSRM driving route（全球）→ {duration_min, distance_km}。失敗 → None。"""
    try:
        url = (
            f"{_OSRM_API}/{origin['lng']},{origin['lat']};"
            f"{destination['lng']},{destination['lat']}?overview=false"
        )
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _PHOTON_HEADERS["User-Agent"]}) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            routes = (r.json().get("routes") or [])
            if not routes:
                return None
            dur = routes[0].get("duration", 0)
            dist = routes[0].get("distance", 0)
            return {
                "duration_min": round(dur / 60),
                "distance_km": round(dist / 1000, 1),
            }
    except Exception:
        return None


def _is_hk(lat: float, lng: float) -> bool:
    """香港 bounding box 偵測（地區增強 gate — 全球用戶唔會見到 HK 數據）。"""
    return 22.0 <= lat <= 22.7 and 113.8 <= lng <= 114.6


async def traffic_commute(
    ctx: AISessionContext,
    db: AsyncSession,
    lang_pref: str = "zh-HK",
    options: dict | None = None,
) -> list[dict[str, Any]]:
    """Global commute route + region-specific live data (HK: MTR ETA + TD incidents).

    Core（全球適用）:
      - origin/destination 用 Photon geocode（OSM）→ OSRM driving route →
        預計車程時間 + 距離。全球任何城市都 work。
    HK 地區增強（bounding box 偵測，非 HK 用戶唔會見到）:
      - mode=public + mtr_line/station 設定 → MTR 實時 ETA（data.gov.hk）
      - TD special traffic news（keyword 過濾）

    Deep options:
      - origin: 起點地址（text，全球，address autocomplete）
      - destination: 目的地地址（text）
      - mode: 'driving' | 'public'
      - mtr_line / mtr_station: HK public mode 用嚟 fetch MTR ETA
    """
    opts = options or {}
    origin = (opts.get("origin") or "").strip()
    destination = (opts.get("destination") or "").strip()
    is_en = lang_pref.startswith("en")
    items: list[dict[str, Any]] = []

    # ── 1. 全球路線（geocode + OSRM driving route）──
    if origin and destination:
        o_geo = await _geocode_place(origin)
        d_geo = await _geocode_place(destination)
        if o_geo and d_geo:
            route = await _osrm_route(o_geo, d_geo)
            # v7.27: 來回 — 回程（destination → origin）都查埋，用戶
            # 2026-09-01：「交通應該可以做到來回」
            return_route = await _osrm_route(d_geo, o_geo) if route else None
            if route:
                o_label = o_geo["label"] if is_en else origin
                d_label = d_geo["label"] if is_en else destination
                hk_route = _is_hk(o_geo["lat"], o_geo["lng"]) and _is_hk(d_geo["lat"], d_geo["lng"])
                items.append({
                    "type": "commute_route",
                    "origin": o_label,
                    "destination": d_label,
                    "duration_min": route["duration_min"],
                    "distance_km": route["distance_km"],
                    "return_duration_min": return_route["duration_min"] if return_route else None,
                    "return_distance_km": return_route["distance_km"] if return_route else None,
                    "hk": hk_route,
                })

    # ── 2. HK 地區增強：MTR ETA（public mode + 有設定線/站）──
    mtr_line = (opts.get("mtr_line") or "").strip().upper()
    mtr_station = (opts.get("mtr_station") or "").strip().upper()
    mode = (opts.get("mode") or "public").strip().lower()
    # 全球 fallback：route 存在且非 HK → 唔出 MTR（用戶可能 set 咗舊 config）
    route_is_hk = any(i.get("type") == "commute_route" and i.get("hk") for i in items)
    route_exists = any(i.get("type") == "commute_route" for i in items)
    if mode == "public" and mtr_line and mtr_station and (not route_exists or route_is_hk):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
                r = await client.get(
                    "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php",
                    params={"line": mtr_line, "sta": mtr_station},
                )
                if r.status_code == 200:
                    body = r.json()
                    key = f"{mtr_line}-{mtr_station}"
                    data = body.get("data", {}).get(key, {})
                    line_zh = _MTR_LINES.get(mtr_line, mtr_line)
                    station_zh = _MTR_STATIONS.get(mtr_station, mtr_station)
                    mtr_entry: dict[str, Any] = {
                        "type": "mtr_eta",
                        "line": line_zh,
                        "station": station_zh,
                        "eta": [],
                    }
                    for direction in ("UP", "DOWN"):
                        trains = data.get(direction, [])[:3]
                        for tr in trains:
                            dest_code = tr.get("dest", "")
                            dest_zh = _MTR_STATIONS.get(dest_code, dest_code)
                            ttnt = tr.get("ttnt", "")
                            if str(ttnt).isdigit():
                                mtr_entry["eta"].append(
                                    f"{direction}往{dest_zh}：{ttnt}分鐘"
                                )
                    if mtr_entry["eta"]:
                        items.append(mtr_entry)
        except Exception:
            pass  # MTR ETA failure — 唔 crash

    # ── 3. HK 地區增強：TD traffic incidents（淨係 HK context 先出 — 全球用戶唔會見到）──
    # gate: 有 MTR ETA（即用戶 set 咗 HK 站）或者 route 係 HK 先出 TD 消息
    hk_context = any(i.get("type") == "mtr_eta" for i in items) or any(
        i.get("type") == "commute_route" and i.get("hk") for i in items
    )
    if not hk_context:
        return items
    keywords = [k for k in (origin, destination) if k]
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            r = await client.get("https://resource.data.one.gov.hk/td/en/specialtrafficnews.xml")
            if r.status_code != 200:
                return items
            root = ET.fromstring(r.text)
            for msg in root.iter("{http://data.one.gov.hk/td}message"):
                status = msg.findtext("{http://data.one.gov.hk/td}CurrentStatus") or ""
                if status not in ("1", "3"):  # 1 = active incident, 3 = special arrangement (2 = resolved)
                    continue
                if is_en:
                    raw = (
                        msg.findtext("{http://data.one.gov.hk/td}EngShort")
                        or msg.findtext("{http://data.one.gov.hk/td}EngText")
                        or ""
                    )
                else:
                    raw = (
                        msg.findtext("{http://data.one.gov.hk/td}ChinShort")
                        or msg.findtext("{http://data.one.gov.hk/td}ChinText")
                        or ""
                    )
                # origin/destination keyword 過濾 — 冇設定 keywords 就全部顯示
                if keywords:
                    haystack = raw
                    # 英文過濾時同時用中文原文 match（用户可能打中文地址）
                    if is_en:
                        haystack += " " + (msg.findtext("{http://data.one.gov.hk/td}ChinShort") or "")
                    if not any(k.lower() in haystack.lower() for k in keywords):
                        continue
                items.append({
                    "type": "traffic",
                    "text": _simplify_traffic(raw, is_en),
                })
    except Exception:
        return items
    return items[:8]


async def email_draft_review(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """AI-generated drafts awaiting user review.

    Deep options:
      - status: 'pending_review' | 'approved' | 'all'
    """
    opts = options or {}
    status = opts.get("status", "pending_review")
    statuses = ["pending_review"] if status == "pending_review" else (["approved"] if status == "approved" else None)
    from app.models.crm_module_c import AiDraft

    q = (
        select(AiDraft)
        .where(
            AiDraft.tenant_id == ctx.tenant_id,
            AiDraft.user_id == ctx.user_id,
        )
        .order_by(AiDraft.created_at.desc())
        .limit(8)
    )
    if statuses is not None:
        q = q.where(AiDraft.status.in_(statuses))
    rows = (await db.execute(q)).scalars().all()
    return [_row_to_dict(r) for r in rows]


async def customer_sentiment(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Recent customer-message sentiment summary (keyword-based, no LLM call).

    Deep options:
      - days: '7' | '14' | '30'（分析窗口）
      - show: 'all' | 'negative_only'（返全部計分定只負面樣本）
    """
    opts = options or {}
    days = int(opts.get("days", 30) or 30)
    show = opts.get("show", "all")
    from sqlalchemy import text as sa_text

    # ai_messages is partitioned; Message model may point at `messages` (legacy).
    # Query the partitioned parent directly with tenant isolation via ai_sessions.
    since = datetime.now(_UTC) - timedelta(days=days)
    try:
        rows = (
            await db.execute(
                sa_text(
                    """
                    SELECT m.content, m.created_at
                    FROM nexus_ai.ai_messages m
                    JOIN nexus_ai.ai_sessions s ON s.id = m.session_id
                    WHERE s.tenant_id = :tid
                      AND s.user_id = :uid
                      AND m.role = 'user'
                      AND m.created_at >= :since
                    ORDER BY m.created_at DESC
                    LIMIT 100
                    """
                ),
                {"tid": str(ctx.tenant_id), "uid": str(ctx.user_id), "since": since},
            )
        ).all()
    except Exception:
        return []

    pos_words = ["great", "excellent", "happy", "thanks", "thank", "good", "love", "perfect", "satisfied", "awesome"]
    neg_words = ["bad", "terrible", "unhappy", "angry", "frustrated", "delay", "slow", "broken", "issue", "complaint", "disappointed", "poor", "wrong", "fail", "error"]

    total = len(rows)
    pos = sum(1 for r in rows if any(w in (r[0] or "").lower() for w in pos_words))
    neg = sum(1 for r in rows if any(w in (r[0] or "").lower() for w in neg_words))
    if total == 0:
        return []

    samples = [
        {"content": r[0][:200], "created_at": r[1].isoformat() if r[1] else ""}
        for r in rows[:5]
        if show != "negative_only" or any(w in (r[0] or "").lower() for w in neg_words)
    ]
    return [{
        "total_messages": total,
        "positive": pos,
        "negative": neg,
        "neutral": total - pos - neg,
        "positive_pct": round(pos / total * 100, 1),
        "negative_pct": round(neg / total * 100, 1),
        "samples": samples[:5],
    }]


async def expense_reminders(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Pending expenses awaiting approval/reimbursement.

    Deep options:
      - status: 'pending' | 'approved' | 'all'
    """
    opts = options or {}
    status = opts.get("status", "pending")
    statuses = [status] if status != "all" else None
    from app.models.crm_module_c import Expense

    q = (
        select(Expense)
        .where(
            Expense.tenant_id == ctx.tenant_id,
            Expense.user_id == ctx.user_id,
        )
        .order_by(Expense.expense_date.asc().nulls_last(), Expense.created_at.desc())
        .limit(8)
    )
    if statuses is not None:
        q = q.where(Expense.status.in_(statuses))
    rows = (await db.execute(q)).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["amount"] = float(r.amount or 0)
        items.append(d)
    return items


async def personal_reminders(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """Upcoming personal reminders/memos not yet done.

    Deep options:
      - range: '1h' | 'today' | 'week'（remind_at 窗口）
    """
    opts = options or {}
    range_sel = opts.get("range", "1h")
    window_hours = {"1h": 1, "today": 24, "week": 168}.get(range_sel, 1)
    from app.models.crm_module_c import PersonalNote

    rows = (
        await db.execute(
            select(PersonalNote)
            .where(
                PersonalNote.tenant_id == ctx.tenant_id,
                PersonalNote.user_id == ctx.user_id,
                PersonalNote.done.is_(False),
                PersonalNote.remind_at >= datetime.now(_UTC) - timedelta(hours=window_hours),
            )
            .order_by(PersonalNote.remind_at.asc().nulls_last())
            .limit(8)
        )
    ).scalars().all()
    return [_row_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# Bible Reading — 讀經進度 module（2026-08-22 spec v2 — 真實章數 + 起點章節）
# ═══════════════════════════════════════════════════════════════

BIBLE_PLAN_TOTAL_DAYS = {
    "one_year": 365,
    "ninety_days": 90,
    "thirty_days_topical": 30,
    "chronological": 365,
    "custom_pace": None,
}

# 譯本 → 中文名（display 用）
BIBLE_TRANSLATION_LABELS = {
    "cuvmp": "和合本修訂版", "cuv": "和合本", "cnvs": "新譯本",
    "esv": "ESV", "niv": "NIV", "kjv": "KJV",
}

# 66 卷 canonical order + 真實章數（KJV/CUV/CUVMP 一致）
BIBLE_BOOKS = [
    ("創世記", 50), ("出埃及記", 40), ("利未記", 27), ("民數記", 36), ("申命記", 34),
    ("約書亞記", 24), ("士師記", 21), ("路得記", 4), ("撒母耳記上", 31), ("撒母耳記下", 24),
    ("列王紀上", 22), ("列王紀下", 25), ("歷代志上", 29), ("歷代志下", 36), ("以斯拉記", 10),
    ("尼希米記", 13), ("以斯帖記", 10), ("約伯記", 42), ("詩篇", 150), ("箴言", 31),
    ("傳道書", 12), ("雅歌", 8), ("以賽亞書", 66), ("耶利米書", 52), ("耶利米哀歌", 5),
    ("以西結書", 48), ("但以理書", 12), ("何西阿書", 14), ("約珥書", 3), ("阿摩司書", 9),
    ("俄巴底亞書", 1), ("約拿書", 4), ("彌迦書", 7), ("那鴻書", 3), ("哈巴谷書", 3),
    ("西番雅書", 3), ("哈該書", 2), ("撒迦利亞書", 14), ("瑪拉基書", 4),
    ("馬太福音", 28), ("馬可福音", 16), ("路加福音", 24), ("約翰福音", 21), ("使徒行傳", 28),
    ("羅馬書", 16), ("哥林多前書", 16), ("哥林多後書", 13), ("加拉太書", 6), ("以弗所書", 6),
    ("腓立比書", 4), ("歌羅西書", 4), ("帖撒羅尼迦前書", 5), ("帖撒羅尼迦後書", 3),
    ("提摩太前書", 6), ("提摩太後書", 4), ("提多書", 3), ("腓利門書", 1), ("希伯來書", 13),
    ("雅各書", 5), ("彼得前書", 5), ("彼得後書", 3), ("約翰一書", 5), ("約翰二書", 1),
    ("約翰三書", 1), ("猶大書", 1), ("啟示錄", 22),
]
BIBLE_BOOK_NAMES = [b[0] for b in BIBLE_BOOKS]

# 短書卷（≤2 章）— full_passage 模式一次過讀完整卷
SHORT_BOOKS = {"俄巴底亞書", "腓利門書", "約翰二書", "約翰三書", "猶大書", "該亞書" if False else "哈該書"}


def _book_range(
    book_selection: str, start_book: str | None, end_book: str | None,
) -> list[tuple[str, int]]:
    """Resolve book_selection / custom range → ordered [(book, chapters), ...]."""
    if book_selection == "ot_full":
        return BIBLE_BOOKS[:39]
    if book_selection == "nt_full":
        return BIBLE_BOOKS[39:]
    if book_selection == "psalms_proverbs":
        return [("詩篇", 150), ("箴言", 31)]
    if book_selection == "gospels":
        return BIBLE_BOOKS[39:43]
    if book_selection == "pentateuch":
        return BIBLE_BOOKS[:5]
    if book_selection == "pauline_epistles":
        return BIBLE_BOOKS[45:58]
    if book_selection == "custom_range":
        try:
            s = BIBLE_BOOK_NAMES.index(start_book) if start_book else 0
            e = BIBLE_BOOK_NAMES.index(end_book) if end_book else len(BIBLE_BOOKS) - 1
        except ValueError:
            s, e = 0, len(BIBLE_BOOKS) - 1
        if s > e:
            s, e = e, s
        return BIBLE_BOOKS[s:e + 1]
    return BIBLE_BOOKS  # ot_nt_mixed / default


def _resolve_passages_for_day(
    plan: str, book_selection: str, day_index: int, chapters_per_push: str,
    start_book: str | None = None, end_book: str | None = None,
    start_chapter: int | None = None, end_chapter: int | None = None,
) -> list[str]:
    """Map (plan, day_index) → list of scripture references (真實章數順序).

    - 用 BIBLE_BOOKS 真實章數，由 start (book, chapter) 順序推進
    - chapters_per_push: '1'|'2'|'3' = 每日幾章；'full_passage' = 整卷（短卷適用）
    - day_index 推進：每日 chapters_per_push 章，行完範圍自動 wrap
    - start_chapter / end_chapter：容許由任何一章開始／喺任何一章停止
    """
    books = _book_range(book_selection, start_book, end_book)
    if not books:
        return []

    per_day = int(chapters_per_push) if chapters_per_push not in ("full_passage", None) else 1

    # 起點：start_book/start_chapter（default 範圍第一本書第1章）
    if book_selection == "custom_range" and start_book and start_chapter:
        try:
            s_book_idx = BIBLE_BOOK_NAMES.index(start_book)
        except ValueError:
            s_book_idx = 0
        # 起點書卷喺範圍內先計
        start_offset = 0
        for b_name, b_ch in books:
            if b_name == start_book:
                break
            start_offset += b_ch
        start_ch = max(1, min(start_chapter, dict(books).get(start_book, 1)))
        # start_chapter 用 chapter-1 偏移（第1章 = offset 0）
        start_offset += (start_ch - 1)
    else:
        start_offset = 0

    # 全範圍章數（由 start offset 計到 range 尾）
    total_chapters_all = sum(ch for _, ch in books)
    # end_chapter 終點：如果指定咗，範圍尾 = end_book 嘅 end_chapter（0 = 讀到書卷尾）
    if book_selection == "custom_range" and end_book and end_chapter:
        try:
            e_book_idx = BIBLE_BOOK_NAMES.index(end_book)
        except ValueError:
            e_book_idx = len(books) - 1
        # 計算 end_book 之前所有章數（由範圍起計）
        end_offset = 0
        for b_name, b_ch in books:
            if b_name == end_book:
                break
            end_offset += b_ch
        e_ch = end_chapter if end_chapter > 0 else dict(books).get(end_book, 1)
        e_ch = max(1, min(e_ch, dict(books).get(end_book, 1)))
        end_offset += e_ch  # 讀到 end_book 嘅 end_chapter（含）
        range_end = end_offset
    else:
        range_end = total_chapters_all
    total_in_range = range_end - start_offset
    if total_in_range <= 0:
        return []

    # day_index → 線性 offset（wrap）
    pos = (start_offset + day_index * per_day) % total_chapters_all
    if pos < start_offset or pos >= range_end:
        pos = start_offset + ((pos - start_offset) % total_in_range)

    # 由 pos 開始攞 per_day 章（逐章行，跨書卷）
    refs: list[str] = []
    chapters = [(name, ch_n) for name, ch_cnt in books for ch_n in range(1, ch_cnt + 1)]
    # 過濾 start offset 之前嘅 chapters（除非 wrap）
    effective = chapters[start_offset:range_end] + chapters[start_offset:start_offset + (range_end - start_offset)]
    for i in range(per_day):
        refs.append(f"{effective[(pos - start_offset + i) % len(effective)][0]} {effective[(pos - start_offset + i) % len(effective)][1]}")
    return refs


def _bible_config_fingerprint(opts: dict) -> str:
    """讀經設定 fingerprint — settings 有變（plan/book_selection/start/end/
    chapters_per_push）→ fingerprint 唔同 → day_index 要 reset 0。

    2026-08-26 事件：用戶期望但以理書 3，但 settings 起點係以西結書 5 —
    改設定後舊 day_index 冇 reset 會跳章/錯章。fingerprint 解決呢個問題：
    任何設定變更都會令下次 generate 由頭（day 0）計起。
    """
    import hashlib
    parts = [
        str(opts.get("plan", "")),
        str(opts.get("book_selection", "")),
        str(opts.get("start_book") or ""),
        str(opts.get("start_chapter") or ""),
        str(opts.get("end_book") or ""),
        str(opts.get("end_chapter") or ""),
        str(opts.get("chapters_per_push", "")),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


async def bible_reading(ctx: AISessionContext, db: AsyncSession, options: dict | None = None) -> list[dict[str, Any]]:
    """讀經進度：根據 book_selection + plan + chapters_per_push 計算今日經文。

    Deep options（6 個）:
      - book_selection: ot_full / nt_full / ot_nt_mixed / psalms_proverbs /
        gospels / pentateuch / pauline_epistles / custom
      - plan: one_year / ninety_days / thirty_days_topical / chronological / custom_pace
      - chapters_per_push: '1' | '2' | '3' | 'full_passage'
      - time_of_day: morning / noon / evening / night（對齊 SLOT_PROMPTS）
      - translation: cuvmp / cnvs / esv / niv / kjv
      - reminder: enabled / silent

    數據源：bible_reading_progress（進度）+ bible_verses（靜態經文）。
    經文必須逐字呈現 — 唔可以由 LLM 改寫（prompt 層另加硬性規則）。
    """
    opts = options or {}
    plan = opts.get("plan", "one_year")
    chapters = opts.get("chapters_per_push", "1")
    translation = opts.get("translation", "cuvmp")
    book_selection = opts.get("book_selection", "ot_nt_mixed")
    reminder = opts.get("reminder", "enabled")
    start_book = opts.get("start_book") or None
    end_book = opts.get("end_book") or None
    start_chapter = opts.get("start_chapter") or None
    end_chapter = opts.get("end_chapter") or None

    # time_of_day filter（用戶 2026-08-25：「CRM briefing 亂了」）：
    # 經文只喺指定時段嘅 briefing 出現一次，唔好每個 greeting slot 重複。
    # greeting mode：ctx.slot 對應 briefing slot（morning/noon/evening/night），
    # time_of_day 唔 match 就唔出。custom mode：generate_briefing 傳嘅 slot
    # 就係 time_of_day 本身，自然 match。
    tod = opts.get("time_of_day", "morning")
    if getattr(ctx, "slot", None) and tod and ctx.slot != tod:
        return []
    try:
        start_chapter = int(start_chapter) if start_chapter else None
        end_chapter = int(end_chapter) if end_chapter else None
    except (TypeError, ValueError):
        start_chapter, end_chapter = None, None

    from app.models.bible_reading import BibleReadingProgress, BibleVerse

    # 讀經設定 fingerprint — settings 有變就 reset day_index（2026-08-26）
    cfg_fp = _bible_config_fingerprint({
        "plan": plan, "book_selection": book_selection,
        "start_book": start_book, "start_chapter": start_chapter,
        "end_book": end_book, "end_chapter": end_chapter,
        "chapters_per_push": chapters,
    })

    try:
        progress = (
            await db.execute(
                select(BibleReadingProgress).where(
                    BibleReadingProgress.tenant_id == ctx.tenant_id,
                    BibleReadingProgress.user_id == ctx.user_id,
                    BibleReadingProgress.plan == plan,
                )
            )
        ).scalar_one_or_none()

        if progress is None:
            progress = BibleReadingProgress(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                plan=plan,
                book_selection=book_selection,
                day_index=0,
                config_fingerprint=cfg_fp,
                started_at=datetime.now(_UTC),
            )
            db.add(progress)
            await db.flush()
        elif progress.config_fingerprint != cfg_fp:
            # 用戶改咗讀經設定（plan/book_selection/start/end/chapters）→
            # 由頭計起，避免舊 day_index 跳章/錯章（2026-08-26 事件）。
            progress.book_selection = book_selection
            progress.day_index = 0
            progress.config_fingerprint = cfg_fp
            progress.started_at = datetime.now(_UTC)
            progress.last_completed_at = None
            await db.flush()

        passages = _resolve_passages_for_day(
            plan=plan, book_selection=book_selection,
            day_index=progress.day_index, chapters_per_push=chapters,
            start_book=start_book, end_book=end_book,
            start_chapter=start_chapter, end_chapter=end_chapter,
        )
        if not passages:
            return []

        async def _fetch_verses(trans: str):
            # passage 格式係「馬太福音 1」（冇 verse number）— 用 prefix match
            # 先 match 到「馬太福音 1:1」…「馬太福音 1:25」全部 verses
            clause = [
                or_(*[BibleVerse.reference.like(f"{p}:%") for p in passages]),
            ]
            return (
                await db.execute(
                    select(BibleVerse).where(
                        BibleVerse.translation == trans,
                        *clause,
                    ).order_by(BibleVerse.reference.asc())
                )
            ).scalars().all()

        verses = await _fetch_verses(translation)

        if not verses:
            # 指定譯本未 seed → fallback 去 kjv（public-domain seed 齊全），
            # 再唔得先出 pending_seed 進度資訊
            fallback_translation = "kjv"
            verses = await _fetch_verses(fallback_translation)
            if verses:
                translation = fallback_translation
            else:
                return [{
                    "reference": passages[0], "text": "", "translation": translation,
                    "day_index": progress.day_index,
                    "total_days": BIBLE_PLAN_TOTAL_DAYS.get(plan),
                    "reminder": reminder,
                    "pending_seed": True,
                }]
    except Exception:
        return []

    # ── Bible app 連結（redirect）──
    # bible.com (YouVersion) 深連結：https://www.bible.com/bible/<ver>/<book>.<ch>
    # 微讀聖經 (WeDevote) 深連結：https://wd.bible/<book>.<ch>  (fallback 主站)
    # 教會年曆：簡單計算節期（跟 Gregorian 固定日 + 復活節推算）
    def _bible_links(ref: str) -> dict[str, str]:
        # ref: 「以西結書 47:1」→ book + chapter
        try:
            book_cn, ch_part = ref.rsplit(" ", 1)
            ch = ch_part.split(":")[0]
        except ValueError:
            return {}
        # 英文書名 map（bible.com 用英文縮寫）
        en_abbr = {
            "創世記": "GEN", "出埃及記": "EXO", "利未記": "LEV", "民數記": "NUM",
            "申命記": "DEU", "約書亞記": "JOS", "士師記": "JDG", "路得記": "RUT",
            "撒母耳記上": "1SA", "撒母耳記下": "2SA", "列王紀上": "1KI", "列王紀下": "2KI",
            "歷代志上": "1CH", "歷代志下": "2CH", "以斯拉記": "EZR", "尼希米記": "NEH",
            "以斯帖記": "EST", "約伯記": "JOB", "詩篇": "PSA", "箴言": "PRO",
            "傳道書": "ECC", "雅歌": "SNG", "以賽亞書": "ISA", "耶利米書": "JER",
            "耶利米哀歌": "LAM", "以西結書": "EZK", "但以理書": "DAN", "何西阿書": "HOS",
            "約珥書": "JOL", "阿摩司書": "AMO", "俄巴底亞書": "OBA", "約拿書": "JON",
            "彌迦書": "MIC", "那鴻書": "NAM", "哈巴谷書": "HAB", "西番雅書": "ZEP",
            "哈該書": "HAG", "撒迦利亞書": "ZEC", "瑪拉基書": "MAL",
            "馬太福音": "MAT", "馬可福音": "MRK", "路加福音": "LUK", "約翰福音": "JHN",
            "使徒行傳": "ACT", "羅馬書": "ROM", "哥林多前書": "1CO", "哥林多後書": "2CO",
            "加拉太書": "GAL", "以弗所書": "EPH", "腓立比書": "PHP", "歌羅西書": "COL",
            "帖撒羅尼迦前書": "1TH", "帖撒羅尼迦後書": "2TH", "提摩太前書": "1TI",
            "提摩太後書": "2TI", "提多書": "TIT", "腓利門書": "PHM", "希伯來書": "HEB",
            "雅各書": "JAS", "彼得前書": "1PE", "彼得後書": "2PE", "約翰一書": "1JN",
            "約翰二書": "2JN", "約翰三書": "3JN", "猶大書": "JUD", "啟示錄": "REV",
        }
        abbr = en_abbr.get(book_cn, "")
        if not abbr:
            return {}
        bible_com = f"https://www.bible.com/bible/1/{abbr}.{ch}"
        we_devote = f"https://wd.bible/{book_cn}.{ch}" if False else f"https://www.we-devote.com/bible?q={book_cn}%20{ch}"
        return {"bible_com": bible_com, "we_devote": we_devote}

    now_hkt = _now_hkt()
    liturgical = _liturgical_season(now_hkt)

    return [
        {
            "reference": v.reference, "text": v.text, "translation": translation,
            "translation_label": BIBLE_TRANSLATION_LABELS.get(translation, translation),
            "day_index": progress.day_index,
            "total_days": BIBLE_PLAN_TOTAL_DAYS.get(plan),
            "reminder": reminder,
            "links": _bible_links(str(v.reference)),
            "liturgical_season": liturgical["season"],
            "liturgical_day": liturgical["day"],
        }
        for v in verses
    ]

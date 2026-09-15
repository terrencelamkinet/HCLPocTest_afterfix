"""AI Secretary Settings — per-user settings API.

GET/PATCH /settings   — read/update the current user's secretary settings
                        (lazy-create with defaults on first read)
POST /settings/reset  — restore defaults
GET /briefing         — briefing filtered by the user's enabled modules
GET /llm-usage        — per-user LLM usage summary (from ai_usage_events)

All endpoints derive user_id / tenant_id from the authenticated request
context (request.state.ai_context) — never from the request body.
RLS (user_id + tenant_id policy, FORCE) enforces isolation at the DB layer.
"""
import re
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.ai.secretary_settings import (
    SecretarySettings,
    ChannelCredential,
    DEFAULT_MODULES,
    DEFAULT_WORKDAYS,
    DEFAULT_CHANNELS,
    DEFAULT_GREETING_SLOTS,
    VALID_TONES,
    VALID_LANGS,
    VALID_CHANNELS,
    normalize_modules,
    module_keys,
)
from app.models.whatsapp import WhatsAppMapping
from app.models.telegram_bot import TelegramBotMapping
from app.models.ai.pending_question import PendingAIQuestion
from app.models.crm import (
    Company,
    Contact,
    Project,
    ProjectCalendarEvent,
    Touchpoint,
)
from app.services.calendar_awareness import list_pending, scan_calendar_gaps

router = APIRouter(prefix="/api/v1/ai-secretary", tags=["AI Secretary"])

KNOWN_MODULES = {
    "weather", "today_tasks", "meetings", "project_status", "hot_leads",
    "stale_deals", "overdue_followup", "unread_messages", "birthday_reminders",
    "quote_tracking", "invoice_reminders", "team_updates", "calendar_conflicts",
    "news_industry", "traffic_commute", "email_draft_review", "sales_kpi",
    "customer_sentiment", "expense_reminders", "personal_reminders",
    "bible_reading",
}
VALID_WORKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

# ── Module connection state ─────────────────────────────────────
# True = briefing data source implemented & tested. False = greyed out
# in the UI (cannot be selected). Flip to True as each module ships.
MODULE_CONNECTED: dict[str, bool] = {
    "weather": True,             # ✅ HKO Open Data API (briefing_sources)
    "today_tasks": True,         # ✅ tasks 表 (briefing 已實作)
    "meetings": True,            # ✅ Google Calendar (briefing 已實作)
    "project_status": True,        # ✅ projects 表 (briefing_sources)
    "hot_leads": True,            # ✅ deals probability>=70 (briefing_sources)
    "stale_deals": True,           # ✅ deals 表 (briefing_sources)
    "overdue_followup": True,      # ✅ touchpoints 表 (briefing_sources)
    "unread_messages": True,     # ✅ Gmail/Outlook OAuth token (briefing_sources)
    "birthday_reminders": True,  # ✅ contacts custom_fields (briefing_sources)
    "quote_tracking": True,       # ✅ quotes 表 (briefing_sources)
    "invoice_reminders": True,   # ✅ quotations 表 (briefing_sources)
    "team_updates": True,        # ✅ teams + tasks (briefing_sources)
    "calendar_conflicts": True, # ✅ project_calendar_events 重疊邏輯 (briefing_sources)
    "news_industry": True,      # ✅ RSS fetch (briefing_sources)
    "traffic_commute": True,    # ✅ 運輸署 API (briefing_sources)
    "email_draft_review": True, # ✅ ai_drafts 表 (briefing_sources)
    "sales_kpi": True,           # ✅ user_targets + deals (briefing_sources)
    "customer_sentiment": True, # ✅ ai_messages 分析 (briefing_sources)
    "expense_reminders": True,  # ✅ expenses 表 (briefing_sources)
    "personal_reminders": True, # ✅ personal_notes 表 (briefing_sources)
    "bible_reading": True,      # ✅ bible_reading_progress + bible_verses (briefing_sources)
}


# ── Schemas ─────────────────────────────────────────────────────
class SettingsOut(BaseModel):
    modules: dict[str, dict]  # {module_key: {option_key: value}} — 深層選項
    workdays: list[str]
    weekend_mute: bool
    strict_silence: bool
    calendar_awareness: bool
    tone: str
    instructions: str
    lang_pref: str
    detail_level: int
    channels: dict[str, Any]
    work_start: str
    work_end: str
    greeting_slots: list[dict[str, Any]]
    connected_modules: list[str]
    updated_at: datetime | None = None


class SettingsPatch(BaseModel):
    modules: dict[str, dict | None] | None = None
    workdays: list[str] | None = None
    weekend_mute: bool | None = None
    strict_silence: bool | None = None
    calendar_awareness: bool | None = None
    tone: str | None = None
    instructions: str | None = None
    lang_pref: str | None = None
    detail_level: int | None = Field(default=None, ge=1, le=3)
    channels: dict[str, Any] | None = None
    work_start: str | None = None
    work_end: str | None = None
    greeting_slots: list[dict[str, Any]] | None = None

    @field_validator("modules")
    @classmethod
    def _check_modules(cls, v):
        if v is None:
            return v
        if isinstance(v, list):
            # 向後兼容：舊前端可能仲 send string[] — normalize 做 dict
            bad = set(v) - KNOWN_MODULES
            if bad:
                raise ValueError(f"unknown modules: {sorted(bad)}")
            return {m: {} for m in v}
        if not isinstance(v, dict):
            raise ValueError("modules must be a dict of {module: options} or list")
        bad = set(v) - KNOWN_MODULES
        if bad:
            raise ValueError(f"unknown modules: {sorted(bad)}")
        # value = None 表示刪除該 module（PATCH merge 語意）
        return {k: (opts if opts is not None else None) for k, opts in v.items()}

    @field_validator("workdays")
    @classmethod
    def _check_workdays(cls, v):
        if v is None:
            return v
        bad = set(v) - VALID_WORKDAYS
        if bad:
            raise ValueError(f"unknown workdays: {sorted(bad)}")
        return v

    @field_validator("tone")
    @classmethod
    def _check_tone(cls, v):
        if v is not None and v not in VALID_TONES:
            raise ValueError(f"tone must be one of {VALID_TONES}")
        return v

    @field_validator("lang_pref")
    @classmethod
    def _check_lang(cls, v):
        if v is not None and v not in VALID_LANGS:
            raise ValueError(f"lang_pref must be one of {VALID_LANGS}")
        return v

    @field_validator("channels")
    @classmethod
    def _check_channels(cls, v):
        if v is None:
            return v
        bad = set(v) - set(VALID_CHANNELS)
        if bad:
            raise ValueError(f"unknown channels: {sorted(bad)}")
        return v

    @field_validator("work_start", "work_end")
    @classmethod
    def _check_time(cls, v):
        if v is None:
            return v
        try:
            time.fromisoformat(v)
        except ValueError:
            raise ValueError(f"invalid time: {v!r} (expect HH:MM)")
        return v


# ── Helpers ─────────────────────────────────────────────────────
_ZERO = uuid.UUID(int=0)


def _ctx_ids(request: Request) -> tuple[uuid.UUID, uuid.UUID]:
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(401, "AI session context not initialized")
    user_id = getattr(ctx, "user_id", None) or _ZERO
    tenant_id = getattr(ctx, "tenant_id", None) or getattr(request.state, "tenant_id", None) or _ZERO
    # No valid JWT → middleware leaves zero-UUID sentinels (truthy) → explicit 401
    if user_id == _ZERO or tenant_id == _ZERO:
        raise HTTPException(401, "Not authenticated")
    return user_id, tenant_id


def _to_out(row: SecretarySettings) -> SettingsOut:
    def t2s(v) -> str:
        return v.strftime("%H:%M") if isinstance(v, time) else str(v)

    return SettingsOut(
        modules=normalize_modules(row.modules or DEFAULT_MODULES),
        workdays=list(row.workdays or DEFAULT_WORKDAYS),
        weekend_mute=row.weekend_mute,
        strict_silence=row.strict_silence,
        calendar_awareness=row.calendar_awareness,
        tone=row.tone,
        instructions=row.instructions,
        lang_pref=row.lang_pref,
        detail_level=row.detail_level,
        channels=row.channels or dict(DEFAULT_CHANNELS),
        work_start=t2s(row.work_start),
        work_end=t2s(row.work_end),
        greeting_slots=row.greeting_slots or DEFAULT_GREETING_SLOTS,
        connected_modules=[m for m, c in MODULE_CONNECTED.items() if c],
        updated_at=row.updated_at,
    )


async def _to_out_connected(row: SecretarySettings, db: AsyncSession, tenant_id: uuid.UUID) -> SettingsOut:
    """Build SettingsOut, reconciling real WhatsApp/Telegram connection state.

    The stored `channels` JSONB may be stale (e.g. whatsapp connected via OTP
    flow but the ai-secretary row never flipped). Ground truth lives in
    nexus_crm.nexus_whatsapp_mappings / nexus_telegram_mappings, so we query
    those and overlay connected=True on top of the stored row.
    """
    out = _to_out(row)
    channels = dict(out.channels or DEFAULT_CHANNELS)

    # WhatsApp: mirror im_push.get_prefs — active mapping ⇒ connected
    wa = (
        await db.execute(
            select(WhatsAppMapping).where(
                WhatsAppMapping.tenant_id == tenant_id,
                WhatsAppMapping.user_id == row.user_id,
                WhatsAppMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    wa_state = dict(channels.get("whatsapp", {}))
    if wa is not None and not wa_state.get("connected"):
        wa_state["connected"] = True
        # Keep previously-toggled enabled state if set, else default on like im_push
        if wa_state.get("enabled") is None:
            wa_state["enabled"] = True
        channels["whatsapp"] = wa_state

    # Telegram: active mapping ⇒ connected (kept in sync by telegram router,
    # but harden here too so a stale row never under-reports an active bot).
    tg = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == row.user_id,
                TelegramBotMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    tg_state = dict(channels.get("telegram", {}))
    if tg is not None and not tg_state.get("connected"):
        tg_state["connected"] = True
        if tg_state.get("enabled") is None:
            tg_state["enabled"] = True
        channels["telegram"] = tg_state

    out.channels = channels
    return out


async def _get_or_create(db: AsyncSession, user_id, tenant_id) -> SecretarySettings:
    row = (
        await db.execute(
            select(SecretarySettings).where(SecretarySettings.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row:
        return row
    row = SecretarySettings(user_id=user_id, tenant_id=tenant_id)
    db.add(row)
    await db.flush()
    return row


# ── Endpoints ───────────────────────────────────────────────────
@router.get("/settings", response_model=SettingsOut)
async def get_settings(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    user_id, _ = _ctx_ids(request)
    tenant_id = _ctx_ids(request)[1]
    row = await _get_or_create(db, user_id, tenant_id)
    await db.commit()
    return await _to_out_connected(row, db, tenant_id)


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(
    patch: SettingsPatch,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    user_id, tenant_id = _ctx_ids(request)
    row = await _get_or_create(db, user_id, tenant_id)

    data = patch.model_dump(exclude_unset=True)
    # Modules must be connected — reject unknown / not-yet-connected ids.
    # modules 而家係 dict {module: options}（SettingsPatch validator 已 normalize）
    if "modules" in data:
        unknown = [m for m in data["modules"] if m not in MODULE_CONNECTED]
        if unknown:
            raise HTTPException(422, f"unknown modules: {unknown}")
        unconnected = [m for m in data["modules"] if not MODULE_CONNECTED[m]]
        if unconnected:
            raise HTTPException(422, f"modules not yet connected: {unconnected}")
    for k, v in data.items():
        if k == "modules":
            # Merge — PATCH 語意：只更新傳入嘅 module/options，保留其他；
            # opts = null 表示刪除該 module
            cur: dict = normalize_modules(row.modules or DEFAULT_MODULES)
            for mod_id, opts in (v or {}).items():
                if opts is None:
                    cur.pop(mod_id, None)
                else:
                    cur[mod_id] = {**(cur.get(mod_id) or {}), **(opts or {})}
            setattr(row, "modules", cur)
            continue
        if k in ("work_start", "work_end") and isinstance(v, str):
            v = time.fromisoformat(v)
        setattr(row, k, v)

    await db.flush()
    await db.refresh(row)  # same transaction — RLS GUC still active, picks up trigger-updated_at
    await db.commit()
    return await _to_out_connected(row, db, tenant_id)


@router.post("/settings/reset", response_model=SettingsOut)
async def reset_settings(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    user_id, tenant_id = _ctx_ids(request)
    row = await _get_or_create(db, user_id, tenant_id)

    row.modules = {m: {} for m in DEFAULT_MODULES}
    row.workdays = list(DEFAULT_WORKDAYS)
    row.weekend_mute = True
    row.strict_silence = True
    row.calendar_awareness = True
    row.tone = "professional"
    row.instructions = ""
    row.lang_pref = "zh-HK"
    row.detail_level = 2
    row.channels = dict(DEFAULT_CHANNELS)
    row.work_start = time(9, 0)
    row.work_end = time(18, 0)
    row.greeting_slots = [dict(s) for s in DEFAULT_GREETING_SLOTS]

    await db.flush()
    await db.refresh(row)
    await db.commit()
    return await _to_out_connected(row, db, tenant_id)


@router.get("/briefing")
async def get_briefing(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Briefing content gated by the user's enabled modules (working-hours aware)."""
    from app.routers.ai import _build_crm_briefing  # reuse existing aggregator

    user_id, tenant_id = _ctx_ids(request)
    row = await _get_or_create(db, user_id, tenant_id)
    lang_pref = str(row.lang_pref or "zh-HK")  # 用戶語言偏好 — 控制 ai_tip / 交通路況語言
    # NOTE: NO commit here — get_tenant_session's set_config GUCs are
    # transaction-scoped (3rd arg=true); a commit would end the transaction
    # and strip RLS context, making every subsequent DB query return 0 rows.
    # The generator's trailing commit persists the lazy-create row.

    ctx = getattr(request.state, "ai_context", None)
    if ctx is None:
        raise HTTPException(401, "AI session context not initialized")
    brief = await _build_crm_briefing(ctx, db, lang_pref=lang_pref)

    from zoneinfo import ZoneInfo
    now_local = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    mods = set(module_keys(row.modules or DEFAULT_MODULES))
    mod_options: dict[str, dict] = normalize_modules(row.modules or DEFAULT_MODULES)

    # Working-hours gate (HKT) — task/project items only inside window
    cur = now_local.time()
    ws, we = row.work_start, row.work_end
    in_hours = (ws <= cur < we) if ws < we else (cur >= ws or cur < we)

    def _in_workday() -> bool:
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        return days[now_local.weekday()] in (row.workdays or DEFAULT_WORKDAYS)

    workday = _in_workday()
    if not workday and row.weekend_mute:
        in_hours = False

    show_risks = bool(in_hours) and bool(mods & {"stale_deals", "quote_tracking"})
    show_tasks = bool(in_hours) and "today_tasks" in mods
    show_events = "meetings" in mods

    # ── Module data sources (only for enabled + connected modules) ──
    # 深層選項：每個 module 嘅 options 由 mod_options dict 傳入（冇設定 → 預設）
    from app.ai import briefing_sources as bs

    projects = await bs.project_status(ctx, db, options=mod_options.get("project_status", {})) if "project_status" in mods else []
    stale = await bs.stale_deals(ctx, db, options=mod_options.get("stale_deals", {})) if "stale_deals" in mods else []
    quotes = await bs.quote_tracking(ctx, db, options=mod_options.get("quote_tracking", {})) if "quote_tracking" in mods else []
    followups = await bs.overdue_followup(ctx, db, options=mod_options.get("overdue_followup", {})) if "overdue_followup" in mods else []
    birthdays = await bs.birthday_reminders(ctx, db, options=mod_options.get("birthday_reminders", {})) if "birthday_reminders" in mods else []
    leads = await bs.hot_leads(ctx, db, options=mod_options.get("hot_leads", {})) if "hot_leads" in mods else []
    kpis = await bs.sales_kpi(ctx, db, options=mod_options.get("sales_kpi", {})) if "sales_kpi" in mods else []
    team = await bs.team_updates(ctx, db, options=mod_options.get("team_updates", {})) if "team_updates" in mods else []
    invoices = await bs.invoice_reminders(ctx, db, options=mod_options.get("invoice_reminders", {})) if "invoice_reminders" in mods else []
    weather = await bs.weather(ctx, db, options=mod_options.get("weather", {})) if "weather" in mods else []
    unread = await bs.unread_messages(ctx, db, options=mod_options.get("unread_messages", {})) if "unread_messages" in mods else []
    conflicts = await bs.calendar_conflicts(ctx, db, options=mod_options.get("calendar_conflicts", {})) if "calendar_conflicts" in mods else []
    news = await bs.news_industry(ctx, db, options=mod_options.get("news_industry", {})) if "news_industry" in mods else []
    traffic = await bs.traffic_commute(ctx, db, lang_pref=lang_pref, options=mod_options.get("traffic_commute", {})) if "traffic_commute" in mods else []
    drafts = await bs.email_draft_review(ctx, db, options=mod_options.get("email_draft_review", {})) if "email_draft_review" in mods else []
    sentiment = await bs.customer_sentiment(ctx, db, options=mod_options.get("customer_sentiment", {})) if "customer_sentiment" in mods else []
    expenses = await bs.expense_reminders(ctx, db, options=mod_options.get("expense_reminders", {})) if "expense_reminders" in mods else []
    personal = await bs.personal_reminders(ctx, db, options=mod_options.get("personal_reminders", {})) if "personal_reminders" in mods else []
    bible = await bs.bible_reading(ctx, db, options=mod_options.get("bible_reading", {})) if "bible_reading" in mods else []

    return {
        "modules": sorted(mods),
        "in_working_hours": in_hours,
        "workday": workday,
        "schedule": brief["schedule"] if show_events else [],
        "tasks": brief["tasks"] if show_tasks else [],
        "projects": projects if (bool(in_hours) and "project_status" in mods) else [],
        "stale_deals": stale if (show_risks and "stale_deals" in mods) else [],
        "quotes": quotes if (show_risks and "quote_tracking" in mods) else [],
        "overdue_followups": followups if (bool(in_hours) and "overdue_followup" in mods) else [],
        "birthdays": birthdays if (bool(in_hours) and "birthday_reminders" in mods) else [],
        "hot_leads": leads if (bool(in_hours) and "hot_leads" in mods) else [],
        "sales_kpi": kpis if (bool(in_hours) and "sales_kpi" in mods) else [],
        "team_updates": team if (bool(in_hours) and "team_updates" in mods) else [],
        "invoice_reminders": invoices if (bool(in_hours) and "invoice_reminders" in mods) else [],
        "weather": weather if (bool(in_hours) and "weather" in mods) else [],
        "unread_messages": unread if (bool(in_hours) and "unread_messages" in mods) else [],
        "calendar_conflicts": conflicts if (bool(in_hours) and "calendar_conflicts" in mods) else [],
        "news_industry": news if (bool(in_hours) and "news_industry" in mods) else [],
        "traffic_commute": traffic if (bool(in_hours) and "traffic_commute" in mods) else [],
        "email_draft_review": drafts if (bool(in_hours) and "email_draft_review" in mods) else [],
        "customer_sentiment": sentiment if (bool(in_hours) and "customer_sentiment" in mods) else [],
        "expense_reminders": expenses if (bool(in_hours) and "expense_reminders" in mods) else [],
        "personal_reminders": personal if (bool(in_hours) and "personal_reminders" in mods) else [],
        "bible_reading": bible if "bible_reading" in mods else [],
        "ai_tip": brief["ai_tip"],
        "greeting_slots": row.greeting_slots or DEFAULT_GREETING_SLOTS,
        "work_start": row.work_start.strftime("%H:%M"),
        "work_end": row.work_end.strftime("%H:%M"),
    }


async def _plan_label(db: AsyncSession, tenant_id) -> str:
    """Subscription plan label — paid = 'pro subscription'、normal = 'free subscription'（2026-09-07 Terrence 要求）"""
    try:
        from app.ai.quota.weekly import get_tenant_plan
        plan = await get_tenant_plan(db, tenant_id)
        return "pro subscription" if plan == "pro" else "free subscription"
    except Exception:
        return "free subscription"


@router.get("/llm-usage")
async def get_llm_usage(
    request: Request,
    days: int = 7,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Per-user LLM usage summary from ai_usage_events (last N days)."""
    user_id, tenant_id = _ctx_ids(request)
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))

    total = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)                                   AS calls,
                    COALESCE(sum(input_tokens), 0)             AS input_tokens,
                    COALESCE(sum(output_tokens), 0)            AS output_tokens,
                    COALESCE(sum(cost_estimate), 0)            AS cost_estimate,
                    COALESCE(sum(CASE WHEN result_status = 'error' THEN 1 ELSE 0 END), 0) AS errors
                FROM nexus_ai.ai_usage_events
                WHERE user_id = :uid AND created_at >= :since
                """
            ),
            {"uid": user_id, "since": since},
        )
    ).one()

    by_model = (
        await db.execute(
            text(
                """
                SELECT model, count(*) AS calls, sum(input_tokens) AS input, sum(output_tokens) AS output
                FROM nexus_ai.ai_usage_events
                WHERE user_id = :uid AND created_at >= :since
                GROUP BY model ORDER BY calls DESC
                """
            ),
            {"uid": user_id, "since": since},
        )
    ).all()

    by_module = (
        await db.execute(
            text(
                """
                SELECT provider AS module, count(*) AS calls,
                       COALESCE(sum(input_tokens), 0) AS input,
                       COALESCE(sum(output_tokens), 0) AS output,
                       COALESCE(sum(cost_estimate), 0) AS cost
                FROM nexus_ai.ai_usage_events
                WHERE user_id = :uid AND created_at >= :since
                GROUP BY provider ORDER BY calls DESC
                """
            ),
            {"uid": user_id, "since": since},
        )
    ).all()

    return {
        "days": days,
        "currency": "USD",  # all provider cost cards are priced in USD
        # Subscription plan（Terrence 2026-09-07: paid = "pro subscription"、normal = "free subscription"）
        "plan": await _plan_label(db, tenant_id),
        "total_calls": total.calls or 0,
        "input_tokens": total.input_tokens or 0,
        "output_tokens": total.output_tokens or 0,
        "cost_estimate": float(total.cost_estimate or 0),
        "errors": total.errors or 0,
        "by_model": [{"model": r.model, "calls": r.calls, "input_tokens": r.input, "output_tokens": r.output} for r in by_model],
        "by_module": [{"module": r.module, "calls": r.calls, "input_tokens": r.input, "output_tokens": r.output, "cost_estimate": float(r.cost or 0)} for r in by_module],
    }


# ── Cron-triggered briefing generation (AI-app-driven pipeline) ──
SLOT_KEYS = ("morning", "noon", "evening", "night")


@router.post("/briefing/run")
async def run_briefing_generation(
    request: Request,
    slot: str = "morning",
    db: AsyncSession = Depends(get_tenant_session),
):
    """Generate + publish briefings for all AI-app users at the given slot.

    Workflow (2026-08-01): 用戶 AI 應用 modules 選擇 → collect（G08 自己
    sources）→ LLM 生成 → 存 PG generated_briefings → dashboard 讀取 +
    （用戶 enable 咗）IM push。Cron-Api-Key protected。
    """
    import os
    from app.config import settings as app_settings
    cron_key = request.headers.get("Cron-Api-Key", "")
    expected = os.environ.get("NEXUS_CRON_API_KEY", "") or app_settings.cron_api_key
    if not expected or cron_key != expected:
        raise HTTPException(403, "Invalid or missing Cron-Api-Key")
    if slot not in SLOT_KEYS:
        raise HTTPException(400, f"slot must be one of {SLOT_KEYS}")

    from app.services.briefing_generator import run_for_all_users
    stats = await run_for_all_users(db, slot)
    return {"slot": slot, "run_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), **stats}


# ── Calendar Awareness — AI 主動提問（pending questions）──
class AnswerBody(BaseModel):
    answer: str


# ── Answer action parsing（v7.06：支援 event/contact/company/touchpoint/project）──
# 前綴 pattern：「加電話：9123 4567」→ field=phone, value=9123 4567
_ANSWER_PREFIXES: list[tuple[str, str]] = [
    ("加地點：", "location"),
    ("加位置：", "location"),
    ("加 agenda：", "description"),
    ("寫低 agenda：", "description"),
    ("加備註：", "notes"),
    ("加 notes：", "notes"),
    ("加電話：", "phone"),
    ("加 email：", "email"),
    ("加電郵：", "email"),
    ("加郵箱：", "email"),
    ("加地址：", "address"),
    ("加網址：", "website"),
    ("加網站：", "website"),
    ("加 deadline：", "deadline"),
    ("加死線：", "deadline"),
    ("加截止：", "deadline"),
    ("加描述：", "description"),
]

# Keyword fallback：「電話 9123 4567」「email a@b.com」「9月1日 deadline」等自由輸入
_ANSWER_KEYWORDS: list[tuple[str, str]] = [
    ("電話", "phone"), ("手機", "phone"), ("phone", "phone"), ("tel", "phone"),
    ("email", "email"), ("電郵", "email"), ("郵箱", "email"),
    ("地址", "address"),
    ("網址", "website"), ("網站", "website"),
    ("deadline", "deadline"), ("死線", "deadline"), ("截止", "deadline"), ("限期", "deadline"),
    ("地點", "location"), ("位置", "location"),
    ("備註", "notes"), ("notes", "notes"), ("重點", "notes"),
    ("agenda", "description"),
]

# 完全自由輸入 fallback：由 source 判斷寫入邊個 field
_SOURCE_FIELD_HINTS = [
    ("record_contact", "phone"),
    ("record_company", "phone"),
    ("calendar_gap", "location"),
    ("location", "location"),
    ("agenda", "description"),
    ("phone", "phone"),
    ("email", "email"),
    ("website", "website"),
    ("deadline", "deadline"),
    ("notes", "notes"),
]


def _parse_answer_action(answer: str) -> tuple[str, str] | None:
    """解析答案 → (field, value)。支援前綴、keyword、自由輸入。"""
    a = (answer or "").strip()
    if not a:
        return None
    for prefix, field in _ANSWER_PREFIXES:
        if a.startswith(prefix):
            val = a[len(prefix):].strip().strip("，,。 ")
            return (field, val) if val else None
    low = a.lower()
    for kw, field in _ANSWER_KEYWORDS:
        idx = low.find(kw)
        if idx >= 0:
            after = a[idx + len(kw):].strip().lstrip("：:，,、 是為")
            if after:
                return field, after
            before = a[:idx].strip().strip("：:，,、 ")
            if before:
                return field, before
    return None


def _field_from_source(source: str | None) -> str | None:
    s = (source or "").lower()
    for hint, field in _SOURCE_FIELD_HINTS:
        if hint in s:
            return field
    return None


def _append_text(existing: str | None, prefix: str, val: str) -> str:
    """將 val 以 prefix 開頭追加到現有 text（有內容就換行分開）。"""
    base = (existing or "").strip()
    line = f"{prefix}{val}"
    return f"{base}\n\n{line}".strip() if base else line


def _parse_date(val: str):
    """寬鬆日期解析：2026-09-01 / 2026/9/1 / 9月1日 / 9/1 / 下週五（唔識就 None）。"""
    v = val.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    m = re.match(r"^(\d{1,2})[月/](\d{1,2})日?$", v)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = datetime.now(timezone.utc).year
        if month < datetime.now(timezone.utc).month:
            year += 1
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


@router.get("/pending-questions")
async def get_pending_questions(
    request: Request,
    force_scan: bool = True,
    db: AsyncSession = Depends(get_tenant_session),
):
    """返回 pending questions — lazy scan 一次再攞（calendar_awareness off 時直接空）。"""
    user_id, tenant_id = _ctx_ids(request)
    row = await _get_or_create(db, user_id, tenant_id)
    await db.commit()
    if row.calendar_awareness is False:
        return {"items": []}
    rows = await list_pending(db, user_id, tenant_id, force_scan=force_scan)
    return {
        "items": [
            {
                "id": str(q.id),
                "question": q.question,
                "context_type": q.context_type,
                "context_id": str(q.context_id) if q.context_id else None,
                "context_title": q.context_title,
                "suggested_answers": q.suggested_answers or [],
                "source": q.source,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in rows
        ]
    }


@router.post("/pending-questions/{qid}/answer")
async def answer_pending_question(
    qid: uuid.UUID,
    body: AnswerBody,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    user_id, tenant_id = _ctx_ids(request)
    q = (
        await db.execute(
            select(PendingAIQuestion).where(
                PendingAIQuestion.id == qid,
                PendingAIQuestion.tenant_id == tenant_id,
                PendingAIQuestion.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "question not found")
    q.status = "answered"
    q.answer = body.answer
    q.answered_at = datetime.now(timezone.utc)

    # 「唔使」→ 等同 dismiss（唔使再出現）
    if body.answer.strip() in ("唔使", "不用", "不需要", "skip", "skip it"):
        q.status = "dismissed"

    # ── v7.07: 見面活動 → 加入 Touchpoint（用戶要求）──
    # 撳「加入 Touchpoint」→ 創建 Touchpoint（由 event 帶入 title/date/location）
    # → 生成 follow-up 問題問「同邊個聯繫？」
    if body.answer.strip() == "加入 Touchpoint" and q.context_type == "calendar" and q.context_id:
        ev = (
            await db.execute(
                select(ProjectCalendarEvent).where(
                    ProjectCalendarEvent.id == q.context_id,
                    ProjectCalendarEvent.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if ev:
            ws = getattr(request.state, "workspace_id", None)
            tp = Touchpoint(
                tenant_id=tenant_id,
                workspace_id=ws,
                type="meeting",
                title=(ev.title or "").strip() or "見面活動",
                description=(ev.description or "").strip() or None,
                date=ev.start,
                location=ev.location,
                extracted_from="meeting",
                created_by=user_id,
            )
            db.add(tp)
            await db.flush()
            follow = PendingAIQuestion(
                user_id=user_id,
                tenant_id=tenant_id,
                question=f"《{ev.title}》嘅 Touchpoint 已加入，同邊個聯繫？",
                context_type="touchpoint",
                context_id=tp.id,
                context_title=ev.title,
                suggested_answers=["唔使"],
                source="touchpoint_contact",
            )
            db.add(follow)
            await db.flush()

    # ── v7.07: follow-up「同邊個聯繫？」→ 搵 contact 綁定去 Touchpoint ──
    if q.source == "touchpoint_contact" and q.context_type == "touchpoint" and q.context_id:
        ref = body.answer.strip()
        if ref and ref not in ("唔使", "不用", "不需要", "skip"):
            contact = (
                await db.execute(
                    select(Contact).where(
                        Contact.tenant_id == tenant_id,
                        or_(
                            Contact.name == ref,
                            Contact.email == ref,
                            Contact.phone == ref,
                        ),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if not contact:
                contact = (
                    await db.execute(
                        select(Contact)
                        .where(Contact.tenant_id == tenant_id, Contact.name.ilike(f"%{ref}%"))
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if contact:
                tp = (
                    await db.execute(
                        select(Touchpoint).where(
                            Touchpoint.id == q.context_id,
                            Touchpoint.tenant_id == tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                if tp:
                    tp.contact_id = contact.id
                    tp.company_id = contact.company_id

    # v7.06: 答案解析 → 實際更新對應 record（event/contact/company/touchpoint/project）
    parsed = _parse_answer_action(body.answer)
    if parsed and q.context_id:
        field, val = parsed
        # 完全自由輸入（冇前綴冇 keyword）→ 由 source 猜寫入邊個 field
        if field is None:
            field = _field_from_source(q.source or "") or ""
        ctype = q.context_type or ""

        if ctype == "calendar":
            ev = (
                await db.execute(
                    select(ProjectCalendarEvent).where(
                        ProjectCalendarEvent.id == q.context_id,
                        ProjectCalendarEvent.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if ev:
                if field == "location":
                    ev.location = val
                elif field == "description":
                    ev.description = _append_text(ev.description, "📋 Agenda：", val)

        elif ctype == "contact":
            c = (
                await db.execute(
                    select(Contact).where(
                        Contact.id == q.context_id,
                        Contact.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if c:
                if field == "phone":
                    c.phone = val
                elif field == "email":
                    c.email = val
                elif field == "address":
                    c.address = val
                elif field == "notes":
                    c.notes = _append_text(c.notes, "📝", val)

        elif ctype == "company":
            co = (
                await db.execute(
                    select(Company).where(
                        Company.id == q.context_id,
                        Company.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if co:
                if field == "phone":
                    co.phone = val
                elif field == "website":
                    co.website = val
                elif field == "address":
                    co.address = val
                elif field == "notes":
                    co.notes = _append_text(co.notes, "📝", val)

        elif ctype == "touchpoint":
            tp = (
                await db.execute(
                    select(Touchpoint).where(
                        Touchpoint.id == q.context_id,
                        Touchpoint.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if tp:
                if field == "description":
                    tp.description = _append_text(tp.description, "📝", val)
                elif field == "notes":
                    tp.description = _append_text(tp.description, "📝", val)
                elif field == "location":
                    tp.location = val

        elif ctype == "project":
            p = (
                await db.execute(
                    select(Project).where(
                        Project.id == q.context_id,
                        Project.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if p:
                if field == "deadline":
                    d = _parse_date(val)
                    if d:
                        p.deadline = d
                elif field == "description":
                    p.description = _append_text(p.description, "📝", val)
                elif field == "notes":
                    p.description = _append_text(p.description, "📝", val)

    await db.commit()
    return {"ok": True, "id": str(qid)}


@router.post("/pending-questions/{qid}/dismiss")
async def dismiss_pending_question(
    qid: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    user_id, tenant_id = _ctx_ids(request)
    q = (
        await db.execute(
            select(PendingAIQuestion).where(
                PendingAIQuestion.id == qid,
                PendingAIQuestion.tenant_id == tenant_id,
                PendingAIQuestion.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not q:
        raise HTTPException(404, "question not found")
    q.status = "dismissed"
    q.answered_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "id": str(qid)}

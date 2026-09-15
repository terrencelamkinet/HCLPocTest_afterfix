"""IM Push module — Tri-Daily Briefing delivery via WhatsApp/Telegram.

Phase A scope (2026-07-31):
- GET/PUT /im-push/prefs  — per-user delivery preferences (settings UI)
- POST /im-push/test      — send a test message to the caller's channels
- POST /im-push/briefing  — Cron-Api-Key protected; compose slot briefing + fan-out

Message format follows AI_Personal_CRM_TriDaily_Strategy.md §2.2 — highly
scannable, emoji hierarchy, deep link on every action point.
"""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.config import settings
from app.ai.session.context import AISessionContext
from app.ai.tool_registry import _get_upcoming_events, _list_tasks, _list_touchpoints
from app.models.im_push import IMDeliveryPref, PushLog, DEFAULT_SLOTS
from app.models.whatsapp import WhatsAppMapping
from app.models.telegram_bot import TelegramBotMapping
from app.models.ai.secretary_settings import ChannelCredential
from app.models.notification import Notification
from app.services import whatsapp_service, telegram_service
from app.services.secret_crypto import decrypt_secret

router = APIRouter(prefix="/api/v1")

APP_BASE_URL = "https://www.penguincrm.io"
HKT = timezone(timedelta(hours=8))
SLOTS = ("morning", "noon", "evening")


# ── Schemas ──────────────────────────────────────────────────────────
class PrefItem(BaseModel):
    channel: str
    enabled: bool = True
    slots: dict[str, bool] = dict(DEFAULT_SLOTS)
    weekend_mute: bool = True
    quiet_hours: dict[str, str] = {"start": "22:00", "end": "08:00"}
    tz: str = "Asia/Hong_Kong"


class PrefsResponse(BaseModel):
    channels: dict[str, PrefItem]


class TestPushRequest(BaseModel):
    channel: str = "whatsapp"


# ── Helpers ──────────────────────────────────────────────────────────
def _tid(request: Request) -> uuid.UUID:
    return uuid.UUID(request.state.tenant_id)


def _uid(request: Request) -> uuid.UUID:
    return uuid.UUID(request.state.user_id)


def _now_hkt() -> datetime:
    return datetime.now(HKT)


def _parse_dt(value: Any) -> datetime | None:
    """Tolerant ISO/datetime parser; assumes naive values are HKT."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HKT)
        return dt.astimezone(HKT)
    s = str(value)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=HKT)
        return dt.astimezone(HKT)
    except Exception:
        return None


def _in_quiet_hours(pref: IMDeliveryPref, now: datetime) -> bool:
    try:
        start_s, end_s = (pref.quiet_hours or {}).get("start", "22:00"), (pref.quiet_hours or {}).get("end", "08:00")
        start = datetime.strptime(start_s, "%H:%M").time()
        end = datetime.strptime(end_s, "%H:%M").time()
        t = now.time()
        if start <= end:
            return start <= t <= end
        return t >= start or t <= end  # overnight window
    except Exception:
        return False


async def _resolve_workspace(db: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    try:
        row = await db.execute(
            text("""SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :tid ORDER BY created_at ASC LIMIT 1"""),
            {"tid": tenant_id},
        )
        result = row.scalar_one_or_none()
        if result:
            return uuid.UUID(str(result))
    except Exception:
        pass
    return uuid.UUID(int=0)


def _build_ctx(tenant_id: uuid.UUID, user_id: uuid.UUID, workspace_id: uuid.UUID) -> AISessionContext:
    return AISessionContext(
        session_id=uuid.uuid4(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
        membership_id=uuid.UUID(int=0),
        plan_type="chat",
    )


def _deep_link(kind: str, entity_id: str | None = None) -> str:
    if kind == "dashboard":
        return f"{APP_BASE_URL}/l/dashboard"
    return f"{APP_BASE_URL}/l/{kind}/{entity_id}"


# ── Message composers ────────────────────────────────────────────────
def _task_emoji(title: str) -> str:
    """Pick a category emoji from the task title (user's reminder format style)."""
    t = (title or "").lower()
    if any(k in t for k in ("書", "圖書", "exam", "考試", "hpe", "h3c", "study", "溫書", "讀", "返還")):
        return "📚"
    if any(k in t for k in ("報價", "quote", "email", "電郵", "客戶", "meeting", "會議", "demo",
                            "moia", "manulife", "sales", "deal", "pipeline", "sit", "diagram", "準備")):
        return "💼"
    if any(k in t for k in ("錢", "費用", "發票", "invoice", "expense", "budget", "報銷", "繳")):
        return "💰"
    if any(k in t for k in ("屋", "家", "個人", "買", "超市", "水電")):
        return "🏠"
    return "📋"


def _due_tag(t: dict, now: datetime) -> str:
    """Inline status tag: 已逾期 (M/D) / 今日到期 / M/D 到期 / ''."""
    due = _parse_dt(t.get("due_date"))
    if not due:
        return ""
    if due.date() < now.date():
        return f"已逾期 ({due.month}/{due.day})"
    if due.date() == now.date():
        return "今日到期"
    return f"{due.month}/{due.day} 到期"


def _compose_suggestions(
    remaining: list[dict],
    tomorrow_tasks: list[dict],
    now: datetime,
    horizon_label: str,
) -> list[str]:
    """Heuristic priority suggestions — 2-4 items, one line each with a reason.

    Order: overdue first → due-soon → high priority → tomorrow's tasks.
    """
    sugg: list[str] = []
    seen: set[str] = set()

    def _push(title: str, reason: str) -> None:
        if title in seen:
            return
        seen.add(title)
        sugg.append(f"{title} — {reason}")

    # (task, due_dt) pairs — parse once, avoid repeated optional access
    parsed: list[tuple[dict, datetime | None]] = [
        (t, _parse_dt(t.get("due_date"))) for t in remaining
    ]
    overdue = [(t, d) for t, d in parsed if d is not None and d.date() < now.date()]
    due_soon = [(t, d) for t, d in parsed if d is not None and d.date() >= now.date()]
    due_soon.sort(key=lambda pair: pair[1] or now)
    high_pri = [t for t in remaining if str(t.get("priority", "")).lower() in ("urgent", "high", "p0", "p1")]

    for t, d in overdue[:2]:
        _push(t.get("title", ""), f"已逾期 ({d.month}/{d.day})，{horizon_label}優先清")
    for t, d in due_soon[:2]:
        _push(t.get("title", ""), f"{d.month}/{d.day} 到期，預早處理")
    for t in high_pri[:2]:
        _push(t.get("title", ""), "優先級較高，建議先做")
    for t in tomorrow_tasks[:2]:
        d = _parse_dt(t.get("due_date"))
        label = f"{d.month}/{d.day}" if d else "聽日"
        _push(t.get("title", ""), f"{label} 到期，可以聽日開頭就處理")

    return sugg[:4]


def _compose_morning(events: list[dict], tasks: list[dict], now: datetime) -> str:
    lines: list[str] = ["🤖 [AI 助理] 早安 Briefing", ""]

    # Today's events (filtered by caller)
    if events:
        lines.append("📅 今日行程：")
        for e in events[:4]:
            start = _parse_dt(e.get("start"))
            t = start.strftime("%H:%M") if start else "--:--"
            title = e.get("title") or e.get("summary") or "Event"
            loc = f" ({e.get('location')})" if e.get("location") else ""
            lines.append(f"• {t} {title}{loc}")
        lines.append(f"📎 AI 會議準備卡：{_deep_link('m', str(events[0].get('id')))}")
        lines.append("")

    # Deadlines: overdue first, then due today — 一行一項，無 per-task link
    if tasks:
        lines.append(f"⏳ 未完成 · {len(tasks[:10])} 項")
        for t in tasks[:10]:
            tag = _due_tag(t, now)
            suffix = f" — {tag}" if tag else ""
            lines.append(f"• {_task_emoji(t.get('title', ''))} {t.get('title', '')}{suffix}")
        lines.append("")
        sugg = _compose_suggestions(tasks, [], now, horizon_label="今日")
        if sugg:
            lines.append("📌 今日建議")
            lines.extend(f"• {s}" for s in sugg)
            lines.append("")

    lines.append(f"🌐 完整簡報：{_deep_link('dashboard')}")
    return "\n".join(lines)


def _compose_noon(
    soon_events: list[dict],
    events: list[dict],
    tasks: list[dict],
    quick_wins: list[dict],
    now: datetime,
) -> str:
    """Noon slot — 1h-soon alert + afternoon focus + quick-win cleanup (Phase D)."""
    lines: list[str] = ["🤖 [AI 助理] 午間 Briefing", ""]

    # ⏰ 1-hour-soon meeting alert — 突發預警, 置頂
    if soon_events:
        lines.append("⏰ 1 小時內會議：")
        for e in soon_events[:3]:
            start = _parse_dt(e.get("start"))
            t = start.strftime("%H:%M") if start else "--:--"
            title = e.get("title") or e.get("summary") or "Event"
            loc = f" ({e.get('location')})" if e.get("location") else ""
            lines.append(f"• {t} {title}{loc}")
            lines.append(f"📎 準備卡：{_deep_link('m', str(e.get('id')))}")
        lines.append("")

    # Remaining events this afternoon (excluding soon ones)
    if events:
        lines.append("🌤 下午行程：")
        for e in events[:4]:
            start = _parse_dt(e.get("start"))
            t = start.strftime("%H:%M") if start else "--:--"
            title = e.get("title") or e.get("summary") or "Event"
            loc = f" ({e.get('location')})" if e.get("location") else ""
            lines.append(f"• {t} {title}{loc}")
        lines.append("")

    # Pending deadlines due today — 一行一項
    if tasks:
        lines.append(f"⏳ 今日到期未完成 · {len(tasks[:8])} 項")
        for t in tasks[:8]:
            tag = _due_tag(t, now)
            suffix = f" — {tag}" if tag else ""
            lines.append(f"• {_task_emoji(t.get('title', ''))} {t.get('title', '')}{suffix}")
        lines.append("")

    # Quick-wins — 微型任務清理 (Phase D)
    if quick_wins:
        lines.append(f"⚡ 順手清 · {len(quick_wins[:5])} 項")
        for t in quick_wins[:5]:
            lines.append(f"• {_task_emoji(t.get('title', ''))} {t.get('title', '')}")
        lines.append("")

    if not (soon_events or events or tasks or quick_wins):
        lines.append("✅ 下午無會議、無到期死線，專心處理手上工作！")

    lines.append(f"🌐 完整簡報：{_deep_link('dashboard')}")
    return "\n".join(lines)


def _compose_evening(
    now: datetime,
    done_tasks: list[dict],
    remaining: list[dict],
    today_events: list[dict],
    gap_events: list[dict],
    rollover_count: int,
    tomorrow_events: list[dict],
    tomorrow_tasks: list[dict],
) -> str:
    """Evening slot — wrap-up review + gap alert + auto-rollover + tomorrow preview (Phase D)."""
    lines: list[str] = ["🤖 [AI 助理] 傍晚 Briefing", ""]

    # ✅ 今日完成 — 逐項列出（冇就一句）
    lines.append("✅ 今日完成")
    if done_tasks:
        for t in done_tasks[:8]:
            lines.append(f"• {_task_emoji(t.get('title', ''))} {t.get('title', '')}")
    else:
        lines.append("• 今日暫無 task 標記完成")
    lines.append("")

    if rollover_count:
        lines.append(f"🔄 {rollover_count} 項到期任務已自動過渡至明日。")
        lines.append("")

    if gap_events:
        lines.append("⚠️ 開咗會未留紀錄：")
        for e in gap_events[:4]:
            start = _parse_dt(e.get("start"))
            t = start.strftime("%H:%M") if start else "--:--"
            title = e.get("title") or e.get("summary") or "Event"
            lines.append(f"• {t} {title}")
            lines.append(f"🎙 語音留底：{_deep_link('note', str(e.get('id')))}")
        lines.append("")

    # ⏳ 未完成 — 一行一項
    if remaining:
        lines.append(f"⏳ 未完成 · {len(remaining[:10])} 項")
        for t in remaining[:10]:
            tag = _due_tag(t, now)
            suffix = f" — {tag}" if tag else ""
            lines.append(f"• {_task_emoji(t.get('title', ''))} {t.get('title', '')}{suffix}")
        lines.append("")

    if tomorrow_events or tomorrow_tasks:
        lines.append("🔮 聽日預告：")
        for e in tomorrow_events[:4]:
            start = _parse_dt(e.get("start"))
            t = start.strftime("%H:%M") if start else "全天"
            title = e.get("title") or e.get("summary") or "Event"
            lines.append(f"• {t} {title}")
        if tomorrow_tasks:
            lines.append(f"• ⏰ {len(tomorrow_tasks)} 項任務到期")
        lines.append("")

    # 📌 聽日建議 — heuristic 排序 + 解釋
    sugg = _compose_suggestions(remaining, tomorrow_tasks, now, horizon_label="聽日")
    if sugg:
        lines.append("📌 聽日建議")
        lines.extend(f"• {s}" for s in sugg)
        lines.append("")

    lines.append(f"🌐 完整簡報：{_deep_link('dashboard')}")
    return "\n".join(lines)


# ── Endpoints ────────────────────────────────────────────────────────
@router.get("/im-push/prefs", response_model=PrefsResponse)
async def get_prefs(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Read delivery prefs; auto-create Default-ON row for connected channels."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    # channels actually connected
    wa = (
        await db.execute(
            select(WhatsAppMapping).where(
                WhatsAppMapping.tenant_id == tenant_id,
                WhatsAppMapping.user_id == user_id,
                WhatsAppMapping.status == "active",
            )
        )
    ).scalar_one_or_none()

    tg = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == user_id,
                TelegramBotMapping.status == "active",
            )
        )
    ).scalar_one_or_none()

    connected = ["whatsapp"] if wa else []
    connected += ["telegram"] if tg else []
    channels: dict[str, PrefItem] = {}

    for ch in connected:
        pref = (
            await db.execute(
                select(IMDeliveryPref).where(
                    IMDeliveryPref.tenant_id == tenant_id,
                    IMDeliveryPref.user_id == user_id,
                    IMDeliveryPref.channel == ch,
                )
            )
        ).scalar_one_or_none()
        if pref is None:
            pref = IMDeliveryPref(tenant_id=tenant_id, user_id=user_id, channel=ch)
            db.add(pref)
            await db.flush()
        channels[ch] = PrefItem(
            channel=pref.channel,
            enabled=pref.enabled,
            slots=pref.slots or dict(DEFAULT_SLOTS),
            weekend_mute=pref.weekend_mute,
            quiet_hours=pref.quiet_hours or {"start": "22:00", "end": "08:00"},
            tz=pref.tz,
        )
    await db.commit()
    return PrefsResponse(channels=channels)


@router.put("/im-push/prefs", response_model=PrefsResponse)
async def put_prefs(
    request: Request,
    body: PrefItem,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    pref = (
        await db.execute(
            select(IMDeliveryPref).where(
                IMDeliveryPref.tenant_id == tenant_id,
                IMDeliveryPref.user_id == user_id,
                IMDeliveryPref.channel == body.channel,
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = IMDeliveryPref(tenant_id=tenant_id, user_id=user_id, channel=body.channel)
        db.add(pref)

    pref.enabled = body.enabled
    pref.slots = {k: bool(v) for k, v in body.slots.items()}
    pref.weekend_mute = body.weekend_mute
    pref.quiet_hours = body.quiet_hours
    pref.tz = body.tz
    await db.commit()

    return await get_prefs(request, db)


@router.post("/im-push/test")
async def test_push(
    request: Request,
    body: TestPushRequest,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    channel = body.channel
    msg = (
        "🤖 [AI 助理] 測試推送成功！\n\n"
        "你已開啟 AI 每日簡報（早安 / 午間 / 傍晚）。\n"
        "你可以隨時在 CRM 設定 > AI 助理設定 > 通知與整合 調整時段或關閉。\n\n"
        f"🌐 進入 Dashboard：{_deep_link('dashboard')}"
    )

    if channel == "telegram":
        tg = (
            await db.execute(
                select(TelegramBotMapping).where(
                    TelegramBotMapping.tenant_id == tenant_id,
                    TelegramBotMapping.user_id == user_id,
                    TelegramBotMapping.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not tg:
            raise HTTPException(400, "Telegram not connected")
        cred = (
            await db.execute(
                select(ChannelCredential).where(
                    ChannelCredential.tenant_id == tenant_id,
                    ChannelCredential.user_id == user_id,
                    ChannelCredential.channel == "telegram",
                )
            )
        ).scalar_one_or_none()
        token = decrypt_secret(cred.access_token) if cred and cred.access_token else ""
        if not token:
            raise HTTPException(400, "Telegram bot token missing")
        result = await telegram_service.send_message(token, str(tg.chat_id), msg)
        if not result.get("ok"):
            raise HTTPException(502, f"Telegram delivery failed: {result.get('description', 'API error')}")
        return {"status": "sent", "detail": result}

    mapping = (
        await db.execute(
            select(WhatsAppMapping).where(
                WhatsAppMapping.tenant_id == tenant_id,
                WhatsAppMapping.user_id == user_id,
                WhatsAppMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not mapping:
        raise HTTPException(400, "WhatsApp not connected")

    msg = (
        "🤖 [AI 助理] 測試推送成功！\n\n"
        "你已開啟 AI 每日簡報（早安 / 午間 / 傍晚）。\n"
        "你可以隨時在 CRM 設定 > AI 助理設定 > 通知與整合 調整時段或關閉。\n\n"
        f"🌐 進入 Dashboard：{_deep_link('dashboard')}"
    )
    result = await whatsapp_service.send_text(mapping.wa_id, msg)
    if isinstance(result, dict) and result.get("error"):
        # Meta rejected the send (e.g. expired token / 24h window) — surface as failure
        err = str(result.get("error"))[:200]
        raise HTTPException(502, f"WhatsApp delivery failed: {err}")
    return {"status": "sent", "detail": result}


@router.post("/im-push/briefing")
async def run_briefing(
    request: Request,
    slot: str = "morning",
    content: str = "",
    db: AsyncSession = Depends(get_tenant_session),
):
    """Cron endpoint — compose + fan-out Tri-Daily Briefing for all opted-in users.

    Auth: Cron-Api-Key header (same pattern as /ai/daily-summary).
    `content` (optional): pre-generated message text from an external LLM
    pipeline (Hermes briefing_cache). When provided, it overrides the
    built-in composers — the gating logic (prefs enabled / slots /
    weekend_mute / quiet_hours / wa mapping) still applies.
    """
    cron_key = request.headers.get("Cron-Api-Key", "")
    expected = os.environ.get("NEXUS_CRON_API_KEY", "") or settings.cron_api_key
    if not expected or cron_key != expected:
        raise HTTPException(403, "Invalid or missing Cron-Api-Key")

    if slot not in SLOTS:
        raise HTTPException(400, f"slot must be one of {SLOTS}")

    now = _now_hkt()
    weekend = now.weekday() >= 5
    stats = {"attempted": 0, "sent": 0, "skipped": 0, "failed": 0}

    prefs = (
        await db.execute(
            select(IMDeliveryPref).where(
                IMDeliveryPref.channel == "whatsapp",
                IMDeliveryPref.enabled == True,  # noqa: E712
            )
        )
    ).scalars().all()

    for pref in prefs:
        slots = pref.slots or {}
        if not slots.get(slot):
            continue
        stats["attempted"] += 1

        # ── Skip logic: weekend mute / quiet hours ──
        if pref.weekend_mute and weekend:
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="skipped", reason="weekend_mute"))
            stats["skipped"] += 1
            continue
        if _in_quiet_hours(pref, now):
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="skipped", reason="quiet_hours"))
            stats["skipped"] += 1
            continue

        # ── Resolve wa_id ──
        mapping = (
            await db.execute(
                select(WhatsAppMapping).where(
                    WhatsAppMapping.tenant_id == pref.tenant_id,
                    WhatsAppMapping.user_id == pref.user_id,
                    WhatsAppMapping.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not mapping:
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="skipped", reason="no_mapping"))
            stats["skipped"] += 1
            continue

        # ── Build context + compose ──
        try:
            workspace_id = await _resolve_workspace(db, pref.tenant_id)
            ctx = _build_ctx(pref.tenant_id, pref.user_id, workspace_id)

            if content.strip():
                # External LLM-generated briefing (Hermes pipeline) — gating already passed above
                msg = content.strip()
            elif slot == "morning":
                events, tasks = await _compose_morning_data(ctx, db, now)
                msg = _compose_morning(events, tasks, now)
            elif slot == "noon":
                data = await _compose_noon_data(ctx, db, now)
                msg = _compose_noon(**data, now=now)
            elif slot == "evening":
                data = await _compose_evening_data(ctx, db, now)
                msg = _compose_evening(now, **data)
            else:
                db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="skipped", reason="slot_not_implemented"))
                stats["skipped"] += 1
                continue

            result = await whatsapp_service.send_text(mapping.wa_id, msg)
            ok = isinstance(result, dict) and result.get("messages")
            # Phase D — 24h-window expired (Meta error 131047 re-engagement) → template fallback
            if not ok and settings.whatsapp_template_name:
                err_text = str(result)
                if "131047" in err_text or "re-engagement" in err_text.lower():
                    tpl = await whatsapp_service.send_template(
                        str(mapping.wa_id),
                        settings.whatsapp_template_name,
                        params=[msg[:500]],
                    )
                    ok = isinstance(tpl, dict) and tpl.get("messages")
                    if ok:
                        result = tpl
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="sent" if ok else "failed", error="" if ok else str(result)[:300]))
            if ok:
                stats["sent"] += 1
                # In-app notification (bell sync) — title varies by slot
                slot_title = {"morning": "☀️ 早安 Briefing", "noon": "🌤 午間 Briefing", "evening": "🌆 傍晚 Briefing"}.get(slot, "AI Briefing")
                db.add(Notification(
                    tenant_id=pref.tenant_id,
                    user_id=pref.user_id,
                    title=slot_title,
                    body=msg.split("\n")[0] if msg else "",
                    priority="NORMAL",
                    status="UNREAD",
                    group_key=f"im_push:{slot}",
                    is_ai_generated=True,
                    source_module="im_push",
                ))
            else:
                stats["failed"] += 1
        except Exception as e:  # noqa: BLE001 — per-user isolation; one failure must not kill the fan-out
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="whatsapp", slot=slot, status="failed", error=str(e)[:300]))
            stats["failed"] += 1

    # ── Telegram fan-out (bound bots) ──
    tg_prefs = (
        await db.execute(
            select(IMDeliveryPref).where(
                IMDeliveryPref.channel == "telegram",
                IMDeliveryPref.enabled == True,  # noqa: E712
            )
        )
    ).scalars().all()

    for pref in tg_prefs:
        slots = pref.slots or {}
        if not slots.get(slot):
            continue
        stats["attempted"] += 1

        # ── Skip logic: weekend mute / quiet hours ──
        if pref.weekend_mute and weekend:
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="skipped", reason="weekend_mute"))
            stats["skipped"] += 1
            continue
        if _in_quiet_hours(pref, now):
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="skipped", reason="quiet_hours"))
            stats["skipped"] += 1
            continue

        # ── Resolve mapping + token ──
        tg = (
            await db.execute(
                select(TelegramBotMapping).where(
                    TelegramBotMapping.tenant_id == pref.tenant_id,
                    TelegramBotMapping.user_id == pref.user_id,
                    TelegramBotMapping.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not tg:
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="skipped", reason="no_mapping"))
            stats["skipped"] += 1
            continue
        cred = (
            await db.execute(
                select(ChannelCredential).where(
                    ChannelCredential.tenant_id == pref.tenant_id,
                    ChannelCredential.user_id == pref.user_id,
                    ChannelCredential.channel == "telegram",
                )
            )
        ).scalar_one_or_none()
        token = decrypt_secret(cred.access_token) if cred and cred.access_token else ""
        if not token:
            # Cron endpoint has no JWT → RLS GUCs unset → credential query returns
            # 0 rows even though the row exists. Fall back to mapping.bot_token
            # (same pattern as telegram_inbound._get_bot_token).
            token = str(tg.bot_token or "")
        if not token or token == "None":
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="skipped", reason="no_token"))
            stats["skipped"] += 1
            continue

        # ── Build context + compose (same compositors, HTML-safe) ──
        try:
            workspace_id = await _resolve_workspace(db, pref.tenant_id)
            ctx = _build_ctx(pref.tenant_id, pref.user_id, workspace_id)

            if content.strip():
                msg = content.strip()
            elif slot == "morning":
                events, tasks = await _compose_morning_data(ctx, db, now)
                msg = _compose_morning(events, tasks, now)
            elif slot == "noon":
                data = await _compose_noon_data(ctx, db, now)
                msg = _compose_noon(**data, now=now)
            else:
                data = await _compose_evening_data(ctx, db, now)
                msg = _compose_evening(now, **data)

            result = await telegram_service.send_message(token, str(tg.chat_id), msg)
            ok = isinstance(result, dict) and result.get("ok")
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="sent" if ok else "failed", error="" if ok else str(result)[:300]))
            if ok:
                stats["sent"] += 1
                slot_title = {"morning": "☀️ 早安 Briefing", "noon": "🌤 午間 Briefing", "evening": "🌆 傍晚 Briefing"}.get(slot, "AI Briefing")
                db.add(Notification(
                    tenant_id=pref.tenant_id,
                    user_id=pref.user_id,
                    title=slot_title,
                    body=msg.split("\n")[0] if msg else "",
                    priority="NORMAL",
                    status="UNREAD",
                    group_key=f"im_push:{slot}",
                    is_ai_generated=True,
                    source_module="im_push",
                ))
            else:
                stats["failed"] += 1
        except Exception as e:  # noqa: BLE001 — per-user isolation
            db.add(PushLog(tenant_id=pref.tenant_id, user_id=pref.user_id, channel="telegram", slot=slot, status="failed", error=str(e)[:300]))
            stats["failed"] += 1

    await db.commit()
    return {"slot": slot, "run_at": now.isoformat(), **stats}


async def _compose_morning_data(ctx: AISessionContext, db: AsyncSession, now: datetime) -> tuple[list[dict], list[dict]]:
    """Extract today's events + overdue/due-today tasks (morning slot)."""
    events: list[dict] = []
    try:
        evts = await _get_upcoming_events(ctx, {"days_ahead": 1, "limit": 20}, db)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        for e in evts:
            start = _parse_dt(e.get("start"))
            if start and today_start <= start < tomorrow:
                events.append(e)
        events.sort(key=lambda e: _parse_dt(e.get("start")) or now)
    except Exception:
        pass

    tasks: list[dict] = []
    try:
        rows = await _list_tasks(ctx, {"status": "pending", "limit": 50}, db)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        for t in rows:
            due = _parse_dt(t.get("due_date"))
            if due and due < tomorrow:  # overdue or due today
                tasks.append(t)
        # overdue first, then due-today, then by due date asc
        tasks.sort(key=lambda t: (_parse_dt(t.get("due_date")) or now).date() < now.date(), reverse=True)
        tasks.sort(key=lambda t: _parse_dt(t.get("due_date")) or now)
    except Exception:
        pass

    return events, tasks


async def _compose_noon_data(ctx: AISessionContext, db: AsyncSession, now: datetime) -> dict:
    """Noon slot data — 1h-soon meetings + remaining events, due-today tasks, quick-wins.

    Phase D (2026-08-06): split events into soon (start within 60min — 突發預警)
    vs. rest-of-day; tasks into due-today (deadlines) vs. quick-wins (low priority
    or no due date — 微型任務清理).
    """
    soon_events: list[dict] = []
    events: list[dict] = []
    try:
        evts = await _get_upcoming_events(ctx, {"days_ahead": 1, "limit": 20}, db)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        soon_cutoff = now + timedelta(minutes=60)
        for e in evts:
            start = _parse_dt(e.get("start"))
            if start and today_start <= start < tomorrow and start >= now:
                (soon_events if start <= soon_cutoff else events).append(e)
        soon_events.sort(key=lambda e: _parse_dt(e.get("start")) or now)
        events.sort(key=lambda e: _parse_dt(e.get("start")) or now)
    except Exception:
        pass

    tasks: list[dict] = []
    quick_wins: list[dict] = []
    try:
        rows = await _list_tasks(ctx, {"status": "pending", "limit": 100}, db)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        for t in rows:
            due = _parse_dt(t.get("due_date"))
            if due and today_start <= due < tomorrow:
                tasks.append(t)
            elif not due or str(t.get("priority", "")).lower() in ("low", "lowest"):
                # quick-win: 冇死線 或 low priority — 細任務
                quick_wins.append(t)
        tasks.sort(key=lambda t: _parse_dt(t.get("due_date")) or now)
        quick_wins.sort(key=lambda t: t.get("title", ""))
    except Exception:
        pass

    return {
        "soon_events": soon_events,
        "events": events,
        "tasks": tasks,
        "quick_wins": quick_wins,
    }


async def _rollover_due_today(ctx: AISessionContext, db: AsyncSession, now: datetime) -> int:
    """Phase D — push today's unfinished due-today tasks to tomorrow (自動過渡).

    Only touches tasks whose due_date == today (HKT). Overdue stays put —
    the user must consciously deal with those. Returns how many rolled over.
    """
    from sqlalchemy import update as sa_update
    from app.models.crm import Task as TaskModel

    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)
    try:
        rows = await _list_tasks(ctx, {"status": "pending", "limit": 200}, db)
        ids = []
        for t in rows:
            due = _parse_dt(t.get("due_date"))
            if due and due.date() == today_date:
                ids.append(t["id"])
        if not ids:
            return 0
        await db.execute(
            sa_update(TaskModel)
            .where(TaskModel.id.in_(ids), TaskModel.tenant_id == ctx.tenant_id)
            .values(due_date=tomorrow_date)
        )
        return len(ids)
    except Exception:
        return 0


async def _compose_evening_data(ctx: AISessionContext, db: AsyncSession, now: datetime) -> dict:
    """Evening slot data — completed count, remaining overdue/tomorrow, tomorrow preview.

    Phase D (2026-08-06): + gap detection — today's meetings with no matching
    touchpoint logged → 開咗會冇留底 提醒. Match = same-day touchpoint whose title
    shares any token (≥3 chars) with the event title.
    """
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    day_after = tomorrow_start + timedelta(days=1)

    # Phase D — 今日到期未完成 → 自動過渡明日
    rollover_count = await _rollover_due_today(ctx, db, now)

    done_tasks: list[dict] = []
    remaining: list[dict] = []
    tomorrow_tasks: list[dict] = []
    try:
        done_rows = await _list_tasks(ctx, {"status": "completed", "limit": 100}, db)
        # completed today (updated_at proxy — no completed_at column on Task)
        for t in done_rows:
            upd = _parse_dt(t.get("updated_at"))
            if upd and upd >= today_start:
                done_tasks.append(t)
        done_tasks.sort(key=lambda t: _parse_dt(t.get("updated_at")) or now, reverse=True)

        pending = await _list_tasks(ctx, {"status": "pending", "limit": 100}, db)
        for t in pending:
            due = _parse_dt(t.get("due_date"))
            if due and due < tomorrow_start:
                remaining.append(t)
            elif due and tomorrow_start <= due < day_after:
                tomorrow_tasks.append(t)
        remaining.sort(key=lambda t: _parse_dt(t.get("due_date")) or now)
        tomorrow_tasks.sort(key=lambda t: _parse_dt(t.get("due_date")) or now)
    except Exception:
        pass

    today_events: list[dict] = []
    tomorrow_events: list[dict] = []
    try:
        evts = await _get_upcoming_events(ctx, {"days_ahead": 2, "limit": 30}, db)
        for e in evts:
            start = _parse_dt(e.get("start"))
            if start and today_start <= start < tomorrow_start:
                today_events.append(e)
            elif start and tomorrow_start <= start < day_after:
                tomorrow_events.append(e)
        today_events.sort(key=lambda e: _parse_dt(e.get("start")) or now)
        tomorrow_events.sort(key=lambda e: _parse_dt(e.get("start")) or now)
    except Exception:
        pass

    # ── Gap detection: today's meetings vs. logged touchpoints ──
    gap_events: list[dict] = []
    try:
        tps = await _list_touchpoints(ctx, {"limit": 200}, db)
        today_tp_titles = []
        for tp in tps:
            tp_date = _parse_dt(tp.get("date"))
            if tp_date and today_start <= tp_date < tomorrow_start:
                today_tp_titles.append((tp.get("title") or "").lower())
        for e in today_events:
            title = (e.get("title") or e.get("summary") or "").strip()
            if not title:
                continue
            tokens = [tok for tok in re.split(r"[\s\-,:：/]+", title.lower()) if len(tok) >= 3]
            if not tokens:
                continue
            # matched if ANY token appears in a same-day touchpoint title
            matched = any(
                tok in tp_title for tp_title in today_tp_titles for tok in tokens
            )
            if not matched:
                gap_events.append(e)
    except Exception:
        pass

    return {
        "done_tasks": done_tasks,
        "remaining": remaining,
        "today_events": today_events,
        "gap_events": gap_events,
        "rollover_count": rollover_count,
        "tomorrow_events": tomorrow_events,
        "tomorrow_tasks": tomorrow_tasks,
    }

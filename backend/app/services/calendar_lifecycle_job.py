"""Calendar lifecycle job — per-minute cron dispatching event reminders.

P1 (2026-09-09): T-60 basic reminder across channels (Web Portal + Telegram +
WhatsApp). P2 will add the T-15 AI briefing, P3 the T+30 touchpoint follow-up.

Design (docs/calendar-crm-integration-design-v3-2026-09-09.md §11):
- Event source of truth = nexus_crm.project_calendar_events (per-event columns
  reminder_t60_sent_at / reminder_t15_sent_at / followup_status ARE the state
  machine — migration 010). No separate table needed.
- Channel delivery pattern mirrors briefing_scheduler._push_telegram /
  _push_whatsapp (RLS GUCs must be re-set per member; credential decrypt with
  plaintext fallback). In-app notification via notification_service.notify().
- Idempotency: tick only claims events with reminder_t60_sent_at IS NULL inside
  the T-60 window; flag is set after dispatch. Cron overlap can't double-send.

Run every minute via crontab:
    * * * * * cd <repo>/backend && venv/bin/python -m app.services.calendar_lifecycle_job >> /tmp/calendar_lifecycle_cron.log 2>&1
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import async_session  # noqa: E402

T60_WINDOW_MIN = 60  # send when event starts within this many minutes


def _now_hkt() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_hm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%H:%M")


_EVENT_TYPE_LABEL = {
    "milestone": "里程碑",
    "task": "任務",
    "meeting": "會議",
    "reminder": "提醒",
}


def _compose_reminder(ev) -> str:
    label = _EVENT_TYPE_LABEL.get((ev.event_type or ""), ev.event_type or "活動")
    lines = [f"📅 1 小時後：{ev.title}", f"🕐 {_fmt_hm(ev.start)} – {_fmt_hm(ev.end)}（{label}）"]
    if ev.location:
        lines.append(f"📍 {ev.location}")
    return "\n".join(lines)


async def _push_channel(db, tenant_id, user_id, channel: str, body: str) -> str:
    """Best-effort single-channel push. Returns 'sent'|'skipped'|'failed'.

    Telegram: active TelegramBotMapping + decrypt credential (plaintext
    fallback) → telegram_service.send_message.
    WhatsApp: active WhatsAppMapping → whatsapp_service.send_text.
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
            {"t": str(tenant_id), "u": str(user_id)},
        )
    except Exception:
        pass

    if channel == "telegram":
        from app.services import telegram_service
        from app.services.secret_crypto import decrypt_secret
        from sqlalchemy import select
        from app.models.telegram_bot import TelegramBotMapping
        from app.models.ai.secretary_settings import ChannelCredential

        mapping = (
            await db.execute(
                select(TelegramBotMapping).where(
                    TelegramBotMapping.tenant_id == tenant_id,
                    TelegramBotMapping.user_id == user_id,
                    TelegramBotMapping.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not mapping or not mapping.chat_id:
            return "skipped"
        # Prefer the encrypted ChannelCredential secret; fall back to the
        # mapping's plaintext token (same pattern as briefing_scheduler).
        cred = (
            await db.execute(
                select(ChannelCredential).where(
                    ChannelCredential.tenant_id == tenant_id,
                    ChannelCredential.user_id == user_id,
                    ChannelCredential.channel == "telegram",
                )
            )
        ).scalar_one_or_none()
        token = ""
        try:
            token = decrypt_secret(cred.access_token) if cred and cred.access_token else ""
        except Exception:
            token = ""
        if not token:
            token = str(mapping.bot_token or "")
            if token == "None":
                token = ""
        if not token:
            return "skipped"
        try:
            res = await telegram_service.send_message(token, str(mapping.chat_id), body)
            return "sent" if (res or {}).get("ok") else "failed"
        except Exception:
            return "failed"

    if channel == "whatsapp":
        from app.models.whatsapp import WhatsAppMapping
        from app.services import whatsapp_service
        from sqlalchemy import select

        mapping = (
            await db.execute(
                select(WhatsAppMapping).where(
                    WhatsAppMapping.tenant_id == tenant_id,
                    WhatsAppMapping.user_id == user_id,
                    WhatsAppMapping.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not mapping or not getattr(mapping, "wa_id", None):
            return "skipped"
        try:
            result = await whatsapp_service.send_text(mapping.wa_id, body)
            ok = isinstance(result, dict) and result.get("messages")
            return "sent" if ok else "failed"
        except Exception:
            return "failed"

    return "skipped"


async def _inapp_notify(db, tenant_id, user_id, ev, body: str, title: str | None = None) -> bool:
    """In-app notification (web portal) — always attempted first (P1)."""
    try:
        from app.services import notification_service

        n = await notification_service.notify(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            module="calendar",
            title=title or f"📅 1 小時後：{ev.title}",
            body=body,
            priority="NORMAL",
            action_url="/calendar",
            source_record_type="project_calendar_event",
            source_record_id=ev.id,
            is_ai_generated=False,
        )
        return n is not None
    except Exception:
        return False


async def _channel_enabled(db, tenant_id, user_id, channel: str) -> bool:
    """IMDeliveryPref enabled (default-ON when bound). Missing row = allowed."""
    try:
        from sqlalchemy import select
        from app.models.im_push import IMDeliveryPref

        pref = (
            await db.execute(
                select(IMDeliveryPref).where(
                    IMDeliveryPref.tenant_id == tenant_id,
                    IMDeliveryPref.user_id == user_id,
                    IMDeliveryPref.channel == channel,
                )
            )
        ).scalar_one_or_none()
        return pref is None or pref.enabled is not False
    except Exception:
        return True


async def run(dry_run: bool = False) -> dict:
    now = _utcnow()
    stats = {"scanned": 0, "due": 0, "sent": 0, "skipped": 0, "failed": 0, "details": []}
    async with async_session() as db:
        members = (
            await db.execute(
                text("SELECT tenant_id, user_id FROM nexus_auth.nexus_auth_tenant_members")
            )
        ).fetchall()
        for tenant_id, user_id in members:
            await db.execute(
                text(
                    "SELECT set_config('app.tenant_id', :tid, true), "
                    "set_config('app.user_id', :uid, true)"
                ),
                {"tid": str(tenant_id), "uid": str(user_id)},
            )
            # T-60 due: starts within the next 60 minutes, not yet reminded,
            # not all-day (no concrete time), owned by this user.
            rows = (
                await db.execute(
                    text(
                        "SELECT id, title, event_type, start, \"end\", location, "
                        "       reminder_t60_sent_at, reminder_t15_sent_at, project_id "
                        "FROM nexus_crm.project_calendar_events "
                        "WHERE owner_user_id = :uid "
                        "  AND is_all_day = false "
                        "  AND (reminder_t60_sent_at IS NULL OR reminder_t15_sent_at IS NULL) "
                        "  AND start > :now AND start <= :window "
                        "ORDER BY start LIMIT 20"
                    ),
                    {"uid": str(user_id), "now": now, "window": now + timedelta(minutes=T60_WINDOW_MIN)},
                )
            ).fetchall()
            stats["scanned"] += 1
            for row in rows:
                ev = type("E", (), {
                    "id": row[0], "title": row[1], "event_type": row[2],
                    "start": row[3], "end": row[4], "location": row[5],
                    "t60": row[6], "t15": row[7], "project_id": row[8],
                })()
                # ── T-60 basic reminder（P1）──
                if ev.t60 is None:
                    stats["due"] += 1
                    body = _compose_reminder(ev)
                    if dry_run:
                        stats["details"].append(f"{str(user_id)[:8]} due T-60: {ev.title}")
                        stats["sent"] += 1
                    else:
                        inapp_ok = await _inapp_notify(db, tenant_id, user_id, ev, body)
                        tg_result = "skipped"
                        if await _channel_enabled(db, tenant_id, user_id, "telegram"):
                            tg_result = await _push_channel(db, tenant_id, user_id, "telegram", body)
                        if inapp_ok or tg_result == "sent":
                            await db.execute(
                                text(
                                    "UPDATE nexus_crm.project_calendar_events "
                                    "SET reminder_t60_sent_at = :ts WHERE id = :eid"
                                ),
                                {"ts": _utcnow(), "eid": ev.id},
                            )
                            stats["sent"] += 1
                            stats["details"].append(
                                f"{str(user_id)[:8]} T-60 sent: {ev.title} (inapp={inapp_ok} tg={tg_result})"
                            )
                        else:
                            stats["failed"] += 1
                            stats["details"].append(f"{str(user_id)[:8]} T-60 NO-CHANNEL: {ev.title}")
                # ── T-15 AI briefing（P2）— 只喺 event 進入 15 分鐘窗口先 dispatch ──
                if ev.t15 is None and ev.start <= now + timedelta(minutes=15):
                    stats["due"] += 1
                    if dry_run:
                        stats["details"].append(f"{str(user_id)[:8]} due T-15: {ev.title}")
                        stats["sent"] += 1
                    else:
                        try:
                            from app.services.calendar_briefing import dispatch_t15

                            res = await dispatch_t15(db, tenant_id, user_id, ev)
                            await db.execute(
                                text(
                                    "UPDATE nexus_crm.project_calendar_events "
                                    "SET reminder_t15_sent_at = :ts WHERE id = :eid"
                                ),
                                {"ts": _utcnow(), "eid": ev.id},
                            )
                            stats["sent"] += 1
                            stats["details"].append(
                                f"{str(user_id)[:8]} T-15 sent: {ev.title} "
                                f"(conf={res.get('confidence')} low={res.get('low')} ch={res.get('channels')})"
                            )
                        except Exception as e:  # noqa: BLE001 — briefing failure must not block the tick
                            stats["failed"] += 1
                            stats["details"].append(f"{str(user_id)[:8]} T-15 ERR: {type(e).__name__}: {str(e)[:120]}")
                            await db.execute(
                                text(
                                    "UPDATE nexus_crm.project_calendar_events "
                                    "SET reminder_t15_sent_at = :ts WHERE id = :eid"
                                ),
                                {"ts": _utcnow(), "eid": ev.id},  # 唔好阻下次 — 失敗都標記，下次 event 再試
                            )
            # ── T+30 touchpoint follow-up（P3a）— per-member scan（同 GUC scope）──
            try:
                from app.services.calendar_followup import ask_followup, scan_followups

                due_fps = await scan_followups(db, tenant_id, user_id, now)
                for fp_ev in due_fps:
                    stats["due"] += 1
                    if dry_run:
                        stats["details"].append(f"{str(user_id)[:8]} due T+30: {fp_ev.title}")
                        stats["sent"] += 1
                        continue
                    try:
                        res = await ask_followup(db, tenant_id, user_id, fp_ev)
                        if res.get("asked"):
                            stats["sent"] += 1
                            stats["details"].append(
                                f"{str(user_id)[:8]} T+30 asked: {fp_ev.title} (ch={res.get('channels')})"
                            )
                        else:
                            stats["details"].append(
                                f"{str(user_id)[:8]} T+30 silent: {fp_ev.title} ({res.get('reason')})"
                            )
                    except Exception as e:  # noqa: BLE001 — follow-up failure must not block the tick
                        stats["failed"] += 1
                        stats["details"].append(f"{str(user_id)[:8]} T+30 ERR: {type(e).__name__}: {str(e)[:120]}")
            except Exception as e:  # noqa: BLE001
                stats["details"].append(f"T+30 module load ERR: {type(e).__name__}: {str(e)[:100]}")
        await db.commit()
    return stats


def main() -> None:
    # CLI/cron context 冇 systemd EnvironmentFile — 手動由 settings 補 DEEPSEEK
    # key 入 env（deepseek provider 直接 os.environ.get("DEEPSEEK_API_KEY")）
    import os

    from app.config import settings

    if settings.deepseek_api_key and not os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key

    dry = "--dry-run" in sys.argv
    stats = asyncio.run(run(dry_run=dry))
    print(f"calendar_lifecycle {'(DRY)' if dry else ''}: {stats['scanned']} members, "
          f"{stats['due']} due, {stats['sent']} sent, {stats['skipped']} skipped, {stats['failed']} failed")
    for d in stats["details"][:30]:
        print(" ", d)


if __name__ == "__main__":
    main()

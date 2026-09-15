"""
Telegram integration router — bot binding, connection status, webhooks.

SOC 2 COMPLIANCE:
  - CC6.1 (Access Control): All auth endpoints use get_tenant_session + JWT
  - CC6.6 (Encryption): Cloudflare TLS for all external traffic
  - CC6.7 (At Rest): Bot token stored in nexus_ai.ai_channel_credentials
    (ChannelCredential, encrypted at app level) — NOT plaintext in mapping.
  - CC7.2 (Audit): Webhook deliveries logged to /tmp/telegram_webhook.log

Design: docs/design-im-push-module.md §4 endpoint table.
  POST /telegram/bind       — user provides bot_token + chat_id → getMe() validate
  GET  /telegram/status     — connection status
  POST /telegram/disconnect — unbind
  POST /telegram/webhook    — (public) Telegram Bot update receiver (reserved)
"""
import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_tenant_session
from app.models.telegram_bot import TelegramBotMapping
from app.models.ai.secretary_settings import SecretarySettings, ChannelCredential, DEFAULT_CHANNELS
from app.models.integration import Integration
from app.routers.crm_integrations import _tid, _uid, PROVIDER_DISPLAY
from app.services import telegram_service
from app.services.secret_crypto import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/v1")


# ── Schemas ──────────────────────────────────────────────────────────
class TelegramBindRequest(BaseModel):
    bot_token: str    # from @BotFather
    chat_id: str      # the chat the user wants deliveries in (Terrence: "bot id 等資料")


class TelegramVerifyTokenRequest(BaseModel):
    bot_token: str    # from @BotFather


class TelegramTestChatRequest(BaseModel):
    bot_token: str    # from @BotFather
    chat_id: str      # 用戶嘅 chat id（要驗證）


# ── AUTH: Test-send to a chat id (wizard step 2 確認 — 唔 store) ──────

@router.post("/telegram/test-chat")
async def test_telegram_chat(body: TelegramTestChatRequest):
    """第二次確認：send 測試訊息去 chat_id — 用戶收到 = chat id 正確。

    2026-09-09 wizard：AI Apps 連接兩步驗證 — token 驗證後，入 user id 再
    send「🔔」測試訊息，用戶喺 Telegram 見到先撳完成（bind）。
    """
    bot_token = body.bot_token.strip()
    chat_id = body.chat_id.strip()
    if not bot_token or not chat_id:
        raise HTTPException(400, "bot_token and chat_id are required")
    try:
        res = await telegram_service.send_message(
            bot_token,
            chat_id,
            "🔔 測試訊息 — 你嘅 User ID 正確！\n而家可以返去 CRM 撳「完成建立連接」。",
        )
    except Exception as e:
        raise HTTPException(400, f"Send failed — chat_id 可能唔啱: {e}")
    if not (res or {}).get("ok"):
        err = (res or {}).get("error") or (res or {}).get("description") or "unknown"
        raise HTTPException(400, f"Send failed — chat_id 可能唔啱: {err}")
    return {"status": "sent", "chat_id": chat_id}


# ── AUTH: Verify bot token (wizard step 1 — 唔 store，淨驗證) ─────────

@router.post("/telegram/verify-token")
async def verify_telegram_token(body: TelegramVerifyTokenRequest):
    """第一步確認：getMe() 驗證 bot token，返回 bot 資料（唔寫入 DB）。

    2026-09-09 wizard：AI Apps 連接改兩步 — 先驗 token（用戶見到自己隻 bot
    先安心），下一步先入 user id。
    """
    bot_token = body.bot_token.strip()
    if not bot_token:
        raise HTTPException(400, "bot_token is required")
    info = await telegram_service.get_me(bot_token)
    if not info.get("ok"):
        raise HTTPException(400, f"Telegram bot token invalid: {info.get('error')}")
    bot = info.get("bot", {})
    return {
        "status": "verified",
        "bot_username": bot.get("username") or "",
        "bot_name": bot.get("first_name") or "",
        "bot_id": bot.get("id"),
    }


# ── AUTH: Bind Telegram bot ──────────────────────────────────────────


@router.post("/telegram/bind")
async def bind_telegram(
    body: TelegramBindRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Validate the user's bot token with Telegram getMe(), then store the
    binding so the bot can push messages to the given chat_id.
    Body: { "bot_token": "...", "chat_id": "123456" }
    """
    bot_token = body.bot_token.strip()
    chat_id = body.chat_id.strip()
    if not bot_token or not chat_id:
        raise HTTPException(400, "bot_token and chat_id are required")

    # 🛡️ Validate token against Telegram BEFORE storing anything.
    info = await telegram_service.get_me(bot_token)
    if not info.get("ok"):
        raise HTTPException(400, f"Telegram bot token invalid: {info.get('error')}")

    bot = info.get("bot", {})
    bot_username = bot.get("username") or ""

    tenant_id = _tid(request)
    user_id = _uid(request)

    # ── Store bot token in the secret store (ChannelCredential) ──
    cred = (
        await db.execute(
            select(ChannelCredential).where(
                ChannelCredential.tenant_id == tenant_id,
                ChannelCredential.user_id == user_id,
                ChannelCredential.channel == "telegram",
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        cred = ChannelCredential(
            tenant_id=tenant_id, user_id=user_id, channel="telegram"
        )
        db.add(cred)
    cred.access_token = encrypt_secret(bot_token)  # AES-256-GCM at rest
    cred.external_id = chat_id
    cred.connected_at = datetime.now(timezone.utc)
    cred.revoked_at = None

    # ── Upsert mapping (connection record) ──
    mapping = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if mapping is None:
        mapping = TelegramBotMapping(
            tenant_id=tenant_id,
            user_id=user_id,
            bot_username=bot_username,
            bot_token=bot_token,  # opaque reference; secret lives in ChannelCredential
            chat_id=chat_id,
            status="active",
            config={"bot_id": bot.get("id"), "token_validated_at": datetime.now(timezone.utc).isoformat()},
        )
        db.add(mapping)
    else:
        mapping.bot_username = bot_username
        mapping.bot_token = bot_token
        mapping.chat_id = chat_id
        mapping.status = "active"
        mapping.config = mapping.config or {}
        mapping.config.update({"bot_id": bot.get("id"), "token_validated_at": datetime.now(timezone.utc).isoformat()})
        mapping.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # ── Upsert into nexus_integrations so the Marketplace shows it ──
    integration = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.user_id == user_id,
                Integration.provider == "telegram",
            )
        )
    ).scalar_one_or_none()
    if integration:
        integration.status = "active"
        integration.config = {"bot_username": bot_username, "chat_id": chat_id}
        integration.metadata_ = {
            **(integration.metadata_ or {}),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        integration.updated_at = datetime.now(timezone.utc)
    else:
        db.add(Integration(
            tenant_id=tenant_id,
            user_id=user_id,
            provider="telegram",
            provider_display=PROVIDER_DISPLAY.get("telegram", "Telegram"),
            status="active",
            config={"bot_username": bot_username, "chat_id": chat_id},
            metadata_={"connected_at": datetime.now(timezone.utc).isoformat()},
        ))

    # ── Default-ON: enable AI briefing push for telegram (§2.1) ──
    from app.models.im_push import IMDeliveryPref
    pref = (
        await db.execute(
            select(IMDeliveryPref).where(
                IMDeliveryPref.tenant_id == tenant_id,
                IMDeliveryPref.user_id == user_id,
                IMDeliveryPref.channel == "telegram",
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        db.add(IMDeliveryPref(tenant_id=tenant_id, user_id=user_id, channel="telegram"))
    else:
        pref.enabled = True
    await db.flush()

    # ── Flip SecretarySettings.channels[telegram].connected = True ──
    await _set_channels(db, tenant_id, user_id, connected=True, enabled=True)

    await db.commit()

    # ── 2026-09-09: send success message to the user's bot chat ──
    # 之前 bind 淨返回 JSON — 用戶喺 Telegram 完全收唔到確認 → Caleb bug report。
    # Best-effort：send 失敗唔影響 bind 結果。
    try:
        await telegram_service.send_message(
            bot_token,
            chat_id,
            "✅ Telegram 已成功連接！\n"
            f"Bot：@{bot_username}\n"
            "你可以直接喺呢個 chat 同 AI 對話，例如：「今日有咩日程？」或者「建立一間公司叫 XXX」。",
        )
    except Exception:
        pass  # best-effort — bind 本身已成功

    return {
        "status": "connected",
        "bot_username": bot_username,
        "chat_id": chat_id,
    }


# ── AUTH: Get Telegram connection status ─────────────────────────────


@router.get("/telegram/status")
async def telegram_status(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get the current user's Telegram binding status."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    mapping = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == user_id,
                TelegramBotMapping.status == "active",
            )
        )
    ).scalar_one_or_none()

    if not mapping:
        return {"status": "disconnected", "bot_username": None, "chat_id": None}

    return {
        "status": "active",
        "bot_username": mapping.bot_username,
        "chat_id": str(mapping.chat_id),
        "connected_at": mapping.created_at.isoformat() if mapping.created_at else None,
    }


# ── AUTH: Disconnect Telegram ────────────────────────────────────────


@router.post("/telegram/disconnect")
async def disconnect_telegram(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Unbind Telegram bot from the current user's account."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    # Deactivate mapping
    mapping = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == user_id,
                TelegramBotMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    if mapping:
        mapping.status = "disconnected"
        mapping.updated_at = datetime.now(timezone.utc)

    # Revoke secret
    cred = (
        await db.execute(
            select(ChannelCredential).where(
                ChannelCredential.tenant_id == tenant_id,
                ChannelCredential.user_id == user_id,
                ChannelCredential.channel == "telegram",
            )
        )
    ).scalar_one_or_none()
    if cred:
        cred.revoked_at = datetime.now(timezone.utc)
        cred.access_token = ""

    # Deactivate integration
    integration = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.user_id == user_id,
                Integration.provider == "telegram",
            )
        )
    ).scalar_one_or_none()
    if integration:
        integration.status = "disconnected"
        integration.updated_at = datetime.now(timezone.utc)

    # Flip SecretarySettings.channels[telegram].connected = False
    await _set_channels(db, tenant_id, user_id, connected=False, enabled=False)

    await db.commit()
    return {"status": "disconnected"}


# ── PUBLIC: Webhook receiver (production — Telegram pushes updates here) ──


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Telegram pushes updates here when a webhook is registered (production mode).

    Fast-ACK pattern: validate secret token → parse body → hand off to a
    background task → return 200 immediately. Telegram retries on non-2xx,
    so we never do slow work (AI, DB writes, media download) inside this
    handler — that would cause duplicate deliveries.
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.tg_webhook_secret or secret != settings.tg_webhook_secret:
        return JSONResponse({"ok": False, "error": "invalid secret token"}, status_code=403)
    body = await request.body()
    try:
        data = json.loads(body) if body else {}
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    from datetime import datetime as _dt
    with open("/tmp/telegram_webhook.log", "a") as f:
        f.write(f"[{_dt.now().isoformat()}] update_id={data.get('update_id')}\n")
    # Durable queue: push to Redis (LPUSH), workers BRPOP. If a worker
    # crashes mid-processing the update stays queued — nothing is lost,
    # unlike in-process BackgroundTasks. 4 gunicorn workers × BRPOP =
    # natural parallel consumption, no duplicates.
    try:
        import redis.asyncio as redis_async
        _r = redis_async.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        await _r.lpush("tg:webhook:updates", json.dumps(data))
        await _r.aclose()
        return {"ok": True, "queued": True}
    except Exception:
        # Redis down → fall back to in-process background task (degraded,
        # not dead). Telegram retries on non-2xx, so never 5xx here.
        from app.services.telegram_inbound import handle_webhook_update
        background_tasks.add_task(handle_webhook_update, data)
        return {"ok": True, "queued": False}


# ── AUTH: Send test message ───────────────────────────────────────────


@router.post("/telegram/send")
async def send_telegram_message(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Send a test message to the user's bound Telegram chat."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    mapping = (
        await db.execute(
            select(TelegramBotMapping).where(
                TelegramBotMapping.tenant_id == tenant_id,
                TelegramBotMapping.user_id == user_id,
                TelegramBotMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not mapping:
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

    text = "🤖 [AI 助理] Telegram 測試推送成功！\n\n你已開啟 AI 每日簡報（早安 / 午間 / 傍晚）。"
    result = await telegram_service.send_message(token, str(mapping.chat_id), text)
    if not result.get("ok"):
        raise HTTPException(502, f"Telegram delivery failed: {result.get('description', 'API error')}")
    return {"status": "sent", "detail": result}


# ── INTERNAL HELPERS ─────────────────────────────────────────────────


async def _set_channels(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, *, connected: bool, enabled: bool
):
    """Flip SecretarySettings.channels[telegram] so the AI Apps UI stays in sync."""
    row = (
        await db.execute(
            select(SecretarySettings).where(
                SecretarySettings.tenant_id == tenant_id,
                SecretarySettings.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return
    channels = dict(row.channels or DEFAULT_CHANNELS)
    current = dict(channels.get("telegram", {}))
    current["connected"] = connected
    current["enabled"] = enabled
    channels["telegram"] = current
    row.channels = channels

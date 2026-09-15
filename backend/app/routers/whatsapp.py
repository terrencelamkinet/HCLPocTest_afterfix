"""
WhatsApp integration router — webhooks, account linking, message sending.

SOC 2 COMPLIANCE:
  - CC6.1 (Access Control): All auth endpoints use get_tenant_session + JWT
  - CC6.6 (Encryption): Cloudflare TLS for all external traffic
  - CC6.7 (At Rest): Phone numbers pending pgcrypto encryption
  - CC7.2 (Audit): Incoming webhooks logged to /tmp/whatsapp_webhook.log
  - Webhook endpoints are public (Meta calls them directly) but signature-verified.
  - All other endpoints require auth + tenant isolation.
"""
import uuid
from uuid import UUID
import os
import random
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session, async_session
from app.models.whatsapp import WhatsAppMapping, WhatsAppOTP
from app.models.integration import Integration
from app.routers.crm_integrations import _tid, _uid, PROVIDER_DISPLAY
from app.services import whatsapp_service
from app.services import namecard_im
from app.services.rate_limiter import check_otp_send, check_otp_verify, reset_rate_limit

router = APIRouter(prefix="/api/v1")

OTP_EXPIRY_MINUTES = 5

# ── NameCard pending state (per wa_id, module-level — single process) ──
_wa_pending: dict[str, str] = {}   # wa_id → pending image path awaiting 係/唔使
_wa_review: dict[str, str] = {}    # wa_id → pending review card_id awaiting 覆蓋/保留
_WA_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "namecards" / "wa_pending"
OTP_LENGTH = 6


# ─── PUBLIC: Webhook verification (GET) ──────────────────────────


@router.get("/whatsapp/webhook")
async def whatsapp_webhook_get(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    """Meta sends a GET request to verify the webhook endpoint."""
    is_valid, challenge = whatsapp_service.verify_webhook(
        hub_mode, hub_verify_token, hub_challenge
    )
    if is_valid:
        return int(hub_challenge) if hub_challenge.isdigit() else int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ─── PUBLIC: Receive inbound messages (POST) ─────────────────────


@router.post("/whatsapp/webhook")
async def whatsapp_webhook_post(request: Request):
    """Receive incoming WhatsApp messages and status updates from Meta."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not whatsapp_service.verify_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = json.loads(body)
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Handle status updates (delivery/read receipts)
            for status in value.get("statuses", []):
                await _handle_status_update(status)

            # Handle incoming messages
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            for msg in value.get("messages", []):
                await _handle_incoming_message(msg, phone_number_id)

    return {"status": "received"}


# ─── AUTH: Send OTP to start account linking ─────────────────────


@router.post("/whatsapp/send-otp")
async def send_otp(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Send OTP verification message to start WhatsApp binding.
    Body: { "phone": "+85200000000" }
    Returns OK once OTP is sent via WhatsApp.
    """
    body = await request.json()
    phone = body.get("phone", "").strip()
    if not phone:
        raise HTTPException(400, "phone is required")

    tenant_id = _tid(request)
    user_id = _uid(request)

    # 🛡️ Rate limit: prevent OTP flooding (3 req/min per phone)
    allowed, count, retry_after = check_otp_send(phone)
    if not allowed:
        raise HTTPException(
            429,
            f"Too many OTP requests. Try again in {retry_after} seconds.",
        )

    # 🛡️ Anti-enumeration: don't reveal if phone is already bound
    # Check not already bound
    q = select(WhatsAppMapping).where(
        WhatsAppMapping.phone_number == phone,
        WhatsAppMapping.status == "active",
    )
    existing = (await db.execute(q)).scalar_one_or_none()
    if existing:
        # Silently return "sent" — attacker can't distinguish existing vs new
        return {
            "status": "sent",
            "wa_id": phone,
            "expires_in": OTP_EXPIRY_MINUTES * 60,
            "_note": "Phone already bound",
        }

    # Generate OTP
    otp = str(random.randint(10 ** (OTP_LENGTH - 1), 10**OTP_LENGTH - 1))
    expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    otp_row = WhatsAppOTP(
        wa_id=phone,
        otp=otp,
        expires_at=expires,
    )
    db.add(otp_row)
    await db.flush()

    # Send via WhatsApp Cloud API
    result = await whatsapp_service.send_otp(phone, otp)

    response_data = {
        "status": "sent",
        "wa_id": phone,
        "expires_in": OTP_EXPIRY_MINUTES * 60,
    }

    # Testing mode: include OTP in response for debugging
    from app.config import settings
    if settings.debug:
        response_data["otp"] = otp
        response_data["_test_mode"] = True

    if result.get("error"):
        if settings.debug:
            response_data["status"] = "debug"
            response_data["wa_send_error"] = result.get("message", "API error")
            return response_data
        raise HTTPException(502, f"Failed to send OTP: {result.get('message', 'API error')}")

    return response_data


# ─── AUTH: Verify OTP and complete binding ────────────────────────


@router.post("/whatsapp/verify-otp")
async def verify_otp(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Verify OTP and bind WhatsApp number to the current user.
    Body: { "phone": "+85200000000", "otp": "482913" }
    """
    body = await request.json()
    phone = body.get("phone", "").strip()
    otp = body.get("otp", "").strip()

    if not phone or not otp:
        raise HTTPException(400, "phone and otp are required")

    tenant_id = _tid(request)
    user_id = _uid(request)

    # 🛡️ Rate limit: prevent OTP brute force (3 attempts/min per phone)
    allowed, count, retry_after = check_otp_verify(phone)
    if not allowed:
        raise HTTPException(
            429,
            f"Too many verification attempts. Try again in {retry_after} seconds.",
        )

    # Find valid OTP
    q = select(WhatsAppOTP).where(
        WhatsAppOTP.wa_id == phone,
        WhatsAppOTP.otp == otp,
        WhatsAppOTP.used == False,
        WhatsAppOTP.expires_at > datetime.now(timezone.utc),
    ).order_by(WhatsAppOTP.created_at.desc())
    otp_row = (await db.execute(q)).scalar_one_or_none()

    if not otp_row:
        raise HTTPException(400, "Invalid or expired OTP")

    # Mark OTP as used
    otp_row.used = True

    # Check if mapping exists — if so, reactivate
    q2 = select(WhatsAppMapping).where(
        WhatsAppMapping.phone_number == phone,
    )
    existing_map = (await db.execute(q2)).scalar_one_or_none()

    if existing_map:
        existing_map.wa_id = phone
        existing_map.phone_number = phone
        existing_map.status = "active"
        existing_map.tenant_id = tenant_id
        existing_map.user_id = user_id
        existing_map.updated_at = datetime.now(timezone.utc)
        mapping = existing_map
    else:
        mapping = WhatsAppMapping(
            tenant_id=tenant_id,
            user_id=user_id,
            wa_id=phone,
            phone_number=phone,
            status="active",
        )
        db.add(mapping)

    await db.flush()

    # Also upsert into nexus_integrations so the Marketplace shows it
    q3 = select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
        Integration.provider == "whatsapp",
    )
    existing_int = (await db.execute(q3)).scalar_one_or_none()

    if existing_int:
        existing_int.status = "active"
        existing_int.config = {"wa_id": phone, "phone_number": phone}
        existing_int.metadata_ = {
            **(existing_int.metadata_ or {}),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        existing_int.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(existing_int)
    else:
        integration = Integration(
            tenant_id=tenant_id,
            user_id=user_id,
            provider="whatsapp",
            provider_display=PROVIDER_DISPLAY.get("whatsapp", "WhatsApp"),
            status="active",
            config={"wa_id": phone, "phone_number": phone},
            metadata_={"connected_at": datetime.now(timezone.utc).isoformat()},
        )
        db.add(integration)
        await db.flush()
        await db.refresh(integration)

    # 🛡️ Reset rate limit on successful verification
    reset_rate_limit(f"otp_verify:{phone}")
    reset_rate_limit(f"otp_send:{phone}")

    # 📲 Default-ON: auto-enable AI Briefing push (frictionless onboarding, §2.1)
    from app.models.im_push import IMDeliveryPref
    pref = (
        await db.execute(
            select(IMDeliveryPref).where(
                IMDeliveryPref.tenant_id == tenant_id,
                IMDeliveryPref.user_id == user_id,
                IMDeliveryPref.channel == "whatsapp",
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        db.add(IMDeliveryPref(tenant_id=tenant_id, user_id=user_id, channel="whatsapp"))
    else:
        pref.enabled = True  # re-binding re-enables
    await db.flush()

    return {
        "status": "connected",
        "wa_id": phone,
        "phone_number": phone[-4:],  # last 4 digits for display
        "integration_id": str(integration.id),
    }


# ─── AUTH: Disconnect WhatsApp ────────────────────────────────────


@router.post("/whatsapp/disconnect")
async def disconnect_whatsapp(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Disconnect WhatsApp from the current user's account."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    # Deactivate mapping
    q = select(WhatsAppMapping).where(
        WhatsAppMapping.tenant_id == tenant_id,
        WhatsAppMapping.user_id == user_id,
        WhatsAppMapping.status == "active",
    )
    mapping = (await db.execute(q)).scalar_one_or_none()
    if mapping:
        mapping.status = "disconnected"
        mapping.updated_at = datetime.now(timezone.utc)

    # Deactivate integration
    q2 = select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
        Integration.provider == "whatsapp",
    )
    integration = (await db.execute(q2)).scalar_one_or_none()
    if integration:
        integration.status = "disconnected"
        integration.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return {"status": "disconnected"}


# ─── AUTH: Get WhatsApp connection status ─────────────────────────


@router.get("/whatsapp/status")
async def whatsapp_status(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get the current user's WhatsApp binding status."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(WhatsAppMapping).where(
        WhatsAppMapping.tenant_id == tenant_id,
        WhatsAppMapping.user_id == user_id,
        WhatsAppMapping.status == "active",
    )
    mapping = (await db.execute(q)).scalar_one_or_none()

    if not mapping:
        return {"status": "disconnected", "wa_id": None}

    return {
        "status": "active",
        "wa_id": mapping.wa_id,
        "phone_number": mapping.phone_number[-4:],
        "connected_at": mapping.created_at.isoformat() if mapping.created_at else None,
    }


# ─── AUTH: Send a message (via API) ────────────────────────────────


@router.post("/whatsapp/send")
async def send_whatsapp_message(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Send a text message to the user's bound WhatsApp.
    Body: { "text": "Hello!" }
    Only works within the 24h messaging window.
    For push beyond 24h, use /whatsapp/push.
    """
    body = await request.json()
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "text is required")

    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(WhatsAppMapping).where(
        WhatsAppMapping.tenant_id == tenant_id,
        WhatsAppMapping.user_id == user_id,
        WhatsAppMapping.status == "active",
    )
    mapping = (await db.execute(q)).scalar_one_or_none()
    if not mapping:
        raise HTTPException(400, "WhatsApp not connected")

    result = await whatsapp_service.send_text(mapping.wa_id, text)
    return result


# ─── AUTH: Push template notification ─────────────────────────────


@router.post("/whatsapp/push")
async def push_whatsapp_notification(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Send a template notification (works outside 24h window).
    Body: { "template": "order_update", "params": ["#10234", "shipped"] }
    """
    body = await request.json()
    template = body.get("template", "")
    params = body.get("params", [])
    lang = body.get("lang", "zh_HK")

    if not template:
        raise HTTPException(400, "template is required")

    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(WhatsAppMapping).where(
        WhatsAppMapping.tenant_id == tenant_id,
        WhatsAppMapping.user_id == user_id,
        WhatsAppMapping.status == "active",
    )
    mapping = (await db.execute(q)).scalar_one_or_none()
    if not mapping:
        raise HTTPException(400, "WhatsApp not connected")

    result = await whatsapp_service.send_template(mapping.wa_id, template, params, lang)
    return result


# ─── INTERNAL HELPERS ─────────────────────────────────────────────


async def _handle_incoming_message(msg: dict, phone_number_id: str):
    """Process an incoming WhatsApp message — namecard flow first, then AI bridge."""
    wa_id = msg.get("from", "")
    msg_type = msg.get("type", "text")
    text = ""
    if msg_type == "text":
        text = msg.get("text", {}).get("body", "")

    # ── Namecard image flow ──
    if msg_type == "image":
        media_id = (msg.get("image") or {}).get("id", "")
        if media_id:
            content, mime = await whatsapp_service.download_media(media_id)
            if content:
                reply = await _handle_wa_namecard_image(wa_id, content, mime)
                if reply:
                    await whatsapp_service.send_text(wa_id, reply)
        return  # image handled (silent if not a namecard)

    # ── Voice-note (audio) flow ── STT → feed transcript into text AI bridge ──
    if msg_type in ("audio", "voice"):
        media = msg.get(msg_type) or {}
        media_id = media.get("id", "")
        if media_id:
            content, mime = await whatsapp_service.download_media(media_id)
            if content:
                reply = await _handle_wa_voice(wa_id, content, mime)
                if reply:
                    await whatsapp_service.send_text(wa_id, reply)
        return

    # ── Namecard confirm flow (係/唔使 after a photo) ──
    if text:
        reply = await _handle_wa_namecard_text(wa_id, text)
        if reply is not None:
            await whatsapp_service.send_text(wa_id, reply)
            return

    if not text:
        return

    # Log incoming for debugging
    from datetime import datetime
    log_line = f"[{datetime.now().isoformat()}] wa_id={wa_id} text={text[:100]}\n"
    with open("/tmp/whatsapp_webhook.log", "a") as f:
        f.write(log_line)

    # Use AI bridge to process the message
    from app.services.whatsapp_ai_bridge import handle_whatsapp_message

    reply = await handle_whatsapp_message(wa_id, text)
    if reply:
        result = await whatsapp_service.send_text(wa_id, reply)
        if result.get("error"):
            with open("/tmp/whatsapp_webhook.log", "a") as f:
                f.write(f"[{datetime.now().isoformat()}] send error: {result.get('message')}\n")


async def _handle_wa_voice(wa_id: str, content: bytes, mime: str) -> str | None:
    """WhatsApp audio message → SiliconFlow STT → feed transcript into text bridge.

    Mirrors the Telegram voice path: the transcript is handled exactly like a
    typed message (CRM search, memory, tool drafts). Returns a zh-HK apology if
    transcription fails so the sender is never left in silence.
    """
    import tempfile
    from app.services.voice_stt import transcribe_audio

    # Resolve tenant/user (provider key scoping + central usage recording)
    tenant_id = user_id = None
    search_ids = [wa_id] + ([("+" + wa_id) if not wa_id.startswith("+") else wa_id[1:]])
    async with async_session() as db:
        for cand in search_ids:
            mapping = (
                await db.execute(
                    select(WhatsAppMapping).where(
                        WhatsAppMapping.wa_id == cand,
                        WhatsAppMapping.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if mapping:
                tenant_id, user_id = mapping.tenant_id, mapping.user_id
                break

    if "ogg" in mime or "opus" in mime:
        ext, ctype = ".ogg", "audio/ogg"
    elif "mp4" in mime or "m4a" in mime or "aac" in mime:
        ext, ctype = ".m4a", "audio/mp4"
    elif "mpeg" in mime or "mp3" in mime:
        ext, ctype = ".mp3", "audio/mpeg"
    else:
        ext, ctype = ".ogg", "audio/ogg"

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(content)
            tmp_path = f.name
        text = await transcribe_audio(
            tmp_path,
            tenant_id=tenant_id,
            user_id=user_id,
            filename=f"voice{ext}",
            content_type=ctype,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    if not text:
        return "😕 唔好意思，未能辨識呢段語音，請再錄一次或者用文字輸入。"
    from app.services.whatsapp_ai_bridge import handle_whatsapp_message

    return await handle_whatsapp_message(wa_id, text)


async def _handle_wa_namecard_image(wa_id: str, content: bytes, mime: str) -> str | None:
    """Detect namecard in a received image → store pending → ask to upload."""
    ext = ".jpg"
    if mime == "image/png":
        ext = ".png"
    elif mime == "image/webp":
        ext = ".webp"
    _WA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = _WA_UPLOAD_DIR / f"wa_{uuid.uuid4().hex}{ext}"
    path.write_bytes(content)

    det = namecard_im.run_script(["--detect", str(path)])
    if not det.get("is_namecard"):
        # Non-namecard photo → route to AI image analysis (normal request flow,
        # same as Telegram). Query mapping for usage tracking context.
        try:
            from app.services.telegram_inbound import _analyze_plain_image
            from sqlalchemy import select as _sa_select
            wa_map = None
            async with async_session() as _db:
                wa_map = (
                    await _db.execute(
                        _sa_select(WhatsAppMapping).where(
                            WhatsAppMapping.wa_id == wa_id,
                            WhatsAppMapping.status == "active",
                        ).limit(1)
                    )
                ).scalar_one_or_none()
            uid = getattr(wa_map, "user_id", None) if wa_map else None
            tid = getattr(wa_map, "tenant_id", None) if wa_map else None
            reply = await _analyze_plain_image(str(path), uid, tid)
        except Exception:
            reply = "收到圖片，但暫時無法分析內容。"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return reply

    # Friendlier preview: parse name + company
    preview = (det.get("ocr_preview") or "")[:80]
    try:
        from app.services.namecard_ocr import parse_namecard, ocr_image
        wa_usage: list = []  # core rule G08: central token collection
        full_txt = ocr_image(str(path), usage_out=wa_usage)
        parsed = parse_namecard(full_txt or preview)
        p_name = parsed.get("name") or ""
        p_company = parsed.get("company") or ""
        if p_name:
            preview = f"{p_name}" + (f" · {p_company}" if p_company else "")
        elif full_txt:
            preview = " ".join(full_txt.split())[:80]
        if wa_usage:
            try:
                from app.models.ai.usage import UsageEvent
                async with async_session() as _db:
                    for r in wa_usage:
                        _db.add(UsageEvent(
                            session_id=None,
                            user_id=uuid.uuid4(),  # KB-040：原為裸 uuid4()，冇 import → NameError
                            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                            provider=r.get("provider") or "siliconflow",
                            model=r.get("model") or "",
                            input_tokens=int(r.get("input_tokens") or 0),
                            output_tokens=int(r.get("output_tokens") or 0),
                            cost_estimate=float(r.get("cost_usd") or 0) if r.get("cost_usd") else None,
                            result_status="success",
                            module="namecard",
                            currency="USD",
                        ))
                    await _db.commit()
            except Exception:
                pass  # usage recording is best-effort
    except Exception:
        pass

    _wa_pending[wa_id] = str(path)
    return (
        f"📇 偵測到名片：{preview}\n\n"
        f"需要上載到名片庫嗎？（自動 OCR + 存入 CRM 聯絡人）\n"
        f"回覆「係」上載，或「唔使」取消"
    )


async def _handle_wa_namecard_text(wa_id: str, text: str) -> str | None:
    """Confirm (係/唔使) + review (覆蓋/保留) replies for WhatsApp."""
    # ── Review reply first (higher priority: 覆蓋/保留 are unambiguous) ──
    is_ow = namecard_im.match_intent(text, namecard_im.OVERWRITE_WORDS)
    is_kp = namecard_im.match_intent(text, namecard_im.KEEP_WORDS)
    if is_ow or is_kp:
        card_id = _wa_review.pop(wa_id, "")
        if card_id:
            action = "overwrite" if is_ow else "keep_both"
            res = namecard_im.run_script(["--resolve", card_id, action])
            return namecard_im.format_resolve_result(res, action)

    # ── Confirm reply (係/唔使) ──
    is_yes = namecard_im.match_intent(text, namecard_im.YES_WORDS)
    is_no = namecard_im.match_intent(text, namecard_im.NO_WORDS)
    if not is_yes and not is_no:
        return None  # normal message — AI bridge handles it

    path = _wa_pending.pop(wa_id, "")
    if is_no:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return "✅ 已取消，名片唔會上載。"
    if not path or not Path(path).is_file():
        return None  # no pending namecard — normal message

    res = namecard_im.run_script(["--upload", path])
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass

    msg, review_state = namecard_im.format_upload_result(res)
    if review_state.get("card_id"):
        _wa_review[wa_id] = review_state["card_id"]
    return msg


async def _handle_status_update(status_data: dict):
    """Track message delivery/read status."""
    wamid = status_data.get("id", "")
    status = status_data.get("status", "")
    # Phase 1: log only
    # Phase 2: store in message_log table

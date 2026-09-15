"""SiliconFlow speech-to-text (STT) helper — shared by IM bridges.

Telegram voice notes (.oga Opus) and WhatsApp audio messages are transcribed
through SiliconFlow's OpenAI-compatible ``/v1/audio/transcriptions`` endpoint
(``FunAudioLLM/SenseVoiceSmall``), then the transcript is fed into the normal
text chat pipeline so CRM search, memory and tool drafts all apply.

Design mirrors the vision path in
``telegram_inbound._analyze_plain_image``:
  - provider key via ``load_provider_key('siliconflow', tenant_id)`` (never hardcoded)
  - usage recorded centrally in ``nexus_ai.usage_events`` (best-effort)
  - graceful fallback: never raises, returns "" on any failure
"""
import logging
import os
from typing import Optional
from uuid import UUID

import httpx

log = logging.getLogger("voice_stt")

STT_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"

# Verified against GET /v1/models?sub_type=speech-to-text (2026-09-10):
#   FunAudioLLM/SenseVoiceSmall (primary), Qwen/Qwen3-ASR-1.7B (fallback)
STT_MODELS = ["FunAudioLLM/SenseVoiceSmall", "Qwen/Qwen3-ASR-1.7B"]


async def transcribe_audio(
    path: str,
    tenant_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    filename: str = "voice.ogg",
    content_type: str = "audio/ogg",
) -> str:
    """Transcribe an audio file → text. Returns "" on any failure (never raises).

    Tries ``STT_MODELS`` in order; a 404 (unknown model) falls through to the
    next model rather than giving up. Successful calls are recorded in
    ``nexus_ai.usage_events`` (module="voice_stt").
    """
    # G08 獨立 key 儲存：provider_credentials（AES-256-GCM）→ env fallback
    from app.services.provider_keys import load_provider_key

    key = await load_provider_key("siliconflow", tenant_id)
    if not key:
        log.warning("STT skipped: no siliconflow key available")
        return ""

    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        log.warning("STT read failed: %s", e)
        return ""
    if not data:
        return ""

    for model in STT_MODELS:
        text, seconds = await _post_stt(key, data, filename, content_type, model)
        if text is None:
            continue  # hard failure (network / 404 / non-200) → try next model
        if text:
            await _record_usage(model, seconds, tenant_id, user_id)
        return text
    return ""


async def _post_stt(
    key: str, data: bytes, filename: str, content_type: str, model: str
) -> tuple[Optional[str], float]:
    """POST one multipart STT request.

    Returns ``(transcript, duration_seconds)``. ``transcript is None`` means a
    hard failure and the caller should try the next model; an empty string is a
    valid "no speech detected" result.
    """
    boundary = f"----hermes{os.urandom(8).hex()}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nauto\r\n'.encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
        ).encode()
        + data
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                STT_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                content=body,
            )
    except Exception as e:  # noqa: BLE001 — network blips must not raise
        log.warning("STT request error (%s): %s", model, e)
        return None, 0.0

    if resp.status_code == 404:
        log.warning("STT model not found: %s — trying next model", model)
        return None, 0.0
    if resp.status_code != 200:
        log.warning("STT failed (%s): %s %s", model, resp.status_code, resp.text[:200])
        return None, 0.0

    try:
        j = resp.json()
    except Exception:  # noqa: BLE001
        return None, 0.0
    seconds = float(((j.get("usage") or {}).get("seconds")) or 0)
    return (j.get("text") or "").strip(), seconds


async def _record_usage(
    model: str, seconds: float, tenant_id: Optional[UUID], user_id: Optional[UUID]
) -> None:
    """Best-effort central usage tracking (nexus_ai.usage_events)."""
    if not tenant_id or not user_id:
        return
    try:
        from app.db import async_session
        from app.models.ai.usage import UsageEvent
        from sqlalchemy import text as _sqltext

        async with async_session() as db:
            # 新 session 冇 GUC → RLS 擋 INSERT（usage 靜默記錄唔到）— 開頭 set 返
            await db.execute(
                _sqltext(
                    "SELECT set_config('app.tenant_id', :t, true), "
                    "set_config('app.user_id', :u, true)"
                ),
                {"t": str(tenant_id), "u": str(user_id)},
            )
            db.add(
                UsageEvent(
                    session_id=None,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    provider="siliconflow",
                    model=model,
                    # STT usage is duration-based (seconds) → no token counts
                    input_tokens=0,
                    output_tokens=0,
                    cost_estimate=None,
                    result_status="success",
                    module="voice_stt",
                    currency="USD",
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — usage recording is best-effort
        pass

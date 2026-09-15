"""
WhatsApp Cloud API client — send messages, templates, verify webhooks.

Uses Meta's Graph API v21.0 (WhatsApp Business Platform).
All config read from app.config.settings at call-time.
"""
import hmac
import hashlib
import re
import httpx
from app.config import settings

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def _access_token() -> str:
    return settings.whatsapp_access_token or ""


def _phone_number_id() -> str:
    return settings.whatsapp_phone_number_id or ""


def _verify_token() -> str:
    return settings.whatsapp_webhook_verify_token or ""


def _app_secret() -> str:
    return settings.whatsapp_app_secret or ""


def verify_webhook(mode: str, token: str, challenge: str) -> tuple[bool, str]:
    """
    Handle Meta's webhook verification handshake (GET).
    Returns (is_valid, challenge_or_error).
    """
    if mode == "subscribe" and token == _verify_token():
        return True, challenge
    return False, ""


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    Validate X-Hub-Signature-256 header.
    Meta signs each webhook POST with the App Secret.
    """
    expected = hmac.new(
        _app_secret().encode(), payload_body, hashlib.sha256
    ).hexdigest()
    received = signature_header.replace("sha256=", "").strip()
    return hmac.compare_digest(expected, received)


async def send_template(
    wa_id: str,
    template_name: str,
    params: list[str] | None = None,
    lang: str = "zh_HK",
) -> dict:
    """
    Send a template message (required for 24h+ window / first touch).
    Returns the API response JSON.
    """
    components = []
    if params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in params],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
        },
    }
    if components:
        payload["template"]["components"] = components

    return await _post_message(payload)


async def send_text(wa_id: str, text: str) -> dict:
    """Send a free-form text message (24h window from last user message)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "text",
        "text": {"body": text},
    }
    return await _post_message(payload)


async def download_media(media_id: str) -> tuple[bytes | None, str]:
    """Download a WhatsApp media object by ID (Cloud API two-step fetch).

    Returns (content, mime_type); (None, "") on failure. Used for incoming
    namecard photos.
    """
    token = _access_token()
    if not token or not media_id:
        return None, ""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: media ID → media URL
            r = await client.get(
                f"{GRAPH_API_BASE}/{_phone_number_id()}/media/{media_id}",
                headers=headers,
            )
            if r.status_code != 200:
                return None, ""
            url = (r.json() or {}).get("url", "")
            mime = (r.json() or {}).get("mime_type", "")
            if not url:
                return None, ""
            # Step 2: media URL → binary content
            r2 = await client.get(url, headers=headers)
            if r2.status_code != 200:
                return None, ""
            return r2.content, mime
    except Exception:  # noqa: BLE001 — media download must never crash webhook
        return None, ""


async def send_contact(wa_id: str, contact: dict) -> dict:
    """
    Send a native WhatsApp contact card (vCard).
    
    contact dict keys (all optional except name):
      name: str          — "Wilson Chan"
      phone: str         — "+85200000000"
      email: str         — "wilson@example.com"
      company: str       — "SYSTEX Information (H.K.) Ltd."
      job_title: str     — "Sales Manager"
      url: str           — LinkedIn / website
      address: str       — office address
      notes: str         — any extra info
    """
    name_parts = contact.get("name", "Unknown").strip().split(maxsplit=1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    card: dict = {
        "name": {
            "formatted_name": contact.get("name", "Unknown"),
        }
    }
    if first_name:
        card["name"]["first_name"] = first_name
    if last_name:
        card["name"]["last_name"] = last_name

    if contact.get("phone"):
        # Normalize to E.164 (strip spaces/dashes) so WhatsApp renders the
        # number as a tappable phone — "852 6302 3030" shows as text only.
        raw_phone = str(contact["phone"]).strip()
        e164_phone = re.sub(r"[\s\-\(\)]", "", raw_phone)
        if not e164_phone.startswith("+"):
            e164_phone = "+" + e164_phone
        card["phones"] = [{
            "phone": e164_phone,
            "type": "CELL",
            "wa_id": e164_phone.lstrip("+"),
        }]
    if contact.get("email"):
        card["emails"] = [{"email": contact["email"], "type": "WORK"}]
    if contact.get("company") or contact.get("job_title"):
        org = {}
        if contact.get("company"):
            org["company"] = contact["company"]
        if contact.get("job_title"):
            org["title"] = contact["job_title"]
        card["org"] = org
    if contact.get("url"):
        card["urls"] = [{"url": contact["url"], "type": "WORK"}]
    if contact.get("address"):
        card["addresses"] = [{
            "street": contact["address"],
            "type": "WORK",
        }]

    payload = {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "contacts",
        "contacts": [card],
    }
    return await _post_message(payload)


async def send_otp(wa_id: str, otp: str) -> dict:
    """
    Send OTP verification message.
    Uses text message for testing (works in sandbox mode).
    For production: use 'account_verification_otp' template (must be approved in Meta Business Manager).
    """
    return await send_text(wa_id, f"Your Penguin CRM verification code: {otp}\n\nCode expires in 5 minutes.")


async def _post_message(payload: dict) -> dict:
    """POST to the WhatsApp Cloud API messages endpoint."""
    phone_id = _phone_number_id()
    token = _access_token()
    if not phone_id or not token:
        return {"error": True, "message": "WhatsApp API not configured"}

    url = f"{GRAPH_API_BASE}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        return resp.json()

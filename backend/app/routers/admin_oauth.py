"""
Admin Router — OAuth client ID management.
Stores client IDs in oauth_clients.json (read by _build_oauth_url).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from app.routers.crm_integrations import _get_client_id, _get_client_secret, _save_client_ids, OAUTH_CLIENTS_FILE
import os, json

router = APIRouter(prefix="/api/v1/admin")


def _check_admin(request: Request):
    role = getattr(request.state, "role", "") or ""
    if role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin access required")


PROVIDER_INFO = {
    "google_calendar": "Google Calendar · https://console.cloud.google.com/apis/credentials",
    "outlook_calendar": "Outlook Calendar · https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps",
    "gmail": "Gmail · https://console.cloud.google.com/apis/credentials",
    "slack": "Slack · https://api.slack.com/apps",
    "stripe": "Stripe · https://dashboard.stripe.com/settings/connect",
    "notion": "Notion · https://www.notion.so/my-integrations",
    "zoom": "Zoom · https://marketplace.zoom.us/develop/create",
    "linkedin": "LinkedIn · https://www.linkedin.com/developers/apps",
    "hubspot": "HubSpot · https://developers.hubspot.com/",
    "facebook": "Facebook · https://developers.facebook.com/apps",
}


@router.get("/oauth-clients")
async def list_oauth_clients(request: Request):
    _check_admin(request)
    # Read current data from file
    data = {}
    try:
        with open(OAUTH_CLIENTS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    result = []
    for provider, desc in PROVIDER_INFO.items():
        entry = data.get(provider, {})
        result.append({
            "provider": provider,
            "description": desc,
            "has_client_id": bool(entry.get("client_id", "")),
            "has_client_secret": bool(entry.get("client_secret", "")),
        })
    return result


@router.put("/oauth-clients/{provider}")
async def set_oauth_client(
    request: Request,
    provider: str,
):
    _check_admin(request)
    if provider not in PROVIDER_INFO:
        raise HTTPException(400, f"Unknown provider: {provider}")

    body = await request.json()
    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")

    if not client_id:
        raise HTTPException(400, "client_id is required")

    # Read current, update, save
    data = {}
    try:
        with open(OAUTH_CLIENTS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    data[provider] = {
        "client_id": client_id,
        "client_secret": client_secret,
    }
    _save_client_ids(data)

    return {"provider": provider, "status": "configured"}

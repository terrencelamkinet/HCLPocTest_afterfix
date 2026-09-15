"""
Integrations Router — per-user, tenant-isolated.

Endpoints:
  GET    /integrations              → list user's connected integrations
  POST   /integrations              → create URL/webhook-based connection directly
  POST   /integrations/oauth/start  → create OAuth state, return redirect URL
  POST   /integrations/oauth/callback → complete OAuth, store tokens
  PATCH  /integrations/{id}         → update status/config
  DELETE /integrations/{id}         → disconnect (remove integration)
"""

import uuid
import secrets
import os
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.integration import Integration, OAuthState
from app.schemas.integration import IntegrationResponse, IntegrationUpdate, OAuthStateResponse

router = APIRouter(prefix="/api/v1")


def _tid(request: Request) -> UUID:
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(403, "Tenant not identified")
    return tid


def _uid(request: Request) -> UUID:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "User not authenticated")
    return uid


# ─── LIST user's integrations ─────────────────────────────────


@router.get("/integrations", response_model=list[IntegrationResponse])
async def list_integrations(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
    ).order_by(Integration.created_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


# ─── CREATE (URL/webhook-based connection) ─────────────────────


@router.post("/integrations", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Create a new integration connection directly (URL/webhook-based).
    Body: { "provider": "google_calendar", "provider_display": "Google Calendar",
            "status": "active", "config": {"connection_url": "..."},
            "metadata_": {"connected_at": "..."} }
    """
    body = await request.json()
    tenant_id = _tid(request)
    user_id = _uid(request)

    provider = body.get("provider", "")
    if not provider:
        raise HTTPException(400, "provider is required")

    integration = Integration(
        tenant_id=tenant_id,
        user_id=user_id,
        provider=provider,
        provider_display=body.get("provider_display", provider.replace("_", " ").title()),
        status=body.get("status", "active"),
        config=body.get("config", {}),
        metadata_=body.get("metadata_", {}),
    )
    db.add(integration)
    await db.flush()
    await db.refresh(integration)
    return integration


# ─── GET single integration ────────────────────────────────────


@router.get("/integrations/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    request: Request,
    integration_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Integration).where(
        Integration.id == integration_id,
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Integration not found")
    return row


# ─── UPDATE ────────────────────────────────────────────────────


@router.patch("/integrations/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    request: Request,
    integration_id: UUID,
    body: IntegrationUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Integration).where(
        Integration.id == integration_id,
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Integration not found")

    if body.status is not None:
        row.status = body.status
    if body.config is not None:
        row.config = body.config
    if body.metadata_ is not None:
        row.metadata_ = body.metadata_
    row.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(row)
    return row


# ─── DELETE (disconnect) ───────────────────────────────────────


@router.delete("/integrations/{integration_id}", status_code=204)
async def delete_integration(
    request: Request,
    integration_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Integration).where(
        Integration.id == integration_id,
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Integration not found")
    await db.delete(row)
    return None


# ─── ICS URL subscription ────────────────────────────────────────


@router.post("/integrations/ics", response_model=IntegrationResponse, status_code=201)
async def create_ics_integration(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Subscribe to an iCal URL (public calendar — no OAuth needed).

    Body: { "ics_url": "https://.../basic.ics", "provider_display": "..." }
    Provider is stored as 'ics'. First sync runs immediately.
    """
    body = await request.json()
    ics_url = (body.get("ics_url") or "").strip()
    if not ics_url:
        raise HTTPException(400, "ics_url is required")
    if not ics_url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "ics_url must be an http(s) URL")

    tenant_id = _tid(request)
    user_id = _uid(request)

    # dedup: one ICS subscription per user per URL
    existing = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.user_id == user_id,
                Integration.provider == "ics",
                Integration.config.op("->>")("connection_url") == ics_url,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    integration = Integration(
        tenant_id=tenant_id,
        user_id=user_id,
        provider="ics",
        provider_display=body.get("provider_display", "ICS Calendar"),
        status="active",
        config={"connection_url": ics_url},
        metadata_={"connected_at": datetime.now(timezone.utc).isoformat()},
    )
    db.add(integration)
    await db.flush()
    await db.refresh(integration)

    # immediate first sync
    try:
        from app.services.calendar_sync import sync_ics
        await sync_ics(db, integration)
        integration.last_sync_at = datetime.now(timezone.utc)
    except Exception as e:
        integration.status = "error"
        integration.metadata_ = {
            **(integration.metadata_ or {}),
            "last_error": f"{type(e).__name__}: {str(e)[:200]}",
        }
    await db.flush()
    await db.refresh(integration)
    return integration


# ─── Manual sync trigger ─────────────────────────────────────────


@router.post("/integrations/{integration_id}/sync")
async def sync_integration_now(
    request: Request,
    integration_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Force a calendar sync for one integration (bypasses interval policy)."""
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Integration).where(
        Integration.id == integration_id,
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Integration not found")
    if row.provider not in ("google_calendar", "outlook_calendar", "ics", "ical"):
        raise HTTPException(400, "provider does not support calendar sync")

    try:
        from app.services.calendar_sync import sync_integration
        stats = await sync_integration(db, row)
        row.last_sync_at = datetime.now(timezone.utc)
        row.status = "active"
        await db.flush()
        return {"status": "ok", "integration_id": str(integration_id), "stats": stats}
    except Exception as e:
        row.status = "error"
        row.metadata_ = {
            **(row.metadata_ or {}),
            "last_error": f"{type(e).__name__}: {str(e)[:200]}",
        }
        await db.flush()
        raise HTTPException(502, f"Sync failed: {type(e).__name__}: {str(e)[:150]}")


# ─── OAuth: START flow ─────────────────────────────────────────


@router.post("/integrations/oauth/start")
async def oauth_start(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Start OAuth flow for a provider.
    Body: { "provider": "google_calendar", "origin": "https://www.penguincrm.io" }
    The origin (frontend URL) is used as the OAuth redirect_uri so the
    provider sends the user back to a frontend page, not the backend.
    """
    body = await request.json()
    provider = body.get("provider", "")
    # Derive frontend origin from request Origin header or body.origin
    frontend_origin = body.get("origin", "") or request.headers.get("origin", "http://localhost:5173")

    if not provider:
        raise HTTPException(400, "provider is required")

    tenant_id = _tid(request)
    user_id = _uid(request)

    # Generate random state for CSRF protection
    state = secrets.token_urlsafe(32)
    oauth = OAuthState(
        tenant_id=tenant_id,
        user_id=user_id,
        provider=provider,
        state=state,
        redirect_uri=frontend_origin,  # store origin for callback context
    )
    db.add(oauth)
    await db.flush()

    # Build provider-specific OAuth URL — redirect_uri points to frontend
    oauth_url = _build_oauth_url(provider, state, frontend_origin)

    return {
        "state": state,
        "oauth_url": oauth_url,
        "provider": provider,
    }


# ─── OAuth: CALLBACK ───────────────────────────────────────────


@router.post("/integrations/oauth/callback")
async def oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """
    Complete OAuth flow.
    Body: { code, state } — provider is looked up from the OAuthState table.
    Called by the frontend OAuthCallbackPage after the provider redirects.
    """
    body = await request.json()
    code = body.get("code", "")
    state = body.get("state", "")

    if not code or not state:
        raise HTTPException(400, "Missing code or state")

    tenant_id = _tid(request)
    user_id = _uid(request)

    # Look up OAuthState by state to get provider。
    # 2026-09-15：加 TTL。state 係一次性 CSRF token，之前冇任何 expiry check →
    # 洩漏咗（URL / browser history / log）嘅 state 可以無限期待用，而且未用嘅
    # state 會一直累積（實測 300+ row）。
    q = select(OAuthState).where(
        OAuthState.state == state,
        OAuthState.tenant_id == tenant_id,
        OAuthState.user_id == user_id,
        OAuthState.created_at
        > datetime.now(timezone.utc) - timedelta(minutes=OAUTH_STATE_TTL_MIN),
    )
    state_row = (await db.execute(q)).scalar_one_or_none()
    if not state_row:
        raise HTTPException(400, "Invalid or expired OAuth state")

    provider = state_row.provider

    # Exchange code for tokens (provider-specific).
    # 2026-09-15：state 係一次性 token。exchange 失敗（上游 502 / provider 未配置 500）時
    # 唔即刻 consume 就會留低 state row（request 失敗 → transaction rollback 埋個刪除），
    # 變成可以無限重玩，oauth_states 亦會慢慢漏 row。
    try:
        token_data = await _exchange_code(provider, code)
    except HTTPException:
        try:
            await db.delete(state_row)
            await db.commit()
        except Exception:
            await db.rollback()
        raise

    # Upsert integration
    q2 = select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
        Integration.provider == provider,
    )
    existing = (await db.execute(q2)).scalar_one_or_none()

    if existing:
        existing.status = "active"
        existing.config = token_data
        existing.metadata_ = {
            **(existing.metadata_ or {}),
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(existing)
        result = existing
    else:
        integration = Integration(
            tenant_id=tenant_id,
            user_id=user_id,
            provider=provider,
            provider_display=_provider_display_name(provider),
            status="active",
            config=token_data,
            metadata_={"connected_at": datetime.now(timezone.utc).isoformat()},
        )
        db.add(integration)
        await db.flush()
        await db.refresh(integration)
        result = integration

    # Clean up OAuth state
    await db.delete(state_row)

    return IntegrationResponse.model_validate(result)


# ─── Helpers ───────────────────────────────────────────────────


OAUTH_URLS = {
    "google_calendar": "https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=https://www.googleapis.com/auth/calendar.readonly+https://www.googleapis.com/auth/calendar.events.readonly&access_type=offline&state={state}",
    "outlook_calendar": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=Calendars.Read+offline_access&state={state}",
    "gmail": "https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=https://www.googleapis.com/auth/gmail.readonly+https://www.googleapis.com/auth/gmail.modify&access_type=offline&state={state}",
    "outlook_mail": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=Mail.Read+offline_access&state={state}",
    "slack": "https://slack.com/oauth/v2/authorize?client_id={client_id}&redirect_uri={redirect}&scope=channels:read,chat:write&state={state}",
    "zoom": "https://zoom.us/oauth/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=meeting:read&state={state}",
    "whatsapp": "https://www.facebook.com/v21.0/dialog/oauth?client_id={client_id}&redirect_uri={redirect}&scope=whatsapp_business_messaging&state={state}",
    "teams": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=OnlineMeetings.Read+Chat.Read+offline_access&state={state}",
    "google_drive": "https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=https://www.googleapis.com/auth/drive.readonly&access_type=offline&state={state}",
    "dropbox": "https://www.dropbox.com/oauth2/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&token_access_type=offline&state={state}",
    "onedrive": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=Flles.Read+offline_access&state={state}",
    "linkedin": "https://www.linkedin.com/oauth/v2/authorization?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=openid+profile+email&state={state}",
    "facebook": "https://www.facebook.com/v21.0/dialog/oauth?client_id={client_id}&redirect_uri={redirect}&scope=pages_manage_leads,pages_read_engagement&state={state}",
    "zapier": "",  # webhook-based, no OAuth
    "make": "",    # webhook-based, no OAuth
    "notion": "https://api.notion.com/v1/oauth/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&owner=user&state={state}",
    "stripe": "https://connect.stripe.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=read_write&state={state}",
    "quickbooks": "https://appcenter.intuit.com/connect/oauth2?client_id={client_id}&redirect_uri={redirect}&response_type=code&scope=com.intuit.quickbooks.accounting+openid+profile+email&state={state}",
    "mailchimp": "https://login.mailchimp.com/oauth2/authorize?client_id={client_id}&redirect_uri={redirect}&response_type=code&state={state}",
    "hubspot": "https://app.hubspot.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect}&scope=crm.objects.contacts.read%20crm.objects.deals.read&state={state}",
}

PROVIDER_DISPLAY = {
    "google_calendar": "Google Calendar",
    "outlook_calendar": "Outlook Calendar",
    "gmail": "Gmail",
    "outlook_mail": "Outlook Mail",
    "slack": "Slack",
    "zoom": "Zoom",
    "whatsapp": "WhatsApp Business",
    "teams": "Microsoft Teams",
    "google_drive": "Google Drive",
    "dropbox": "Dropbox",
    "onedrive": "OneDrive",
    "linkedin": "LinkedIn",
    "facebook": "Facebook Pages",
    "zapier": "Zapier",
    "make": "Make",
    "notion": "Notion",
    "stripe": "Stripe",
    "quickbooks": "QuickBooks",
    "mailchimp": "Mailchimp",
    "hubspot": "HubSpot",
}


OAUTH_CLIENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "oauth_clients.json")


def _get_client_id(provider: str) -> str:
    """Get OAuth client ID for a provider.
    Priority: oauth_clients.json → config.py env vars → PLACEHOLDER
    """
    from app.config import settings
    try:
        with open(OAUTH_CLIENTS_FILE) as f:
            data = json.load(f)
        if provider in data and data[provider].get("client_id"):
            return data[provider]["client_id"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    env_val = settings.integration_client_ids.get(provider, "")
    if env_val:
        return env_val
    return "PLACEHOLDER"


def _get_client_secret(provider: str) -> str:
    try:
        with open(OAUTH_CLIENTS_FILE) as f:
            data = json.load(f)
        if provider in data and data[provider].get("client_secret"):
            return data[provider]["client_secret"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return ""


def _save_client_ids(data: dict) -> None:
    with open(OAUTH_CLIENTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _build_oauth_url(provider: str, state: str, frontend_origin: str = "") -> str:
    """Build OAuth authorization URL for a given provider.
    The redirect_uri points to the frontend OAuth callback page so the
    provider sends users back to our UI, not directly to the backend.
    Reads client_id from DB (set via Admin UI) or falls back to env config.
    """
    from app.config import settings

    template = OAUTH_URLS.get(provider, "")
    if not template:
        return ""

    callback_url = f"{frontend_origin or 'http://localhost:5173'}/marketplace/oauth/callback"
    # Fallback chain: DB-stored client_id → env config → placeholder
    client_id = _get_client_id(provider)

    return template.format(
        client_id=client_id,
        redirect=callback_url,
        state=state,
    )


def _provider_display_name(provider: str) -> str:
    return PROVIDER_DISPLAY.get(provider, provider.replace("_", " ").title())


# OAuth state 最長有效時間（分鐘）— 過期後 callback 一律 400（見 oauth_callback）。
OAUTH_STATE_TTL_MIN = 15

# 有真實 token endpoint 嘅 provider；冇列出嘅會走 placeholder 分支。
_TOKEN_ENDPOINTS = {
    "google_calendar": "https://oauth2.googleapis.com/token",
    "gmail": "https://oauth2.googleapis.com/token",
    "google_drive": "https://oauth2.googleapis.com/token",
    "outlook_calendar": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "outlook_mail": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
}


async def _http_post_json(url: str, data: dict, headers: dict | None = None) -> dict:
    """POST form-encoded → JSON response. Raises HTTPException(502) on failure."""
    import httpx

    form = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in data.items())
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.post(
                url,
                content=form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    **(headers or {}),
                },
            )
    except Exception:
        raise HTTPException(502, f"Token endpoint unreachable: {url}")
    if r.status_code >= 400:
        raise HTTPException(502, f"Token exchange failed ({r.status_code}): {r.text[:200]}")
    return r.json()


async def _exchange_code(provider: str, code: str) -> dict:
    """Exchange authorization code for tokens (real HTTP exchange).

    Platform-owned OAuth client — client_id/secret come from server-side
    oauth_clients.json / .env, never from the frontend.
    Returns dict with at least {access_token, refresh_token, expires_at, scope}.
    """
    endpoint = _TOKEN_ENDPOINTS.get(provider)
    if not endpoint:
        # Unknown provider — keep legacy placeholder behaviour
        return {
            "access_token": f"placeholder_{provider}_{code[:16]}",
            "refresh_token": f"refresh_{provider}_{uuid.uuid4().hex[:16]}",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "scope": "",
        }

    client_id = _get_client_id(provider)
    client_secret = _get_client_secret(provider)
    if client_id == "PLACEHOLDER" or not client_secret:
        raise HTTPException(500, f"OAuth client for {provider} not configured (platform setup required)")

    # redirect_uri must match the one used in _build_oauth_url
    frontend_origin = "https://www.penguincrm.io"
    redirect_uri = f"{frontend_origin}/marketplace/oauth/callback"

    token = await _http_post_json(endpoint, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })

    expires_in = token.get("expires_in", 3600)
    return {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": datetime.now(timezone.utc).timestamp() + int(expires_in),
        "scope": token.get("scope", ""),
        "token_type": token.get("token_type", "Bearer"),
    }


async def refresh_access_token(provider: str, refresh_token: str) -> dict:
    """Refresh an expired access token. Returns {access_token, expires_at, refresh_token}.

    Raises HTTPException(502) on failure — caller should mark integration disconnected
    when refresh fails (user revoked access).
    """
    endpoint = _TOKEN_ENDPOINTS.get(provider)
    if not endpoint or not refresh_token:
        raise HTTPException(502, f"No refresh endpoint/token for {provider}")

    client_id = _get_client_id(provider)
    client_secret = _get_client_secret(provider)

    token = await _http_post_json(endpoint, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })

    expires_in = token.get("expires_in", 3600)
    return {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", refresh_token),
        "expires_at": datetime.now(timezone.utc).timestamp() + int(expires_in),
        "scope": token.get("scope", ""),
        "token_type": token.get("token_type", "Bearer"),
    }


# ─── Google Calendar picker ────────────────────────────────────


async def _google_calendar_row(db: AsyncSession, tenant_id: UUID, user_id: UUID):
    """Find the user's google_calendar integration row (or None)."""
    q = select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.user_id == user_id,
        Integration.provider == "google_calendar",
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


@router.get("/integrations/google-calendar/calendars")
async def list_google_calendars(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List the user's Google calendars (id + name + primary flag).

    Uses the existing OAuth token — no extra consent needed
    (calendar.readonly scope already covers calendarList).
    """
    tenant_id = _tid(request)
    user_id = _uid(request)

    row = await _google_calendar_row(db, tenant_id, user_id)
    if not row:
        raise HTTPException(404, "Google Calendar not connected")

    from app.services.calendar_sync import _valid_access_token
    try:
        access_token, cfg_update = await _valid_access_token(row)
    except Exception as e:
        raise HTTPException(502, f"Cannot refresh Google token: {e}")
    if cfg_update:
        row.config = cfg_update
        await db.flush()

    import httpx
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            params={"minAccessRole": "reader", "maxResults": 100},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if r.status_code == 401:
            raise HTTPException(401, "Google token expired — reconnect")
        if r.status_code == 403:
            raise HTTPException(403, "Google API access denied")
        r.raise_for_status()
        items = r.json().get("items", [])

    return [
        {
            "id": c.get("id", ""),
            "summary": c.get("summary", "(untitled)"),
            "primary": bool(c.get("primary", False)),
            "access_role": c.get("accessRole", "reader"),
        }
        for c in items
        if c.get("id")
    ]


class GoogleCalendarSettingsBody(BaseModel):
    calendar_ids: list[str]
    calendar_names: dict[str, str] = {}


@router.put("/integrations/google-calendar/settings", response_model=IntegrationResponse)
async def update_google_calendar_settings(
    request: Request,
    body: GoogleCalendarSettingsBody,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Pick which Google calendars to mirror into CRM (multi-select).

    Merges calendar_ids (+ names map) into the existing config —
    never touches access_token/refresh_token. Default (no selection
    ever made) = primary calendar only.
    """
    tenant_id = _tid(request)
    user_id = _uid(request)

    row = await _google_calendar_row(db, tenant_id, user_id)
    if not row:
        raise HTTPException(404, "Google Calendar not connected")

    cfg = dict(row.config or {})
    cfg["calendar_ids"] = [str(i) for i in body.calendar_ids]
    cfg["calendar_names"] = {str(k): str(v) for k, v in body.calendar_names.items()}
    cfg.pop("calendar_id", None)  # legacy single-select key — superseded
    row.config = cfg
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(row)
    return row

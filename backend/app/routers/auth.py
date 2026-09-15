from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User, Session, Tenant, TenantMember
from app.services.tenant_bootstrap import ensure_default_workspace
from app.schemas import LoginRequest, RegisterRequest, MFAVerifyRequest, TokenResponse, RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, UserOut
from app.services.auth_service import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    create_reset_token, decode_token, generate_otp
)
from app.services.email_service import send_otp_email
from app.services.session_cookies import set_session_cookies, clear_session_cookies, refresh_token_from_request
from app.services.redis_service import store_otp, verify_otp, store_refresh_blacklist, check_device_trust, store_device_trust, get_redis
from app.config import settings
import uuid
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _session_response(response: Response, body: TokenResponse) -> TokenResponse:
    """回 token 嘅 endpoint 全部經呢度 —— 順手種 httpOnly session cookie。

    2026-09-15 SAST（AppScan: Web Local Storage Insecure）：前端唔再將 token 存
    localStorage；cookie 由瀏覽器自動帶（同源 + SameSite=Lax）。Body 照樣回 token
    係為咗 scripts / e2e / CLI 向後兼容（佢哋用 Authorization: Bearer）。
    """
    set_session_cookies(response, body.access_token, body.refresh_token)
    return body


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Create personal tenant
    safe_name = req.display_name.strip() or req.email.split("@")[0]
    subdomain = f"p-{uuid.uuid4().hex[:12]}"
    tenant = Tenant(name=safe_name, subdomain=subdomain)
    db.add(tenant)
    await db.flush()

    # Create user
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name or safe_name,
        email_verified=True,  # Skip email verification for now
        mfa_enabled=False,    # MFA optional
        role="member",
    )
    db.add(user)
    await db.flush()

    # Link to tenant
    tm = TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner")
    db.add(tm)
    await db.flush()

    # 2026-09-12 結構性修復：tenant 一建立就要有 workspace。
    # 之前呢度冇建 → 新註冊用戶所有寫入（companies/contacts/tasks/projects/notes…）
    # 撞 workspace_id NOT NULL → HTTP 500（GET 正常所以冇人發現）。
    await ensure_default_workspace(db, tenant.id, user.id)

    # Issue tokens
    tenant_id = str(tenant.id)
    access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
    refresh_token_str, expires_at = create_refresh_token(str(user.id))

    db_session = Session(
        user_id=user.id,
        refresh_token=refresh_token_str,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "unknown",
        expires_at=expires_at,
    )
    db.add(db_session)
    await db.flush()

    # Create default notification preferences for all modules (per-user)
    from app.services.notification_service import ensure_default_preferences
    await ensure_default_preferences(db, tenant.id, user.id)

    return _session_response(response, TokenResponse(
        access_token=access_token,
        mfa_required=False,
        email=user.email,
        refresh_token=refresh_token_str,
    ))

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # Find user
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # If MFA not enabled for this user — skip OTP, issue tokens directly
    if not user.mfa_enabled:
        tm = await db.execute(
            select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
        )
        tm_row = tm.scalar_one_or_none()
        tenant_id = str(tm_row.tenant_id) if tm_row else ""

        access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
        refresh_token_str, expires_at = create_refresh_token(str(user.id))
        db_session = Session(
            user_id=user.id, refresh_token=refresh_token_str,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=request.client.host if request.client else "unknown",
            expires_at=expires_at
        )
        db.add(db_session)
        await db.flush()
        return _session_response(response, TokenResponse(
            access_token=access_token, mfa_required=False,
            email=user.email, refresh_token=refresh_token_str,
        ))

    # Check device trust — skip MFA if device token is valid
    if req.device_token:
        trusted = await check_device_trust(str(user.id), req.device_token)
        if trusted:
            # Resolve tenant
            tm = await db.execute(
                select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
            )
            tm_row = tm.scalar_one_or_none()
            tenant_id = str(tm_row.tenant_id) if tm_row else ""

            access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
            refresh_token_str, expires_at = create_refresh_token(str(user.id))
            db_session = Session(
                user_id=user.id, refresh_token=refresh_token_str,
                user_agent=request.headers.get("user-agent", ""),
                ip_address=request.client.host if request.client else "unknown",
                expires_at=expires_at
            )
            db.add(db_session)
            await db.flush()
            return _session_response(response, TokenResponse(
                access_token=access_token, mfa_required=False,
                email=user.email, device_token=req.device_token,
                refresh_token=refresh_token_str,
            ))

    # Generate and send OTP
    otp = generate_otp()
    await store_otp(req.email, otp)
    await send_otp_email(req.email, otp)

    return _session_response(response, TokenResponse(
        access_token="",
        mfa_required=True,
        email=req.email
    ))

@router.post("/google", response_model=TokenResponse)
async def google_login(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Sign in with Google — GIS ID-token flow (2026-09-11).

    The browser hands us the ID token Google issued. We verify it against Google's
    public keys with OUR client id as the audience, then match it to an existing
    CRM user by email. We deliberately do NOT auto-create accounts: this is a
    tenant-scoped CRM and a Google identity says nothing about which tenant the
    person belongs to, so an unknown email is refused rather than given a
    tenant-less account. The client SECRET is never needed here — nothing is
    exchanged, only a signature checked.
    """
    from sqlalchemy import func as _func
    from google.auth.transport import requests as _greq
    from google.oauth2 import id_token as _gid

    from app.config import settings as _settings

    client_id = _settings.google_client_id
    if not client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    body = await request.json()
    credential = (body or {}).get("credential") or ""
    if not credential:
        raise HTTPException(status_code=400, detail="Missing credential")

    try:
        info = _gid.verify_oauth2_token(credential, _greq.Request(), client_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google credential")

    if not info.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google email not verified")

    email = (info.get("email") or "").strip().lower()
    sub = info.get("sub") or ""
    if not email or not sub:
        raise HTTPException(status_code=401, detail="Incomplete Google profile")

    result = await db.execute(select(User).where(_func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=403, detail="No CRM account for this Google email")

    if user.google_sub and user.google_sub != sub:
        raise HTTPException(
            status_code=403,
            detail="This account is linked to a different Google account",
        )
    if not user.google_sub:
        user.google_sub = sub

    # Copy Google's profile over, but only into blanks. A name the operator has
    # edited in the CRM must not be clobbered by whatever Google happens to hold.
    if not (user.display_name or "").strip():
        user.display_name = info.get("name") or ""
    if not (user.avatar_url or "").strip():
        user.avatar_url = info.get("picture") or ""
    if not (user.locale or "").strip():
        user.locale = info.get("locale") or ""
    # Google's ID token carries no timezone at all, so the browser reports it. A
    # blank is filled; an existing value (however it was set) wins.
    tz = (body or {}).get("timezone") or ""
    if tz and not (user.timezone or "").strip():
        user.timezone = tz
    await db.flush()

    tm = await db.execute(
        select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
    )
    tm_row = tm.scalar_one_or_none()
    tenant_id = str(tm_row.tenant_id) if tm_row else ""

    access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
    refresh_token_str, expires_at = create_refresh_token(str(user.id))
    db_session = Session(
        user_id=user.id, refresh_token=refresh_token_str,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "unknown",
        expires_at=expires_at,
    )
    db.add(db_session)
    await db.flush()
    return _session_response(response, TokenResponse(
        access_token=access_token, mfa_required=False,
        email=user.email, refresh_token=refresh_token_str,
    ))


@router.post("/send-mfa", response_model=dict)
async def send_mfa(req: dict, db: AsyncSession = Depends(get_db)):
    email = req.get("email", "")
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    otp = generate_otp()
    await store_otp(email, otp)
    await send_otp_email(email, otp)
    return {"message": "MFA code sent", "email": email}

@router.post("/verify-mfa", response_model=TokenResponse)
async def verify_mfa(req: MFAVerifyRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # Verify OTP
    valid = await verify_otp(req.email, req.otp_code)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code")

    # Get user
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.email_verified:
        user.email_verified = True
        await db.flush()

    # Create tokens with tenant context
    tm = await db.execute(
        select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
    )
    tm_row = tm.scalar_one_or_none()
    tenant_id = str(tm_row.tenant_id) if tm_row else ""

    access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
    refresh_token_str, expires_at = create_refresh_token(str(user.id))

    # Store session
    db_session = Session(
        user_id=user.id,
        refresh_token=refresh_token_str,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "unknown",
        expires_at=expires_at
    )
    db.add(db_session)
    await db.flush()

    # Generate device trust token if requested
    device_token = None
    if req.trust_device:
        from app.services.auth_service import generate_device_token
        device_token = generate_device_token()
        await store_device_trust(str(user.id), device_token, ttl_days=30)

    return _session_response(response, TokenResponse(
        access_token=access_token,
        mfa_required=False,
        email=user.email,
        device_token=device_token,
        refresh_token=refresh_token_str,
    ))

@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # 2026-09-15 SAST：前端唔再喺 body 傳 token（喺 httpOnly cookie），但照樣接受
    # body 以兼容舊 client / scripts / e2e。
    token_in = refresh_token_from_request(request, req.refresh_token)
    if not token_in:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    payload = decode_token(token_in)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Check blacklist
    r = await get_redis()
    blacklisted = await r.get(f"refresh_blacklist:{payload.get('jti')}")
    if blacklisted:
        raise HTTPException(status_code=401, detail="Token revoked")

    # Find session
    result = await db.execute(
        select(Session).where(
            Session.refresh_token == token_in,
            Session.revoked == False
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=401, detail="Session not found")

    # Get user
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Revoke old session
    session.revoked = True
    await store_refresh_blacklist(payload.get("jti"), datetime.now(timezone.utc))

    # Resolve tenant context
    tm = await db.execute(
        select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
    )
    tm_row = tm.scalar_one_or_none()
    tenant_id = str(tm_row.tenant_id) if tm_row else ""

    # Issue new tokens WITH tenant_id
    new_access = create_access_token(str(user.id), user.email, user.role, tenant_id)
    new_refresh, new_expires = create_refresh_token(str(user.id))

    new_session = Session(
        user_id=user.id,
        refresh_token=new_refresh,
        expires_at=new_expires
    )
    db.add(new_session)
    await db.flush()

    # 2026-09-15 bug fix：之前唔回新 refresh token，但舊嗰個已經 revoke + blacklist
    # → 一世只 refresh 到一次，第二次就 401「Token revoked」。而家回新 token，
    # cookie 同 body 都會換新，refresh 可以無限次（同 refresh_token_expire_days 一致）。
    return _session_response(response, TokenResponse(
        access_token=new_access,
        mfa_required=False,
        email=user.email,
        refresh_token=new_refresh,
    ))

@router.post("/logout")
async def logout(req: RefreshRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # token 可以嚟自 body（舊 client）或 cookie（新前端唔傳 body）
    token_in = refresh_token_from_request(request, req.refresh_token)
    payload = decode_token(token_in) if token_in else None
    if payload and payload.get("jti"):
        expires = datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc)
        await store_refresh_blacklist(payload["jti"], expires)

    if token_in:
        result = await db.execute(
            select(Session).where(Session.refresh_token == token_in)
        )
        session = result.scalar_one_or_none()
        if session:
            session.revoked = True
            await db.flush()

    # 無論上面成功與否，cookie 一定要清（否則前端以為登出咗但 session 仲有效）
    clear_session_cookies(response)

    return {"message": "Logged out"}

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Don't reveal whether email exists — always return success
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"message": "If that email is registered, a reset link has been sent."}

    reset_token, expires = create_reset_token(req.email)
    reset_url = f"{settings.allowed_origins.split(',')[0].strip()}/sign-in?reset_token={reset_token}"

    # Dev mode: print to console
    print(f"[DEV RESET] Reset link for {req.email}: {reset_url}")

    # Try sending email (silently fail if SMTP not configured)
    if settings.smtp_user and settings.smtp_pass:
        msg = MIMEText(
            f"Click the link below to reset your Penguin CRM password:\n\n{reset_url}\n\n"
            f"This link expires in 15 minutes.\n\nIf you didn't request this, ignore this email."
        )
        msg["Subject"] = "Penguin CRM — Password Reset"
        msg["From"] = settings.mfa_from_email
        msg["To"] = req.email
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.send_message(msg)
        except Exception:
            pass  # Dev mode: ignore email errors

    return {"message": "If that email is registered, a reset link has been sent."}

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.token)
    if not payload or payload.get("type") != "reset":
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    email = payload.get("sub", "")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(req.password)
    await db.flush()
    return {"message": "Password has been reset successfully."}

@router.patch("/me", response_model=UserOut)
async def update_me(request: Request, db: AsyncSession = Depends(get_db)):
    """Update the caller's own profile (2026-09-11).

    Every field is optional — only the keys present in the body change. avatar_url
    is free-form on purpose: Google supplies its own picture URL at sign-in, and the
    operator may prefer a different one. There is deliberately no file upload here
    yet; an uploaded image would need the files/storage_key path first.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_token(auth.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    if "display_name" in body:
        user.display_name = str(body.get("display_name") or "")[:255]
    if "avatar_url" in body:
        user.avatar_url = str(body.get("avatar_url") or "")[:2000]
    if "locale" in body:
        user.locale = str(body.get("locale") or "")[:32]
    if "timezone" in body:
        user.timezone = str(body.get("timezone") or "")[:64]
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth.split(" ")[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ═══════════════════════════════════════════════════════════════
# Profile avatar（2026-09-11）— 用戶自己上載／更換頭像
# ---------------------------------------------------------------------------
# 頭像係用戶級資料，唔屬任何 tenant，所以唔入 nexus_crm.files（嗰張表有
# tenant RLS）——檔案存 backend/uploads/avatars/，DB 淨係放 URL。
# Google 登入首先寫入 Google 嘅 picture URL；用戶可隨時上載覆蓋。
# ═══════════════════════════════════════════════════════════════

from pathlib import Path as _Path
from fastapi import File, UploadFile

AVATAR_DIR = _Path(__file__).resolve().parents[2] / "uploads" / "avatars"
_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024


def _bearer_user_id(request: Request) -> uuid.UUID:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_token(auth.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        return uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/me/avatar", response_model=UserOut)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload (or replace) the caller's own avatar.

    舊檔案會先刪除（同一個 user 只會留一個檔案），avatar_url 每次加 ?v=
    時間戳，令瀏覽器唔會重用舊 cache。
    """
    user = await db.get(User, _bearer_user_id(request))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    ext = _Path(file.filename or "avatar.jpg").suffix.lower()
    if ext not in _AVATAR_EXT:
        raise HTTPException(status_code=422, detail="Unsupported image type")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(blob) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image larger than 5MB")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for old in AVATAR_DIR.glob(f"{user.id}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    (AVATAR_DIR / f"{user.id}{ext}").write_bytes(blob)

    stamp = int(datetime.now(timezone.utc).timestamp())
    user.avatar_url = f"/api/v1/auth/avatar/{user.id}{ext}?v={stamp}"
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/avatar/{filename}")
async def get_avatar(filename: str):
    """Serve an avatar file.

    Public on purpose：<img> 唔可以帶 Authorization header，而頭像本身唔係
    tenant 機密資料（Google 頭像亦係公開 URL）。
    """
    from fastapi.responses import FileResponse

    safe = _Path(filename).name  # path traversal guard
    path = AVATAR_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=600"})


# ═══════════════════════════════════════════════════════════════
# Google OAuth Login（2026-08-30）— 一鍵登入 / 註冊
# Reuses the google_calendar OAuth client (same Google Cloud project).
# Flow: /google/start → Google consent → /google/callback → token
# exchange → userinfo → find-or-create user → redirect back with
# tokens in URL fragment (#google_token=...) — fragment never hits
# the server, so JWT stays out of access logs.
# ═══════════════════════════════════════════════════════════════

import os as _os
import json as _json
import secrets as _secrets
from urllib.parse import urlencode
import httpx
from fastapi.responses import RedirectResponse

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_creds() -> tuple[str, str]:
    """Read Google OAuth client creds (reuses google_calendar client)."""
    path = _os.path.join(_os.path.dirname(__file__), "..", "oauth_clients.json")
    try:
        with open(path) as f:
            data = _json.load(f)
    except FileNotFoundError:
        raise HTTPException(400, "Google OAuth not configured")
    entry = data.get("google_calendar") or data.get("google_login") or {}
    client_id = entry.get("client_id", "")
    client_secret = entry.get("client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(400, "Google OAuth not configured")
    return client_id, client_secret


def _public_base(request: Request) -> str:
    """Resolve the public-facing base URL. Behind cloudflared the Host header
    is rewritten to localhost:8001, so prefer an explicit PUBLIC_BASE_URL
    (set in production .env). Fall back to the Host header for direct dev
    access via the Vite proxy (localhost:5173)."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = request.headers.get("host", "")
    scheme = request.url.scheme
    return f"{scheme}://{host}".rstrip("/")


@router.get("/google/start")
async def google_start(request: Request, origin: str = ""):
    """Start Google OAuth login — redirects to the Google authorization page."""
    client_id, _ = _google_creds()
    base = _public_base(request)
    redirect_uri = f"{base}/api/v1/auth/google/callback"
    origin = origin or base
    state = _secrets.token_urlsafe(24)
    r = await get_redis()
    await r.setex(f"google_oauth_state:{state}", 600, origin)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(GOOGLE_AUTH_URL + "?" + urlencode(params))


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Google OAuth callback — exchange code → userinfo → find-or-create
    user → issue JWT → redirect back to {origin}/login/#google_token=..."""
    def fail(msg: str) -> RedirectResponse:
        return RedirectResponse(f"/login/?google_error={msg}")

    if error:
        return fail(f"google_denied:{error}")
    if not code or not state:
        return fail("missing_params")

    # ── Verify state (CSRF) ──
    r = await get_redis()
    origin = await r.get(f"google_oauth_state:{state}")
    if not origin:
        return fail("invalid_state")
    await r.delete(f"google_oauth_state:{state}")

    # ── Exchange code → tokens ──
    client_id, client_secret = _google_creds()
    base = _public_base(request)
    redirect_uri = f"{base}/api/v1/auth/google/callback"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            tok_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            if tok_resp.status_code != 200:
                return fail("token_exchange")
            tokens = tok_resp.json()
            info_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if info_resp.status_code != 200:
                return fail("userinfo")
            info = info_resp.json()
    except httpx.HTTPError:
        return fail("network")

    email = (info.get("email") or "").lower()
    if not email:
        return fail("no_email")
    display_name = info.get("name") or email.split("@")[0]

    # ── Find or create user + tenant + notification prefs ──
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        tenant = Tenant(name=display_name, subdomain=f"p-{uuid.uuid4().hex[:12]}")
        db.add(tenant)
        await db.flush()
        user = User(
            email=email,
            password_hash="",  # Google-only account — no password
            display_name=display_name,
            email_verified=True,
            mfa_enabled=False,
            role="member",
        )
        db.add(user)
        await db.flush()
        db.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
        await db.flush()
        # ensure_default_preferences sets RLS GUC internally (v7.11 fix)
        from app.services.notification_service import ensure_default_preferences
        await ensure_default_preferences(db, tenant.id, user.id)
        # 2026-09-12 結構性修復：Google 註冊同樣要即刻建立 workspace
        # （否則新用戶所有寫入 500 — 見 app/services/tenant_bootstrap.py 註釋）
        await ensure_default_workspace(db, tenant.id, user.id)
        tenant_id = str(tenant.id)
    else:
        tm = (await db.execute(
            select(TenantMember).where(TenantMember.user_id == user.id).limit(1)
        )).scalar_one_or_none()
        tenant_id = str(tm.tenant_id) if tm else ""

    # ── Issue tokens + session ──
    access_token = create_access_token(str(user.id), user.email, user.role, tenant_id)
    refresh_token_str, expires_at = create_refresh_token(str(user.id))
    db.add(Session(
        user_id=user.id,
        refresh_token=refresh_token_str,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "unknown",
        expires_at=expires_at,
    ))
    await db.commit()

    # 2026-09-15 SAST：token 唔再放入 URL fragment。原本 `#google_token=...` 會被前端
    # 寫入 localStorage → URL（history／分享／DevTools／書籤）同 JS 兩重都拎得到。
    # 而家改為種 httpOnly cookie，redirect 只帶一個 `google_ok` 標記。
    resp = RedirectResponse(f"{origin}/login/#google_ok=1")
    set_session_cookies(resp, access_token, refresh_token_str)
    return resp


# ═══════════════════════════════════════════════════════════════
# Special Access Link（2026-08-31）— 加密 magic link 登入通道
# GG family debug 專用：直入 terrence_lam 嘅 tenant，唔使 MFA。
# - token = secrets.token_urlsafe(32)，DB 只存 sha256 hash
# - Terrence 開（JWT auth）→ default 3h 自動關；可傳 hours 彈性
# - GG family 開（Cron-Api-Key）→ default 1h；用完即 revoke
# - Link: https://www.penguincrm.io/login/#sa=<token>
# ═══════════════════════════════════════════════════════════════
import hashlib as _hashlib
from app.models import SpecialAccessLink

_SA_DEFAULT_HOURS = {"terrence": 3.0, "gg_family": 1.0}
_SA_TARGET_EMAIL = "terrence_lam@kinetix.com.hk"


def _sa_hash(token: str) -> str:
    return _hashlib.sha256(token.encode()).hexdigest()


def _sa_require_cron_or_jwt(request: Request) -> tuple[str, str]:
    """Return (actor, actor_email). actor: 'terrence' | 'gg_family'."""
    cron_key = request.headers.get("Cron-Api-Key", "")
    expected = _os.environ.get("NEXUS_CRON_API_KEY", "") or settings.cron_api_key
    if cron_key and cron_key == expected:
        return "gg_family", _SA_TARGET_EMAIL
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        payload = decode_token(auth.split(" ")[1])
        if payload and payload.get("sub"):
            return "terrence", payload.get("email") or ""
    raise HTTPException(status_code=401, detail="Requires Cron-Api-Key or valid JWT")


@router.post("/special-access", response_model=dict)
async def create_special_access(
    req: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create an encrypted magic login link into terrence_lam's tenant.

    Body: {hours?: float, purpose?: str}
    - Terrence JWT → default 3h（「3小時自動關」）
    - GG family Cron-Api-Key → default 1h（用完即 revoke）
    Returns {link, expires_at, created_by, purpose}
    """
    actor, actor_email = _sa_require_cron_or_jwt(request)
    hours = float(req.get("hours") or _SA_DEFAULT_HOURS[actor])
    if hours <= 0 or hours > 72:
        raise HTTPException(status_code=400, detail="hours must be 0 < hours <= 72")
    purpose = (req.get("purpose") or "").strip()[:200]

    # Target = terrence_lam 主帳戶 + 佢嘅 Kinetix tenant
    target = (await db.execute(
        select(User).where(User.email == _SA_TARGET_EMAIL)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    tm = (await db.execute(
        select(TenantMember).where(TenantMember.user_id == target.id).limit(1)
    )).scalar_one_or_none()
    tenant_id = str(tm.tenant_id) if tm else ""

    token = _secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    db.add(SpecialAccessLink(
        user_id=target.id,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else target.id,
        token_hash=_sa_hash(token),
        created_by=actor,
        purpose=purpose,
        expires_at=expires_at,
        enabled=True,
    ))
    await db.commit()

    # SPEC notifications-revamp T2: 特殊通道開啟 → 系統通知（俾 target 知道）
    # handler session 無 RLS GUC（cron/JWT admin context）→ 寫前 set target
    # tenant+user GUC（is_local — 只影響呢個 transaction）
    try:
        from sqlalchemy import text as _sql_text
        await db.execute(
            _sql_text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
            {"t": tenant_id, "u": str(target.id)},
        )
        from app.services.notification_writer import notify_event
        await notify_event(
            db, target.id if not tenant_id else uuid.UUID(tenant_id), target.id,
            source_module="system",
            title="特殊通道已開啟",
            body=f"Magic link 已建立（{purpose or '無備註'}），{hours:g} 小時後自動關閉。",
            group_key=f"special_access:{expires_at.date()}",
        )
        await db.commit()  # hook 喺主 commit 之後 — 要自己 commit 通知先 persist
    except Exception:
        pass

    base = settings.public_base_url or "https://www.penguincrm.io"
    link = f"{base.rstrip('/')}/login/#sa={token}"
    return {
        "link": link,
        "expires_at": expires_at.isoformat(),
        "created_by": actor,
        "purpose": purpose,
        "note": f"Created by {actor}. Auto-expires in {hours}h.",
    }


@router.post("/special-access/verify", response_model=TokenResponse)
async def verify_special_access(req: dict, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange a special access token for a normal JWT (no MFA).

    Body: {token: str} — from the #sa= fragment in the login URL.
    """
    token = (req.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    row = (await db.execute(
        select(SpecialAccessLink).where(SpecialAccessLink.token_hash == _sa_hash(token))
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid special access token")
    if not row.enabled:
        raise HTTPException(status_code=401, detail="Special access link is disabled")
    if datetime.now(timezone.utc) > row.expires_at:
        row.enabled = False
        await db.commit()
        raise HTTPException(status_code=401, detail="Special access link has expired")

    user = await db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    row.last_used_at = datetime.now(timezone.utc)
    access_token = create_access_token(str(user.id), user.email, user.role, str(row.tenant_id))
    refresh_token_str, expires_at = create_refresh_token(str(user.id))
    db.add(Session(
        user_id=user.id,
        refresh_token=refresh_token_str,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "unknown",
        expires_at=expires_at,
    ))
    await db.commit()
    return _session_response(response, TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        token_type="bearer",
        email=user.email,
        mfa_required=False,
    ))


@router.get("/special-access", response_model=dict)
async def list_special_access(request: Request, db: AsyncSession = Depends(get_db)):
    """List active special access links (GG family status check)."""
    actor, _ = _sa_require_cron_or_jwt(request)
    rows = (await db.execute(
        select(SpecialAccessLink).order_by(SpecialAccessLink.created_at.desc()).limit(20)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        out.append({
            "id": str(r.id),
            "created_by": r.created_by,
            "purpose": r.purpose,
            "enabled": r.enabled,
            "expires_at": r.expires_at.isoformat(),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "expired": now > r.expires_at,
        })
    return {"actor": actor, "links": out}


@router.delete("/special-access", response_model=dict)
async def revoke_special_access(req: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Revoke special access link(s). Body: {token?: str} — 冇 token 就 revoke 全部 active。"""
    actor, _ = _sa_require_cron_or_jwt(request)
    token = (req.get("token") or "").strip()
    if token:
        row = (await db.execute(
            select(SpecialAccessLink).where(SpecialAccessLink.token_hash == _sa_hash(token))
        )).scalar_one_or_none()
        if row:
            row.enabled = False
            await db.commit()
            return {"revoked": 1, "actor": actor}
        return {"revoked": 0, "actor": actor}
    rows = (await db.execute(
        select(SpecialAccessLink).where(SpecialAccessLink.enabled == True)  # noqa: E712
    )).scalars().all()
    for r in rows:
        r.enabled = False
    await db.commit()
    return {"revoked": len(rows), "actor": actor}

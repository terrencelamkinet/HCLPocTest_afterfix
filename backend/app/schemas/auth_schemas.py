from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class LoginRequest(BaseModel):
    email: str
    password: str
    device_token: Optional[str] = None

class MFAVerifyRequest(BaseModel):
    email: str
    otp_code: str
    trust_device: bool = False

class MFASendRequest(BaseModel):
    email: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str = ""
    mfa_required: bool = False
    email: str = ""
    device_token: Optional[str] = None

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""

class RefreshRequest(BaseModel):
    # 2026-09-15 SAST：新前端將 refresh token 放喺 httpOnly cookie，唔再傳 body
    # → 呢個 field 變成 optional（留空 = 由 cookie 拎）。
    refresh_token: str = ""

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    email_verified: bool
    mfa_enabled: bool
    role: str
    created_at: datetime
    # 2026-09-11 (migration 016): Google-derived profile. Optional so older rows —
    # and password-only accounts, which have none — still serialise.
    avatar_url: str | None = None
    locale: str | None = None
    timezone: str | None = None

    model_config = {"from_attributes": True}

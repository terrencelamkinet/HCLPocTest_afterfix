import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base

class User(Base):
    __tablename__ = "nexus_auth_users"
    __table_args__ = {"schema": "nexus_auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(255), default="")
    email_verified = Column(Boolean, default=False)
    mfa_enabled = Column(Boolean, default=True)
    role = Column(String(50), default="member")
    # 2026-09-11: Google Sign-In link (migration 015). Google's stable subject id —
    # durable where an email is not (emails get renamed/re-issued, a sub never
    # does). NULL until the account first signs in with Google; a password-only
    # account stays NULL forever.
    google_sub = Column(String(255), nullable=True, unique=True)
    # 2026-09-11 (migration 016): Google profile claims we now copy across. The ID
    # token carries name/picture/locale but has NO timezone field at all, so the
    # browser supplies that one at login (Intl.DateTimeFormat).
    avatar_url = Column(Text, nullable=True)
    locale = Column(Text, nullable=True)
    timezone = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    tenants = relationship("TenantMember", back_populates="user")

class Session(Base):
    __tablename__ = "nexus_auth_sessions"
    __table_args__ = {"schema": "nexus_auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="CASCADE"), nullable=False)
    refresh_token = Column(String(500), unique=True, nullable=False)
    user_agent = Column(Text)
    ip_address = Column(String(45))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="sessions")

class Tenant(Base):
    __tablename__ = "nexus_auth_tenants"
    __table_args__ = {"schema": "nexus_auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    subdomain = Column(String(255), unique=True, nullable=True)
    settings = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    members = relationship("TenantMember", back_populates="tenant")

class TenantMember(Base):
    __tablename__ = "nexus_auth_tenant_members"
    __table_args__ = {"schema": "nexus_auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), default="member")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="members")
    user = relationship("User", back_populates="tenants")


class SpecialAccessLink(Base):
    """加密 magic link — GG family debug 專用登入通道（terrence_lam tenant）。

    - token 只存 sha256 hash（DB leak 都唔會直接洩漏 token）
    - created_by: 'terrence' | 'gg_family' — Terrence 開 default 3h 自動關；
      GG family 開可以指定時長，用完即 revoke
    - expires_at 過期後 verify 自動 reject
    - revoke / disable 即時生效
    """

    __tablename__ = "special_access_links"
    __table_args__ = {"schema": "nexus_auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    created_by = Column(String(20), default="terrence", nullable=False)  # terrence | gg_family
    purpose = Column(Text, default="", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)

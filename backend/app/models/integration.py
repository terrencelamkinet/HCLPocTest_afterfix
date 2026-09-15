"""Integration & OAuth State models — per-user, per-tenant isolation.
No FK constraints on tenant_id/user_id — the TenantMiddleware + RLS
already enforce isolation, and DB-level FKs prevent testing with
synthetic JWTs."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.db import Base


class Integration(Base):
    """Per-user integration connection record."""
    __tablename__ = "nexus_integrations"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    provider_display = Column(String(255), nullable=False)
    status = Column(String(50), default="disconnected")
    config = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class OAuthState(Base):
    """Temporary OAuth state — CSRF protection + user binding."""
    __tablename__ = "nexus_oauth_states"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    state = Column(String(255), unique=True, nullable=False, index=True)
    redirect_uri = Column(String(500), default="")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

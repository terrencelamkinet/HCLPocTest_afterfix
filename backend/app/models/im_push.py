"""IM Push — delivery preferences + push audit log (Tri-Daily Briefing module)."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db import Base

DEFAULT_SLOTS = {"morning": True, "noon": True, "evening": True}
DEFAULT_QUIET_HOURS = {"start": "22:00", "end": "08:00"}


class IMDeliveryPref(Base):
    """Per-user per-channel delivery preferences for AI briefing pushes.

    Row is auto-created (enabled=True, Default ON) when a channel is bound —
    frictionless onboarding per AI_Personal_CRM_TriDaily_Strategy.md §2.1.
    """

    __tablename__ = "im_delivery_prefs"
    __table_args__ = {"schema": "nexus_crm"}

    tenant_id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    channel = Column(String(20), primary_key=True)  # whatsapp | telegram
    enabled = Column(Boolean, default=True, nullable=False)
    slots = Column(JSONB, default=lambda: dict(DEFAULT_SLOTS), nullable=False)
    weekend_mute = Column(Boolean, default=True, nullable=False)
    quiet_hours = Column(JSONB, default=lambda: dict(DEFAULT_QUIET_HOURS), nullable=False)
    tz = Column(String(64), default="Asia/Hong_Kong", nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PushLog(Base):
    """Audit trail for every push attempt (sent / failed / skipped)."""

    __tablename__ = "push_log"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    slot = Column(String(20), nullable=False)  # morning | noon | evening
    status = Column(String(20), nullable=False)  # sent | failed | skipped
    reason = Column(String(120), default="")  # e.g. weekend_mute / quiet_hours / no_mapping
    error = Column(Text, default="")
    # 2026-09-10 (migration 013): record WHAT was pushed, not just THAT something
    # was. Without these, push history is unreadable — see KB-014.
    body = Column(Text, nullable=True)
    chat_id = Column(Text, nullable=True)
    message_id = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

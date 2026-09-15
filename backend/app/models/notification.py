"""
Notifications Module — Platform-level Foundation.

Core tables for multi-tenant notification system.
Designed for Agent API Bridge integration.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Integer, Numeric, ARRAY, Time
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    source_module = Column(String(100))
    source_record_type = Column(String(50))
    source_record_id = Column(UUID(as_uuid=True))

    title = Column(String(255), nullable=False)
    body = Column(Text)
    priority = Column(String(20), default="NORMAL")  # CRITICAL / HIGH / NORMAL / LOW
    group_key = Column(String(150))  # dedup/collapse key

    # AI fields
    is_ai_generated = Column(Boolean, default=False)
    ai_rationale = Column(Text)
    ai_confidence = Column(Numeric(5, 2))
    generated_by_agent_id = Column(String(100))

    # Status
    status = Column(String(20), default="UNREAD", index=True)  # UNREAD / READ / DISMISSED
    read_at = Column(DateTime(timezone=True))
    snoozed_until = Column(DateTime(timezone=True))

    # Agent ack tracking
    agent_ack_at = Column(DateTime(timezone=True))
    agent_ack_channel = Column(String(30))

    action_url = Column(String(500))

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = ({"schema": "nexus_crm"},)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    module_key = Column(String(100), nullable=False)
    channels = Column(ARRAY(String), default=["IN_APP"])
    priority_min = Column(String(20), default="NORMAL")
    is_muted = Column(Boolean, default=False)
    digest = Column(String(20), default="REALTIME")
    quiet_start = Column(Time)
    quiet_end = Column(Time)
    timezone = Column(String(50), default="Asia/Hong_Kong")
    agent_push_enabled = Column(Boolean, default=True)
    agent_digest_enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

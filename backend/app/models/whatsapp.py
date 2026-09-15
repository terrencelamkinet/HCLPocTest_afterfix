"""WhatsApp integration models — wa_id ↔ user mapping + OTP store."""
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, Boolean, DateTime, JSON, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base


class WhatsAppMapping(Base):
    """Bind a WhatsApp number to a platform user."""
    __tablename__ = "nexus_whatsapp_mappings"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    wa_id = Column(String(50), unique=True, nullable=False, index=True)       # WhatsApp ID (phone)
    phone_number = Column(String(20), nullable=False)                          # Display phone
    status = Column(String(20), default="active")                              # active | disconnected
    config = Column(JSON, default=dict)                                        # extra metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class WhatsAppOTP(Base):
    """One-time password for account linking — auto-expires."""
    __tablename__ = "nexus_whatsapp_otps"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wa_id = Column(String(50), nullable=False, index=True)
    otp = Column(String(10), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

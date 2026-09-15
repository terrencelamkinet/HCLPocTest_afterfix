"""Telegram integration models — bot binding + connection state.

Binding model follows the WhatsAppMapping pattern. The bot token (secret) is
NOT stored plaintext here — it lives in nexus_ai.ai_channel_credentials
(ChannelCredential, "encrypted at app level"), see telegram_service.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.db import Base


class TelegramBotMapping(Base):
    """Bind a Telegram bot + chat to a platform user (the "connection")."""

    __tablename__ = "nexus_telegram_mappings"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    bot_username = Column(String(100), nullable=False)          # e.g. MyNexusCrmBot
    bot_token = Column(String(64), unique=True, nullable=False) # opaque reference only (not plaintext secret)
    chat_id = Column(String(64), nullable=False)                # telegram chat_id to deliver to
    status = Column(String(20), default="active")               # active | disconnected
    config = Column(JSON, default=dict)                         # extra metadata (bot info etc.)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

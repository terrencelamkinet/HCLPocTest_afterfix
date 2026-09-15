"""OAuth client ID settings — stored in DB so admins can configure via UI."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from app.db import Base


class OAuthClientSetting(Base):
    """Platform-level OAuth client ID per provider."""
    __tablename__ = "nexus_oauth_client_settings"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(String(100), primary_key=True)  # provider key: 'google_calendar', 'slack', etc.
    client_id = Column(String(500), default="")
    client_secret = Column(String(500), default="")
    scopes = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

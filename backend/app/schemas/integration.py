"""Integration schemas — per-user, per-tenant."""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: UUID
    provider: str
    provider_display: str
    status: str
    config: dict
    metadata_: dict
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class IntegrationUpdate(BaseModel):
    status: Optional[str] = None
    config: Optional[dict] = None
    metadata_: Optional[dict] = None


class OAuthStateResponse(BaseModel):
    state: str
    redirect_uri: str
    provider: str

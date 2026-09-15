from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AISession(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "nexus_ai"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    team_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nexus_ai.agents.id", ondelete="SET NULL"), nullable=True)
    model_profile_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nexus_ai.model_profiles.id", ondelete="SET NULL"), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(50), default="chat")
    channel: Mapped[str] = mapped_column(String(20), default="portal", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    action_requests = relationship("ActionRequest", back_populates="session", cascade="all, delete-orphan")

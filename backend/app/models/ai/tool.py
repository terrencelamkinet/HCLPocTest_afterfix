from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = {"schema": "nexus_ai"}

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tool_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    tool_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_module: Mapped[str] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

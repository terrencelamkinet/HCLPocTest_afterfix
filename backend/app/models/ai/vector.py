"""SQLAlchemy models for vector document storage.

These map to the ``nexus_ai.vector_documents`` and
``nexus_ai.vector_document_chunks`` tables, which store CRM record
content as chunked + embedded vectors for RAG retrieval.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# pgvector Python package may not be installed at import time;
# use a simple ARRAY(Float) fallback if the Vector type is unavailable.
try:
    from pgvector.sqlalchemy import Vector as _Vector

    VectorType = _Vector
except ImportError:
    from sqlalchemy import ARRAY, Float

    VectorType = ARRAY(Float)  # type: ignore[misc]
    _make_vector = lambda dim: ARRAY(Float)  # noqa: E731
else:
    _make_vector = lambda dim: _Vector(dim)  # noqa: E731


class VectorDocument(Base):
    """A logical document that groups related chunks for a single CRM record."""

    __tablename__ = "vector_documents"
    __table_args__ = {"schema": "nexus_ai"}

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=True)
    _metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    chunks = relationship(
        "VectorDocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="VectorDocumentChunk.chunk_index",
    )


class VectorDocumentChunk(Base):
    """A single chunk of a vector document with its embedding."""

    __tablename__ = "vector_document_chunks"
    __table_args__ = {"schema": "nexus_ai"}

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nexus_ai.vector_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(_make_vector(1536), nullable=True)  # type: ignore[valid-type]
    _metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    document = relationship("VectorDocument", back_populates="chunks")

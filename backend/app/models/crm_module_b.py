"""Module B — Sales & Deals ORM models.

Entities:
  deal_pipelines, deal_stages, deals, products,
  deal_line_items, quotes, quote_items, sales_reports
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, ForeignKey,
    Integer, Date, Numeric, JSON, ARRAY, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base


class DealPipeline(Base):
    __tablename__ = "deal_pipelines"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    stages = relationship("DealStage", back_populates="pipeline", order_by="DealStage.order_index")


class DealStage(Base):
    __tablename__ = "deal_stages"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deal_pipelines.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    probability = Column(Integer, default=0)
    order_index = Column(Integer, nullable=False)
    color = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    pipeline = relationship("DealPipeline", back_populates="stages")


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(Text, nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    pipeline_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deal_pipelines.id", ondelete="SET NULL"))
    stage_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deal_stages.id", ondelete="SET NULL"))
    amount = Column(Numeric(15, 2), default=0)
    currency = Column(Text, default="HKD")
    probability = Column(Integer)
    expected_close_date = Column(Date)
    status = Column(Text, default="open")  # open, won, lost, stalled, abandoned
    lost_reason = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    notes = Column(Text)
    tags = Column(ARRAY(Text), default=lambda: [])
    custom_fields = Column(JSON, default=lambda: {})
    won_at = Column(DateTime(timezone=True))
    lost_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    line_items = relationship("DealLineItem", back_populates="deal")
    quotes = relationship("Quote", back_populates="deal")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    unit_price = Column(Numeric(15, 2), default=0)
    currency = Column(Text, default="HKD")
    category = Column(Text)
    sku = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DealLineItem(Base):
    __tablename__ = "deal_line_items"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deals.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.products.id", ondelete="SET NULL"))
    description = Column(Text, nullable=False)
    quantity = Column(Numeric(10, 2), default=1)
    unit_price = Column(Numeric(15, 2), nullable=False)
    total_price = Column(Numeric(15, 2))  # GENERATED ALWAYS AS in DB; set by app for insert
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    deal = relationship("Deal", back_populates="line_items")


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deals.id", ondelete="CASCADE"), nullable=False)
    quote_number = Column(Text, nullable=False)
    status = Column(Text, default="draft")  # draft, sent, accepted, rejected, expired
    valid_until = Column(Date)
    subtotal = Column(Numeric(15, 2), default=0)
    discount_percent = Column(Numeric(5, 2), default=0)
    discount_amount = Column(Numeric(15, 2), default=0)
    tax_percent = Column(Numeric(5, 2), default=0)
    tax_amount = Column(Numeric(15, 2), default=0)
    total = Column(Numeric(15, 2), default=0)
    notes = Column(Text)
    terms = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    deal = relationship("Deal", back_populates="quotes")
    items = relationship("QuoteItem", back_populates="quote")


class QuoteItem(Base):
    __tablename__ = "quote_items"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    quote_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.quotes.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.products.id", ondelete="SET NULL"))
    description = Column(Text, nullable=False)
    quantity = Column(Numeric(10, 2), default=1)
    unit_price = Column(Numeric(15, 2), nullable=False)
    total_price = Column(Numeric(15, 2), default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    quote = relationship("Quote", back_populates="items")


class SalesReport(Base):
    __tablename__ = "sales_reports"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    report_type = Column(Text, nullable=False)  # pipeline_velocity, forecast, win_rate, deal_aging, sales_activity
    parameters = Column(JSON, default=lambda: {})
    result = Column(JSON, default=lambda: {})
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    generated_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))


class ModuleSetting(Base):
    """Tenant-level module enable/disable configuration."""
    __tablename__ = "module_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_key", name="uq_tenant_module"),
        {"schema": "nexus_crm"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    module_key = Column(Text, nullable=False)
    enabled = Column(Boolean, default=False)
    settings = Column(JSON, default=lambda: {})
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

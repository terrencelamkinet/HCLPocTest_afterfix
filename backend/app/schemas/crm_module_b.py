"""Module B — Sales & Deals Pydantic schemas.

Each entity has Create, Update, and Response schemas.
Shared ListResponse[T] is imported from crm.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


# ===========================================================================
# DEAL PIPELINES
# ===========================================================================

class DealPipelineCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False


class DealPipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None


class DealPipelineResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# DEAL STAGES
# ===========================================================================

class DealStageCreate(BaseModel):
    pipeline_id: UUID
    name: str
    probability: Optional[int] = 0
    order_index: int
    color: Optional[str] = None


class DealStageUpdate(BaseModel):
    name: Optional[str] = None
    probability: Optional[int] = None
    order_index: Optional[int] = None
    color: Optional[str] = None


class DealStageResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    pipeline_id: UUID
    name: str
    probability: int = 0
    order_index: int
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# DEALS
# ===========================================================================

class DealCreate(BaseModel):
    name: str
    company_id: UUID
    contact_id: Optional[UUID] = None
    pipeline_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    amount: Decimal = Decimal("0")
    currency: str = "HKD"
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    status: str = "open"
    lost_reason: Optional[str] = None
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None
    tags: list[str] = []
    custom_fields: dict = {}


class DealUpdate(BaseModel):
    name: Optional[str] = None
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    pipeline_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    status: Optional[str] = None
    lost_reason: Optional[str] = None
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    custom_fields: Optional[dict] = None


class DealResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    company_id: UUID
    contact_id: Optional[UUID] = None
    pipeline_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    amount: Decimal = Decimal("0")
    currency: str = "HKD"
    probability: Optional[int] = None
    expected_close_date: Optional[date] = None
    status: str = "open"
    lost_reason: Optional[str] = None
    owner_id: Optional[UUID] = None
    notes: Optional[str] = None
    tags: list[str] = []
    custom_fields: dict = {}
    won_at: Optional[datetime] = None
    lost_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# PRODUCTS
# ===========================================================================

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    unit_price: Decimal = Decimal("0")
    currency: str = "HKD"
    category: Optional[str] = None
    sku: Optional[str] = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    unit_price: Optional[Decimal] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    sku: Optional[str] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    unit_price: Decimal = Decimal("0")
    currency: str = "HKD"
    category: Optional[str] = None
    sku: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# DEAL LINE ITEMS
# ===========================================================================

class DealLineItemCreate(BaseModel):
    deal_id: UUID
    product_id: Optional[UUID] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal


class DealLineItemUpdate(BaseModel):
    product_id: Optional[UUID] = None
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None


class DealLineItemResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    deal_id: UUID
    product_id: Optional[UUID] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    total_price: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# QUOTES
# ===========================================================================

class QuoteCreate(BaseModel):
    deal_id: UUID
    quote_number: str
    status: str = "draft"
    valid_until: Optional[date] = None
    subtotal: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    notes: Optional[str] = None
    terms: Optional[str] = None


class QuoteUpdate(BaseModel):
    status: Optional[str] = None
    valid_until: Optional[date] = None
    subtotal: Optional[Decimal] = None
    discount_percent: Optional[Decimal] = None
    discount_amount: Optional[Decimal] = None
    tax_percent: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total: Optional[Decimal] = None
    notes: Optional[str] = None
    terms: Optional[str] = None


class QuoteResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    deal_id: UUID
    quote_number: str
    status: str = "draft"
    valid_until: Optional[date] = None
    subtotal: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    discount_amount: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    notes: Optional[str] = None
    terms: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# QUOTE ITEMS
# ===========================================================================

class QuoteItemCreate(BaseModel):
    quote_id: UUID
    product_id: Optional[UUID] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    total_price: Decimal = Decimal("0")


class QuoteItemUpdate(BaseModel):
    product_id: Optional[UUID] = None
    description: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None


class QuoteItemResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    quote_id: UUID
    product_id: Optional[UUID] = None
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    total_price: Decimal = Decimal("0")
    created_at: datetime

    class Config:
        from_attributes = True


# ===========================================================================
# SALES REPORTS
# ===========================================================================

class SalesReportCreate(BaseModel):
    report_type: str
    parameters: dict = {}
    result: dict = {}
    generated_by: Optional[UUID] = None


class SalesReportResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    report_type: str
    parameters: dict = {}
    result: dict = {}
    generated_at: datetime
    generated_by: Optional[UUID] = None

    class Config:
        from_attributes = True


# ===========================================================================
# MODULE SETTINGS
# ===========================================================================

class ModuleSettingCreate(BaseModel):
    module_key: str
    enabled: bool = False
    settings: dict = {}


class ModuleSettingUpdate(BaseModel):
    enabled: Optional[bool] = None
    settings: Optional[dict] = None


class ModuleSettingResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    module_key: str
    enabled: bool = False
    settings: dict = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

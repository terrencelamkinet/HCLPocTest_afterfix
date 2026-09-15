"""Module B — Sales & Deals CRUD router.

Same flat path structure under /api/v1/crm as Module A:
  GET    /{entity}          → list (paginated, filterable)
  POST   /{entity}          → create
  GET    /{entity}/{id}     → read
  PATCH  /{entity}/{id}     → partial update
  DELETE /{entity}/{id}     → delete (204)

Entity types:
  deal-pipelines, deal-stages, deals, products,
  deal-line-items, quotes, quote-items, sales-reports

Every write operation records an ActivityLog row in the nextus_crm schema.
"""

from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.crm import ActivityLog
from app.models.crm_module_b import (
    DealPipeline,
    DealStage,
    Deal,
    Product,
    DealLineItem,
    Quote,
    QuoteItem,
    SalesReport,
)
from app.schemas.crm import ListResponse
from app.schemas.crm_module_b import (
    DealPipelineCreate,
    DealPipelineResponse,
    DealPipelineUpdate,
    DealStageCreate,
    DealStageResponse,
    DealStageUpdate,
    DealCreate,
    DealResponse,
    DealUpdate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    DealLineItemCreate,
    DealLineItemResponse,
    DealLineItemUpdate,
    QuoteCreate,
    QuoteResponse,
    QuoteUpdate,
    QuoteItemCreate,
    QuoteItemResponse,
    QuoteItemUpdate,
    SalesReportCreate,
    SalesReportResponse,
)

router = APIRouter(prefix="/api/v1/crm", tags=["crm-module-b"])

# ---------------------------------------------------------------------------
# Activity-log helper (same pattern as Module A)
# ---------------------------------------------------------------------------


async def _log_activity(
    db: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID,
    summary: str | None = None,
    changes: dict | None = None,
    workspace_id: UUID | None = None,
) -> None:
    # 2026-09-08 fix（member 500）: 任何 falsy actor_id → None（column nullable — 存 NULL）
    actor_id = actor_id if actor_id else None
    # Fallback: resolve tenant's default workspace when caller didn't pass one
    # (update/delete handlers historically omit it → NOT NULL violation on
    # activity_log). Same resolution path as get_tenant_session.
    if workspace_id is None:
        try:
            row = await db.execute(
                text("SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :tid ORDER BY created_at ASC LIMIT 1"),
                {"tid": str(tenant_id)},
            )
            wid = row.scalar_one_or_none()
            if wid:
                workspace_id = UUID(str(wid))
        except Exception:
            pass
    entry = ActivityLog(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        changes=changes,
    )
    db.add(entry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tenant_id(request: Request) -> UUID:
    # If token was valid but expired, return 401 so frontend refresh flow kicks in
    if getattr(request.state, "auth_status", "") == "expired":
        raise HTTPException(status_code=401, detail="Token expired")
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(status_code=403, detail="Tenant not identified")
    return tid


def _get_user_id(request: Request) -> UUID | None:
    # 2026-09-08 fix（member 500）: middleware 設 ""（冇 user claim）→ 正規化 None（caller 安全）
    uid = getattr(request.state, "user_id", None)
    if not uid:
        return None
    return uid


# ===========================================================================
# DEAL PIPELINES
# ===========================================================================


@router.get("/deal-pipelines", response_model=ListResponse[DealPipelineResponse])
async def list_deal_pipelines(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(DealPipeline).where(DealPipeline.tenant_id == tenant_id)

    if search:
        base = base.where(DealPipeline.name.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(DealPipeline.name).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/deal-pipelines", response_model=DealPipelineResponse, status_code=201)
async def create_deal_pipeline(
    request: Request,
    body: DealPipelineCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = DealPipeline(
        tenant_id=tenant_id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="deal_pipeline", entity_id=obj.id,
        summary=f"Created deal pipeline '{obj.name}'",
    )

    await db.refresh(obj)
    return obj


@router.get("/deal-pipelines/{obj_id}", response_model=DealPipelineResponse)
async def get_deal_pipeline(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DealPipeline).where(DealPipeline.id == obj_id, DealPipeline.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal pipeline not found")
    return obj


@router.patch("/deal-pipelines/{obj_id}", response_model=DealPipelineResponse)
async def update_deal_pipeline(
    request: Request,
    obj_id: UUID,
    body: DealPipelineUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealPipeline).where(DealPipeline.id == obj_id, DealPipeline.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal pipeline not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="deal_pipeline", entity_id=obj.id,
        summary=f"Updated deal pipeline '{obj.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/deal-pipelines/{obj_id}", status_code=204)
async def delete_deal_pipeline(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealPipeline).where(DealPipeline.id == obj_id, DealPipeline.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal pipeline not found")

    name = obj.name
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="deal_pipeline", entity_id=obj_id,
        summary=f"Deleted deal pipeline '{name}'",
    )

    return None


# ===========================================================================
# DEAL STAGES
# ===========================================================================


@router.get("/deal-stages", response_model=ListResponse[DealStageResponse])
async def list_deal_stages(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    pipeline_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(DealStage).where(DealStage.tenant_id == tenant_id)

    if pipeline_id:
        base = base.where(DealStage.pipeline_id == pipeline_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(DealStage.order_index).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/deal-stages", response_model=DealStageResponse, status_code=201)
async def create_deal_stage(
    request: Request,
    body: DealStageCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = DealStage(
        tenant_id=tenant_id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="deal_stage", entity_id=obj.id,
        summary=f"Created deal stage '{obj.name}'",
    )

    await db.refresh(obj)
    return obj


@router.get("/deal-stages/{obj_id}", response_model=DealStageResponse)
async def get_deal_stage(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DealStage).where(DealStage.id == obj_id, DealStage.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal stage not found")
    return obj


@router.patch("/deal-stages/{obj_id}", response_model=DealStageResponse)
async def update_deal_stage(
    request: Request,
    obj_id: UUID,
    body: DealStageUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealStage).where(DealStage.id == obj_id, DealStage.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal stage not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="deal_stage", entity_id=obj.id,
        summary=f"Updated deal stage '{obj.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/deal-stages/{obj_id}", status_code=204)
async def delete_deal_stage(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealStage).where(DealStage.id == obj_id, DealStage.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal stage not found")

    name = obj.name
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="deal_stage", entity_id=obj_id,
        summary=f"Deleted deal stage '{name}'",
    )

    return None


# ===========================================================================
# DEALS
# ===========================================================================


@router.get("/deals", response_model=ListResponse[DealResponse])
async def list_deals(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    stage_id: UUID | None = None,
    pipeline_id: UUID | None = None,
    company_id: UUID | None = None,
    owner_id: UUID | None = None,
    contact_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Deal).where(Deal.tenant_id == tenant_id)

    if search:
        base = base.where(
            or_(
                Deal.name.ilike(f"%{search}%"),
                Deal.notes.ilike(f"%{search}%"),
            )
        )
    if status:
        base = base.where(Deal.status == status)
    if stage_id:
        base = base.where(Deal.stage_id == stage_id)
    if pipeline_id:
        base = base.where(Deal.pipeline_id == pipeline_id)
    if company_id:
        base = base.where(Deal.company_id == company_id)
    if owner_id:
        base = base.where(Deal.owner_id == owner_id)
    if contact_id:
        base = base.where(Deal.contact_id == contact_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Deal.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/deals", response_model=DealResponse, status_code=201)
async def create_deal(
    request: Request,
    body: DealCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    data = body.model_dump()

    # Auto-set win/lost timestamps
    now = datetime.now(timezone.utc)
    if data.get("status") == "won":
        data["won_at"] = now
    elif data.get("status") == "lost":
        data["lost_at"] = now

    obj = Deal(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        **data,
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="deal", entity_id=obj.id,
        summary=f"Created deal '{obj.name}'",
        workspace_id=workspace_id,
    )

    await db.refresh(obj)
    return obj


@router.get("/deals/{obj_id}", response_model=DealResponse)
async def get_deal(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Deal).where(Deal.id == obj_id, Deal.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal not found")
    return obj


@router.patch("/deals/{obj_id}", response_model=DealResponse)
async def update_deal(
    request: Request,
    obj_id: UUID,
    body: DealUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Deal).where(Deal.id == obj_id, Deal.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    # Auto-set win/lost timestamps on status change
    if "status" in body.model_dump(exclude_unset=True):
        now = datetime.now(timezone.utc)
        if body.status == "won" and not obj.won_at:
            obj.won_at = now
        elif body.status == "lost" and not obj.lost_at:
            obj.lost_at = now

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="deal", entity_id=obj.id,
        summary=f"Updated deal '{obj.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/deals/{obj_id}", status_code=204)
async def delete_deal(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Deal).where(Deal.id == obj_id, Deal.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal not found")

    name = obj.name
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="deal", entity_id=obj_id,
        summary=f"Deleted deal '{name}'",
    )

    return None


# ===========================================================================
# PRODUCTS
# ===========================================================================


@router.get("/products", response_model=ListResponse[ProductResponse])
async def list_products(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    category: str | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Product).where(Product.tenant_id == tenant_id)

    if search:
        base = base.where(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
            )
        )
    if category:
        base = base.where(Product.category == category)
    if is_active is not None:
        base = base.where(Product.is_active == is_active)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Product.name).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    request: Request,
    body: ProductCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = Product(
        tenant_id=tenant_id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="product", entity_id=obj.id,
        summary=f"Created product '{obj.name}'",
    )

    await db.refresh(obj)
    return obj


@router.get("/products/{obj_id}", response_model=ProductResponse)
async def get_product(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Product).where(Product.id == obj_id, Product.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Product not found")
    return obj


@router.patch("/products/{obj_id}", response_model=ProductResponse)
async def update_product(
    request: Request,
    obj_id: UUID,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Product).where(Product.id == obj_id, Product.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Product not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="product", entity_id=obj.id,
        summary=f"Updated product '{obj.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/products/{obj_id}", status_code=204)
async def delete_product(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Product).where(Product.id == obj_id, Product.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Product not found")

    name = obj.name
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="product", entity_id=obj_id,
        summary=f"Deleted product '{name}'",
    )

    return None


# ===========================================================================
# DEAL LINE ITEMS
# ===========================================================================


@router.get("/deal-line-items", response_model=ListResponse[DealLineItemResponse])
async def list_deal_line_items(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    deal_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(DealLineItem).where(DealLineItem.tenant_id == tenant_id)

    if deal_id:
        base = base.where(DealLineItem.deal_id == deal_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(DealLineItem.created_at).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/deal-line-items", response_model=DealLineItemResponse, status_code=201)
async def create_deal_line_item(
    request: Request,
    body: DealLineItemCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    data = body.model_dump()
    # Auto-calculate total_price
    data["total_price"] = data["quantity"] * data["unit_price"]

    obj = DealLineItem(
        tenant_id=tenant_id,
        **data,
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="deal_line_item", entity_id=obj.id,
        summary=f"Created line item for deal {obj.deal_id}",
    )

    await db.refresh(obj)
    return obj


@router.get("/deal-line-items/{obj_id}", response_model=DealLineItemResponse)
async def get_deal_line_item(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DealLineItem).where(DealLineItem.id == obj_id, DealLineItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal line item not found")
    return obj


@router.patch("/deal-line-items/{obj_id}", response_model=DealLineItemResponse)
async def update_deal_line_item(
    request: Request,
    obj_id: UUID,
    body: DealLineItemUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealLineItem).where(DealLineItem.id == obj_id, DealLineItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal line item not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    # Recalculate total_price if quantity or unit_price changed
    updated = body.model_dump(exclude_unset=True)
    if "quantity" in updated or "unit_price" in updated:
        obj.total_price = obj.quantity * obj.unit_price

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="deal_line_item", entity_id=obj.id,
        summary=f"Updated line item for deal {obj.deal_id}",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/deal-line-items/{obj_id}", status_code=204)
async def delete_deal_line_item(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(DealLineItem).where(DealLineItem.id == obj_id, DealLineItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Deal line item not found")

    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="deal_line_item", entity_id=obj_id,
        summary=f"Deleted line item {obj_id}",
    )

    return None


# ===========================================================================
# QUOTES
# ===========================================================================


@router.get("/quotes", response_model=ListResponse[QuoteResponse])
async def list_quotes(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    deal_id: UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Quote).where(Quote.tenant_id == tenant_id)

    if deal_id:
        base = base.where(Quote.deal_id == deal_id)
    if status:
        base = base.where(Quote.status == status)
    if search:
        base = base.where(Quote.quote_number.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Quote.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/quotes", response_model=QuoteResponse, status_code=201)
async def create_quote(
    request: Request,
    body: QuoteCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    obj = Quote(
        tenant_id=tenant_id,
        created_by=user_id,
        **body.model_dump(),
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="quote", entity_id=obj.id,
        summary=f"Created quote '{obj.quote_number}'",
        workspace_id=workspace_id,
    )

    await db.refresh(obj)
    return obj


@router.get("/quotes/{obj_id}", response_model=QuoteResponse)
async def get_quote(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Quote).where(Quote.id == obj_id, Quote.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote not found")
    return obj


@router.patch("/quotes/{obj_id}", response_model=QuoteResponse)
async def update_quote(
    request: Request,
    obj_id: UUID,
    body: QuoteUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Quote).where(Quote.id == obj_id, Quote.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    obj.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="quote", entity_id=obj.id,
        summary=f"Updated quote '{obj.quote_number}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/quotes/{obj_id}", status_code=204)
async def delete_quote(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Quote).where(Quote.id == obj_id, Quote.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote not found")

    qn = obj.quote_number
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="quote", entity_id=obj_id,
        summary=f"Deleted quote '{qn}'",
    )

    return None


# ===========================================================================
# QUOTE ITEMS
# ===========================================================================


@router.get("/quote-items", response_model=ListResponse[QuoteItemResponse])
async def list_quote_items(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    quote_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(QuoteItem).where(QuoteItem.tenant_id == tenant_id)

    if quote_id:
        base = base.where(QuoteItem.quote_id == quote_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(QuoteItem.created_at).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/quote-items", response_model=QuoteItemResponse, status_code=201)
async def create_quote_item(
    request: Request,
    body: QuoteItemCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    data = body.model_dump()
    # Auto-calculate total_price if not provided
    if not data.get("total_price") or data["total_price"] == 0:
        data["total_price"] = data["quantity"] * data["unit_price"]

    obj = QuoteItem(
        tenant_id=tenant_id,
        **data,
    )
    db.add(obj)
    await db.flush()

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="quote_item", entity_id=obj.id,
        summary=f"Created quote item for quote {obj.quote_id}",
    )

    await db.refresh(obj)
    return obj


@router.get("/quote-items/{obj_id}", response_model=QuoteItemResponse)
async def get_quote_item(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(QuoteItem).where(QuoteItem.id == obj_id, QuoteItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote item not found")
    return obj


@router.patch("/quote-items/{obj_id}", response_model=QuoteItemResponse)
async def update_quote_item(
    request: Request,
    obj_id: UUID,
    body: QuoteItemUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(QuoteItem).where(QuoteItem.id == obj_id, QuoteItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote item not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
        changes[field] = str(value)

    # Recalculate total_price if quantity or unit_price changed
    updated = body.model_dump(exclude_unset=True)
    if "quantity" in updated or "unit_price" in updated or "total_price" in updated:
        # manual override or auto-calc
        if "total_price" not in updated:
            obj.total_price = obj.quantity * obj.unit_price

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="quote_item", entity_id=obj.id,
        summary=f"Updated quote item for quote {obj.quote_id}",
        changes=changes,
    )

    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/quote-items/{obj_id}", status_code=204)
async def delete_quote_item(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(QuoteItem).where(QuoteItem.id == obj_id, QuoteItem.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Quote item not found")

    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="quote_item", entity_id=obj_id,
        summary=f"Deleted quote item {obj_id}",
    )

    return None


# ===========================================================================
# SALES REPORTS
# ===========================================================================


@router.get("/sales-reports", response_model=ListResponse[SalesReportResponse])
async def list_sales_reports(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    report_type: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(SalesReport).where(SalesReport.tenant_id == tenant_id)

    if report_type:
        base = base.where(SalesReport.report_type == report_type)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(SalesReport.generated_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/sales-reports", response_model=SalesReportResponse, status_code=201)
async def create_sales_report(
    request: Request,
    body: SalesReportCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = SalesReport(
        tenant_id=tenant_id,
        generated_by=user_id or body.generated_by,
        report_type=body.report_type,
        parameters=body.parameters,
        result=body.result,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


@router.get("/sales-reports/{obj_id}", response_model=SalesReportResponse)
async def get_sales_report(
    request: Request,
    obj_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(SalesReport).where(SalesReport.id == obj_id, SalesReport.tenant_id == tenant_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Sales report not found")
    return obj

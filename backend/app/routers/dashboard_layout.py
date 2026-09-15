"""Dashboard Layout Router — save/load card order per user."""

import json
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.dashboard_layout import DashboardLayout

router = APIRouter(prefix="/api/v1/dashboard")


def _tid(request: Request) -> UUID:
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(403, "Tenant not identified")
    return tid


def _uid(request: Request) -> UUID:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "User not authenticated")
    return uid


@router.get("/layout")
async def get_layout(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    row = (
        await db.execute(
            select(DashboardLayout).where(
                DashboardLayout.tenant_id == tenant_id,
                DashboardLayout.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if not row:
        return {"layout": {}}
    try:
        return {"layout": json.loads(row.layout_json)}
    except json.JSONDecodeError:
        return {"layout": {}}


@router.put("/layout")
async def save_layout(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    layout_json = json.dumps(payload.get("layout", {}), ensure_ascii=False)

    row = (
        await db.execute(
            select(DashboardLayout).where(
                DashboardLayout.tenant_id == tenant_id,
                DashboardLayout.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if row:
        row.layout_json = layout_json
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(DashboardLayout(
            tenant_id=tenant_id,
            user_id=user_id,
            layout_json=layout_json,
        ))

    await db.commit()
    return {"status": "ok"}

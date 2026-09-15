"""Module Settings — tenant-level module enable/disable router.

Endpoints:
  GET    /api/v1/crm/module-settings          → list all for current tenant
  PUT    /api/v1/crm/module-settings/{key}    → upsert (create or update)
  POST   /api/v1/crm/module-settings/{key}/toggle  → toggle enabled
"""

from uuid import UUID, NAMESPACE_OID, uuid5
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.crm_module_b import ModuleSetting
from app.schemas.crm import ListResponse
from app.schemas.crm_module_b import (
    ModuleSettingCreate,
    ModuleSettingResponse,
    ModuleSettingUpdate,
)

router = APIRouter(prefix="/api/v1/crm", tags=["crm-module-settings"])


# ---------------------------------------------------------------------------
# Hidden (force-disabled) modules
# ---------------------------------------------------------------------------
# Modules removed from the product UI for now (e.g. the Deals/Sales module was
# temporarily hidden at the owner's request). The feature code, tables and data
# are untouched and additive — we simply force these off so they cannot be
# re-enabled accidentally, while keeping it a one-line revert for the future.
#
# To re-open a module later: remove its key from this set (and un-hide it in
# SettingsPage.moduleDefs). No data migration needed.
HIDDEN_MODULES: set[str] = {
    "sales",  # Deals pipeline — hidden 2026-08-17, re-open later on request
}


def _module_visible(key: str) -> bool:
    return key not in HIDDEN_MODULES


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


# ===========================================================================
# MODULE SETTINGS
# ===========================================================================


@router.get("/module-settings", response_model=list[ModuleSettingResponse])
async def list_module_settings(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List all module settings for the current tenant."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(ModuleSetting).where(ModuleSetting.tenant_id == tenant_id)
    )
    rows = result.scalars().all()

    # Force hidden modules to disabled regardless of any stored value. Also
    # synthèse a disabled row for a hidden module even when the tenant has no
    # row yet, so the frontend sees an explicit `enabled=false` (frontends
    # default to *visible* when a module key is absent) — otherwise the hidden
    # module would still appear in nav/quick-actions.
    out: list[ModuleSettingResponse] = []
    seen: set[str] = set()
    for row in rows:
        if _module_visible(row.module_key):
            out.append(row)
        else:
            row.enabled = False
            out.append(row)
        seen.add(row.module_key)
    for key in HIDDEN_MODULES:
        if key not in seen:
            out.append(
                ModuleSettingResponse(
                    id=uuid5(NAMESPACE_OID, f"hidden-{key}"),  # stable synthetic id (not persisted)
                    tenant_id=tenant_id,
                    module_key=key,
                    enabled=False,
                    settings={},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
    return out


@router.put("/module-settings/{module_key}", response_model=ModuleSettingResponse)
async def upsert_module_setting(
    request: Request,
    module_key: str,
    body: ModuleSettingCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create or update a module setting for the current tenant."""
    tenant_id = _get_tenant_id(request)

    # Hidden modules cannot be enabled through the API — keeps the deal module
    # off even if a client/UI tries to force it back on.
    if not _module_visible(module_key):
        raise HTTPException(status_code=409, detail="This module is temporarily hidden")

    # Check if setting already exists
    result = await db.execute(
        select(ModuleSetting).where(
            ModuleSetting.tenant_id == tenant_id,
            ModuleSetting.module_key == module_key,
        )
    )
    obj = result.scalar_one_or_none()

    if obj:
        # Update
        if body.enabled is not None:
            obj.enabled = body.enabled
        if body.settings:
            obj.settings = body.settings
        obj.updated_at = datetime.now(timezone.utc)
    else:
        # Create
        obj = ModuleSetting(
            tenant_id=tenant_id,
            module_key=body.module_key,
            enabled=body.enabled,
            settings=body.settings,
        )
        db.add(obj)

    await db.flush()
    await db.refresh(obj)
    return obj


@router.post("/module-settings/{module_key}/toggle", response_model=ModuleSettingResponse)
async def toggle_module_setting(
    request: Request,
    module_key: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Toggle the enabled flag for a module setting. Creates with enabled=True if not exists."""
    tenant_id = _get_tenant_id(request)

    # Hidden modules cannot be toggled back on.
    if not _module_visible(module_key):
        raise HTTPException(status_code=409, detail="This module is temporarily hidden")

    result = await db.execute(
        select(ModuleSetting).where(
            ModuleSetting.tenant_id == tenant_id,
            ModuleSetting.module_key == module_key,
        )
    )
    obj = result.scalar_one_or_none()

    if obj:
        obj.enabled = not obj.enabled
        obj.updated_at = datetime.now(timezone.utc)
    else:
        obj = ModuleSetting(
            tenant_id=tenant_id,
            module_key=module_key,
            enabled=True,
            settings={},
        )
        db.add(obj)

    await db.flush()
    await db.refresh(obj)
    return obj

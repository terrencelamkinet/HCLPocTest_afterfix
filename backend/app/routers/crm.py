"""
CRM Module A — FastAPI CRUD router.

Flat path structure under /api/v1/crm:
  GET    /{entity}          → list (paginated, filterable)
  POST   /{entity}          → create
  GET    /{entity}/{id}     → read
  PATCH  /{entity}/{id}     → partial update
  DELETE /{entity}/{id}     → delete (204)

Entity types: companies, contacts, touchpoints, tasks, name-cards, notes, activity-log, tags

Every write operation (create / update / delete) records an ActivityLog row.
"""

from uuid import UUID
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import re
import json

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query, BackgroundTasks
from sqlalchemy import delete, func, select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ColumnProperty, selectinload

from app.db import get_tenant_session
from app.services.note_mentions import MENTION_ENTITY_TABLES, mentions_ready, sync_note_mentions
from app.models.crm import (
    ActivityLog,
    Company,
    Contact,
    ContactProject,
    NameCard,
    NameCardTag,
    Note,
    NoteLink,
    NoteRevision,
    UserPreference,
    NoteTag,
    Project,
    ProjectCalendarEvent,
    Tag,
    Task,
    Touchpoint,
    TouchpointParticipant,
    TouchpointCompany,
    UserFieldOption,
)
from app.models.crm_module_b import Deal, DealStage
from app.services import namecard_agents, namecard_llm
from app.schemas.crm import (
    ActivityLogCreate,
    ActivityLogResponse,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
    ContactCreate,
    ContactProjectCreate,
    ContactProjectResponse,
    ContactResponse,
    ContactUpdate,
    ListResponse,
    NameCardCreate,
    NameCardResponse,
    NameCardResolveRequest,
    NameCardUpdate,
    NoteCreate,
    NoteResponse,
    NoteLinkCreate,
    NoteLinkRef,
    NoteTagAttach,
    NoteTagRef,
    NoteUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ProjectCalendarEventCreate,
    ProjectCalendarEventResponse,
    ProjectCalendarEventUpdate,
    TagCreate,
    TagResponse,
    TagUpdate,
    NameCardTagResponse,
    NameCardTagCreate,
    NameCardTagUpdate,
    NameCardTagMergeRequest,
    NameCardTagCleanupResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    TouchpointCreate,
    TouchpointResponse,
    TouchpointUpdate,
    FieldOptionCreate,
    FieldOptionResponse,
)

router = APIRouter(prefix="/api/v1/crm", tags=["crm"])

# ---------------------------------------------------------------------------
# Activity‑log helper — called by every write endpoint
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
    # 2026-09-08 fix（member 500）: 任何 falsy actor_id（""/None）→ None（column nullable — 存 NULL）
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
# Generic helpers
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
    # 2026-09-08 fix（Terrence: member create company HTTP 500）: tenant middleware 將
    # 冇 user claim 嘅 token 設 state.user_id = ""（唔係 None）→ UUID column 收到 ""
    # → asyncpg invalid UUID ''。正規化 "" → None — caller 全部安全。
    uid = getattr(request.state, "user_id", None)
    if not uid:
        return None
    return uid


# ---------------------------------------------------------------------------
# Custom Field helpers — EAV batch load + write
# ---------------------------------------------------------------------------

async def _load_custom_fields(
    db: AsyncSession,
    tenant_id: UUID,
    module: str,
    record_ids: list[UUID],
) -> dict[str, dict[str, Any]]:
    """Batch-load custom fields for a list of record IDs.

    Returns {record_id_str: {field_key: value, ...}}
    """
    if not record_ids:
        return {}

    result = await db.execute(
        text("""
            SELECT v.record_id, d.field_key, d.field_type,
                   v.value_text, v.value_number, v.value_boolean, v.value_date, v.value_json
            FROM nexus_crm.get_custom_fields(:tenant_id, :module, :record_ids) v
            JOIN nexus_crm.custom_field_definitions d ON d.field_key = v.field_key
                AND d.module_name = :module2 AND d.tenant_id = :tenant_id2
        """),
        {
            "tenant_id": tenant_id,
            "module": module,
            "record_ids": record_ids,
            "module2": module,
            "tenant_id2": tenant_id,
        },
    )
    rows = result.all()  # force fetch before closing
    cf_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row.record_id)
        if rid not in cf_map:
            cf_map[rid] = {}
        val = _extract_cf_value(row)
        if val is not None:
            cf_map[rid][row.field_key] = val
    return cf_map


def _extract_cf_value(row) -> Any:
    """Pick the right value column based on field_type."""
    ft = row.field_type
    if ft == "boolean":
        return row.value_boolean
    elif ft == "number":
        return row.value_number
    elif ft == "date":
        return row.value_date.isoformat() if row.value_date else None
    elif ft in ("select", "multi_select"):
        return row.value_text or row.value_json
    elif ft == "file":
        return row.value_json
    else:
        return row.value_text


async def _apply_task_cf(
    db: AsyncSession, tenant_id: UUID, task_id: UUID, custom_fields: dict[str, Any]
) -> None:
    """Write custom field values for a task (upsert via PG function)."""
    if not custom_fields:
        return
    # Get definition_id for each field_key
    result = await db.execute(
        text("""
            SELECT id, field_key FROM nexus_crm.custom_field_definitions
            WHERE tenant_id = :tenant_id AND module_name = 'tasks'
              AND field_key = ANY(:keys)
        """),
        {"tenant_id": tenant_id, "keys": list(custom_fields.keys())},
    )
    defs = {row.field_key: row.id for row in result}
    for key, val in custom_fields.items():
        def_id = defs.get(key)
        if not def_id:
            continue
        # Map value to correct type column
        params = {
            "p_tenant_id": tenant_id,
            "p_definition_id": def_id,
            "p_record_id": task_id,
            "p_value_text": None,
            "p_value_number": None,
            "p_value_boolean": None,
            "p_value_date": None,
            "p_value_json": None,
        }
        if isinstance(val, bool):
            params["p_value_boolean"] = val
        elif isinstance(val, (int, float)):
            params["p_value_number"] = val
        elif isinstance(val, (list, dict)):
            params["p_value_json"] = val
        elif isinstance(val, str):
            # Try date parse
            try:
                from datetime import date as d_type
                # just store as text for now
                params["p_value_text"] = val
            except Exception:
                params["p_value_text"] = val
        else:
            params["p_value_text"] = str(val) if val is not None else None

        await db.execute(
            text("""
                SELECT nexus_crm.upsert_custom_field_value(
                    :p_tenant_id, :p_definition_id, :p_record_id,
                    :p_value_text, :p_value_number, :p_value_boolean,
                    :p_value_date::timestamptz, :p_value_json::jsonb
                )
            """),
            params,
        )


async def _delete_task_cf(
    db: AsyncSession, tenant_id: UUID, task_id: UUID
) -> None:
    """Delete all custom field values for a task."""
    await db.execute(
        text("SELECT nexus_crm.delete_custom_fields_for_record(:tid, 'tasks', :rid)"),
        {"tid": tenant_id, "rid": task_id},
    )


# ===========================================================================
# COMPANIES
# ===========================================================================


@router.get("/companies", response_model=ListResponse[CompanyResponse])
async def list_companies(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    industry: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Company).where(Company.tenant_id == tenant_id)

    if search:
        base = base.where(Company.name.ilike(f"%{search}%"))
    if industry:
        base = base.where(Company.industry == industry)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Company.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


# ── v3: custom option system（industry / category / status searchable combobox）──
# module → {field: column} mapping（v3 範圍）
_FIELD_OPTION_COLUMNS = {
    "company": {"industry": "industry", "category": "category", "status": "status"},
    "contact": {"status": "status"},
    "task": {"status": "status"},
    "project": {"status": "status"},
}
# module → model
_FIELD_OPTION_MODELS = {
    "company": Company,
    "contact": Contact,
    "task": Task,
    "project": Project,
}


@router.get("/field-options")
async def get_field_options(
    request: Request,
    module: str = Query(...),
    field: str = Query(...),
    db: AsyncSession = Depends(get_tenant_session),
):
    """分頁欄位（industry/category/status）嘅 options。

    v3: tenant-scoped distinct values（DISTINCT 現有值 = implicit persistence）。
    v5: 加返當前 user 嘅 custom options（user_field_options table，per-user 管轄）。
    Response: {"options": [...], "userOptions": [{id, value, label}...]}
      - options: tenant distinct values（value == label）
      - userOptions: 只返 user_id == request.state.user_id 嘅 custom rows（有 id 先可以 delete）
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    cols = _FIELD_OPTION_COLUMNS.get(module)
    model = _FIELD_OPTION_MODELS.get(module)
    if cols is None or model is None or field not in cols:
        # 2026-09-11: "no tenant-scoped custom options" is a VALID answer, not an
        # error. Not every module/field has one — the touchpoint `type` is a fixed
        # enum that lives in the frontend config. Raising 404 here made every modal
        # open on such a field fire a failed request (the caller catches it and
        # falls back silently, so the only symptom was a 404 polluting the browser
        # console and network log on /touchpoints). Return the empty shape instead.
        return {"options": [], "userOptions": []}

    # tenant distinct values（v3 原有行為唔變）
    col = getattr(model, cols[field])
    q = (
        select(col)
        .where(model.tenant_id == tenant_id)
        .where(col.is_not(None))
        .where(col != "")
        .distinct()
        .order_by(col)
        .limit(100)
    )
    rows = (await db.execute(q)).scalars().all()
    options = [
        {"value": v, "label": v}
        for v in rows
        if v is not None
    ]

    # v5: per-user custom options（淨返自己 user_id 嘅 rows）
    user_options: list[dict[str, Any]] = []
    if user_id is not None:
        uq = (
            select(UserFieldOption)
            .where(UserFieldOption.tenant_id == tenant_id)
            .where(UserFieldOption.user_id == user_id)
            .where(UserFieldOption.module == module)
            .where(UserFieldOption.field == field)
            .order_by(UserFieldOption.created_at.asc())
        )
        urows = (await db.execute(uq)).scalars().all()
        user_options = [
            {"id": str(u.id), "value": u.value, "label": u.value}
            for u in urows
        ]

    return {"options": options, "userOptions": user_options}


@router.post("/field-options", status_code=201)
async def create_field_option(
    body: FieldOptionCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """v5: 新增 per-user custom option。

    (tenant_id, user_id, module, field, value) unique — duplicate → 409。
    value 空 / 全 whitespace → 422。module/field 唔喺 mapping → 404。
    """
    value = body.value
    if value is None or not value.strip():
        raise HTTPException(status_code=422, detail="value must not be empty")
    value = value.strip()

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    cols = _FIELD_OPTION_COLUMNS.get(body.module)
    model = _FIELD_OPTION_MODELS.get(body.module)
    if cols is None or model is None or body.field not in cols:
        raise HTTPException(status_code=404, detail=f"No field option mapping for module={body.module} field={body.field}")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # duplicate check（unique constraint 兜底）
    dup = (
        select(UserFieldOption.id)
        .where(UserFieldOption.tenant_id == tenant_id)
        .where(UserFieldOption.user_id == user_id)
        .where(UserFieldOption.module == body.module)
        .where(UserFieldOption.field == body.field)
        .where(UserFieldOption.value == value)
        .limit(1)
    )
    existing = (await db.execute(dup)).scalar_one_or_none()
    if existing is not None:
        row = existing[0] if isinstance(existing, tuple) else existing
        raise HTTPException(status_code=409, detail=f"Field option already exists: {value}")

    option = UserFieldOption(
        tenant_id=tenant_id,
        user_id=user_id,
        module=body.module,
        field=body.field,
        value=value,
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)
    return FieldOptionResponse(id=option.id, value=option.value, label=option.value)


@router.delete("/field-options/{option_id}", status_code=204)
async def delete_field_option(
    option_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """v5: 刪除自己嘅 custom option。

    只可以刪 user_id == request.state.user_id + tenant match 嘅 row — 其他人嘅 → 404。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    q = (
        select(UserFieldOption)
        .where(UserFieldOption.id == option_id)
        .where(UserFieldOption.tenant_id == tenant_id)
        .where(UserFieldOption.user_id == user_id)
        .limit(1)
    )
    option = (await db.execute(q)).scalar_one_or_none()
    if option is None:
        raise HTTPException(status_code=404, detail="Field option not found")
    await db.delete(option)
    await db.commit()
    return None


@router.get("/companies/duplicate-check")
async def duplicate_check_companies(
    request: Request,
    name: str = Query(""),
    limit: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Fuzzy-match company names → possible duplicates (tenant-scoped).

    Returns top matches with similarity > 0.5 (difflib ratio on normalised name).
    """
    import difflib
    tenant_id = _get_tenant_id(request)
    q = (name or "").strip()
    if not q or len(q) < 2:
        return {"matches": []}
    norm = q.lower()

    rows = (
        await db.execute(
            select(Company.id, Company.name)
            .where(Company.tenant_id == tenant_id)
            .limit(2000)
        )
    ).fetchall()

    matches = []
    for rid, rname in rows:
        if not rname:
            continue
        rn = rname.lower()
        sim = difflib.SequenceMatcher(None, norm, rn).ratio()
        if sim >= 0.5:
            matches.append({"id": str(rid), "name": rname, "similarity": round(sim, 3)})
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return {"matches": matches[:limit]}


@router.get("/contacts/duplicate-check")
async def duplicate_check_contacts(
    request: Request,
    name: str = Query(""),
    limit: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Fuzzy-match contact names → possible duplicates (tenant-scoped).

    Returns top matches with similarity > 0.5 (difflib ratio on normalised name).
    """
    import difflib
    tenant_id = _get_tenant_id(request)
    q = (name or "").strip()
    if not q or len(q) < 2:
        return {"matches": []}
    norm = q.lower()

    rows = (
        await db.execute(
            select(Contact.id, Contact.name)
            .where(Contact.tenant_id == tenant_id)
            .limit(2000)
        )
    ).fetchall()

    matches = []
    for rid, rname in rows:
        if not rname:
            continue
        rn = rname.lower()
        sim = difflib.SequenceMatcher(None, norm, rn).ratio()
        if sim >= 0.5:
            matches.append({"id": str(rid), "name": rname, "similarity": round(sim, 3)})
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return {"matches": matches[:limit]}



@router.post("/companies", response_model=CompanyResponse, status_code=201)
async def create_company(
    request: Request,
    body: CompanyCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    company = Company(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        **body.model_dump(),
    )
    db.add(company)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="company",
        entity_id=company.id,
        summary=f"Created company '{company.name}'",
        workspace_id=workspace_id,
    )

    await db.refresh(company)
    return company


@router.get("/companies/{company_id}", response_model=CompanyResponse)
async def get_company(
    request: Request,
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    d = {col.name: getattr(company, col.name) for col in company.__table__.columns}
    # SPEC detail-v3: company KPI counts（open projects / contacts / overdue tasks）
    try:
        row = (await db.execute(
            text("""
              SELECT
                (SELECT count(*) FROM nexus_crm.projects p
                  WHERE p.company_id = :cid AND p.tenant_id = :tid AND p.status NOT IN ('cancelled','done','completed')) AS open_projects,
                (SELECT count(*) FROM nexus_crm.contacts c
                  WHERE c.company_id = :cid AND c.tenant_id = :tid) AS contacts,
                (SELECT count(*) FROM nexus_crm.tasks t
                  WHERE t.company_id = :cid AND t.tenant_id = :tid AND t.status NOT IN ('done','cancelled')
                    AND t.due_date IS NOT NULL AND t.due_date < CURRENT_DATE) AS overdue_tasks
            """), {"cid": company_id, "tid": tenant_id})).mappings().first()
        if row:
            d['active_projects_count'] = row.open_projects or 0
            d['contacts_count'] = row.contacts or 0
            d['overdue_tasks_count'] = row.overdue_tasks or 0
    except Exception as e:
        print(f"[company-kpi] counts query failed: {type(e).__name__}: {e}", flush=True)
    return d


@router.patch("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(
    request: Request,
    company_id: UUID,
    body: CompanyUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
        changes[field] = str(value)

    company.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="company",
        entity_id=company.id,
        summary=f"Updated company '{company.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(company)
    return company


@router.delete("/companies/{company_id}", status_code=204)
async def delete_company(
    request: Request,
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    name = company.name
    await db.delete(company)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="company",
        entity_id=company_id,
        summary=f"Deleted company '{name}'",
    )

    return None


# ===========================================================================
# CONTACTS
# ===========================================================================


@router.get("/contacts", response_model=ListResponse[ContactResponse])
async def list_contacts(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    contact_type: str | None = None,
    grade: str | None = None,
    company_id: UUID | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Contact).where(Contact.tenant_id == tenant_id)

    if search:
        base = base.where(
            or_(
                Contact.name.ilike(f"%{search}%"),
                Contact.email.ilike(f"%{search}%"),
            )
        )
    if status:
        base = base.where(Contact.status == status)
    if contact_type:
        base = base.where(Contact.contact_type == contact_type)
    if grade:
        base = base.where(Contact.grade == grade)
    if company_id:
        base = base.where(Contact.company_id == company_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    sort_col = getattr(Contact, sort_by, None)
    if sort_col is None or not isinstance(sort_col.property, ColumnProperty):
        sort_col = Contact.created_at
    order = sort_col.asc() if sort_order == "asc" else sort_col.desc()
    items_q = base.options(selectinload(Contact.company)).order_by(order).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    # Build response with resolved company names
    items = []
    for c in rows:
        d = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        d['company'] = {"id": str(c.company.id), "name": c.company.name} if c.company else None
        items.append(d)

    return ListResponse(items=items, total=total)


@router.post("/contacts", response_model=ContactResponse | list[ContactResponse], status_code=201)
async def create_contact(
    request: Request,
    body: ContactCreate | list[ContactCreate],
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create one contact (object) or several (array) — 2026-09-11 multi-add.

    Accepts either a single ContactCreate object (legacy callers unchanged) or a
    JSON array of them. Multi-add is ALL-OR-NOTHING: rows are flushed inside one
    transaction; any failure rolls the whole batch back (get_tenant_session
    rollbacks on exception) so no partial batch is silently kept. Each created
    row is audited exactly like a single create. Returns the created record(s)
    in input order (object for object input, array for array input).
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    is_batch = isinstance(body, list)
    payloads = list(body) if is_batch else [body]
    if not payloads:
        raise HTTPException(status_code=422, detail="At least one contact is required")

    created: list[Contact] = []
    for payload in payloads:
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            **payload.model_dump(),
        )
        db.add(contact)
        await db.flush()  # assigns id; failure aborts the whole batch

        await _log_activity(
            db,
            tenant_id=tenant_id,
            actor_id=user_id,
            action="created",
            entity_type="contact",
            entity_id=contact.id,
            summary=f"Created contact '{contact.name}'",
            workspace_id=workspace_id,
        )
        created.append(contact)

    # Re-query with company loaded (avoids MissingGreenlet on response serialization)
    ids = [c.id for c in created]
    result = await db.execute(
        select(Contact).options(selectinload(Contact.company)).where(Contact.id.in_(ids))
    )
    by_id = {c.id: c for c in result.scalars().all()}
    out = []
    for cid in ids:  # preserve input order
        contact = by_id[cid]
        d = {col.name: getattr(contact, col.name) for col in contact.__table__.columns}
        d['company'] = {'id': str(contact.company.id), 'name': contact.company.name} if contact.company else None
        out.append(d)
    return out if is_batch else out[0]


@router.get("/contacts/{contact_id}", response_model=ContactResponse)
async def get_contact(
    request: Request,
    contact_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Contact).options(selectinload(Contact.company)).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    # Build response with resolved company name
    d = {col.name: getattr(contact, col.name) for col in contact.__table__.columns}
    d['company'] = {"id": str(contact.company.id), "name": contact.company.name} if contact.company else None
    # SPEC detail-v3: KPI counts（open tasks / touchpoints / projects / next follow-up）
    try:
        row = (await db.execute(
            text("""
              SELECT
                (SELECT count(*) FROM nexus_crm.tasks t
                  WHERE t.contact_id = :cid AND t.tenant_id = :tid AND t.status NOT IN ('done','cancelled')) AS open_tasks,
                (SELECT count(*) FROM nexus_crm.touchpoints tp
                  WHERE tp.tenant_id = :tid AND (tp.contact_id = :cid OR EXISTS (
                    SELECT 1 FROM nexus_crm.touchpoint_participants tpp
                    WHERE tpp.touchpoint_id = tp.id AND tpp.contact_id = :cid AND tpp.tenant_id = :tid))) AS touchpoints,
                (SELECT count(*) FROM nexus_crm.contact_projects cp
                  WHERE cp.contact_id = :cid AND cp.tenant_id = :tid) AS projects,
                (SELECT min(t.due_date) FROM nexus_crm.tasks t
                  WHERE t.contact_id = :cid AND t.tenant_id = :tid AND t.status NOT IN ('done','cancelled') AND t.due_date IS NOT NULL) AS next_follow_up
            """), {"cid": contact_id, "tid": tenant_id})).mappings().first()
        if row:
            d['open_tasks_count'] = row.open_tasks or 0
            d['touchpoints_count'] = row.touchpoints or 0
            d['projects_count'] = row.projects or 0
            d['next_follow_up'] = str(row.next_follow_up) if row.next_follow_up else None
    except Exception as e:
        print(f"[KPI-debug] contact counts query failed: {type(e).__name__}: {e}", flush=True)
    return d


@router.patch("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    request: Request,
    contact_id: UUID,
    body: ContactUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
        changes[field] = str(value)

    contact.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="contact",
        entity_id=contact.id,
        summary=f"Updated contact '{contact.name}'",
        changes=changes,
    )

    await db.flush()
    # Reload with company eager-loaded (same pattern as GET) — the lazy
    # `contact.company` relationship would otherwise 500 during response
    # serialization (MissingGreenlet in async session) → inline status/select
    # edits in the table view could not save (2026-08-11).
    result = await db.execute(
        select(Contact).options(selectinload(Contact.company)).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one()
    d = {col.name: getattr(contact, col.name) for col in contact.__table__.columns}
    d['company'] = {"id": str(contact.company.id), "name": contact.company.name} if contact.company else None
    return d


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(
    request: Request,
    contact_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    name = contact.name
    await db.delete(contact)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="contact",
        entity_id=contact_id,
        summary=f"Deleted contact '{name}'",
    )

    return None


# ===========================================================================
# CONTACT PROJECTS (contact <-> deal junction)
# ===========================================================================


@router.get(
    "/contacts/{contact_id}/projects",
    response_model=ListResponse[ContactProjectResponse],
)
async def list_contact_projects(
    request: Request,
    contact_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)

    # Verify contact exists
    contact_result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    if not contact_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Contact not found")

    # Join contact_projects with deals and deal_stages
    from sqlalchemy import join

    j = (
        select(
            ContactProject,
            Deal.name.label("project_name"),
            Deal.amount.label("amount"),
            DealStage.name.label("stage_name"),
            DealStage.probability.label("probability"),
        )
        .select_from(
            join(
                ContactProject,
                Deal,
                ContactProject.project_id == Deal.id,
            ).join(
                DealStage,
                Deal.stage_id == DealStage.id,
                isouter=True,
            )
        )
        .where(
            ContactProject.tenant_id == tenant_id,
            ContactProject.contact_id == contact_id,
        )
        .order_by(ContactProject.created_at.desc())
    )

    rows = (await db.execute(j)).all()

    count_q = select(func.count()).select_from(
        select(ContactProject)
        .where(
            ContactProject.tenant_id == tenant_id,
            ContactProject.contact_id == contact_id,
        )
        .subquery()
    )
    total = (await db.execute(count_q)).scalar() or 0

    items = []
    for row in rows:
        item = ContactProjectResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            contact_id=row.contact_id,
            project_id=row.project_id,
            role=row.role,
            created_at=row.created_at,
            project_name=row.project_name,
            amount=float(row.amount) if row.amount is not None else None,
            stage_name=row.stage_name,
            probability=row.probability,
        )
        items.append(item)

    return ListResponse(items=items, total=total)


@router.post(
    "/contacts/{contact_id}/projects",
    response_model=ContactProjectResponse,
    status_code=201,
)
async def create_contact_project(
    request: Request,
    contact_id: UUID,
    body: ContactProjectCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    # Verify contact exists
    contact_result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = contact_result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Verify project (deal) exists
    deal_result = await db.execute(
        select(Deal).where(Deal.id == body.project_id, Deal.tenant_id == tenant_id)
    )
    deal = deal_result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check for existing link
    existing = await db.execute(
        select(ContactProject).where(
            ContactProject.tenant_id == tenant_id,
            ContactProject.contact_id == contact_id,
            ContactProject.project_id == body.project_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Contact is already linked to this project")

    link = ContactProject(
        tenant_id=tenant_id,
        contact_id=contact_id,
        project_id=body.project_id,
        role=body.role,
    )
    db.add(link)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="contact_project",
        entity_id=link.id,
        summary=f"Linked contact '{contact.name}' to project '{deal.name}'",
    )

    await db.refresh(link)
    return ContactProjectResponse(
        id=link.id,
        tenant_id=link.tenant_id,
        contact_id=link.contact_id,
        project_id=link.project_id,
        role=link.role,
        created_at=link.created_at,
    )


@router.delete(
    "/contacts/{contact_id}/projects/{project_id}",
    status_code=204,
)
async def delete_contact_project(
    request: Request,
    contact_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(ContactProject).where(
            ContactProject.tenant_id == tenant_id,
            ContactProject.contact_id == contact_id,
            ContactProject.project_id == project_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Contact-project link not found")

    await db.delete(link)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="contact_project",
        entity_id=link.id,
        summary="Unlinked contact from project",
    )

    return None


# ===========================================================================
# TOUCHPOINTS
# ===========================================================================


@router.get("/touchpoints/location-suggest")
async def suggest_locations(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_tenant_session),
):
    """Location autocomplete — CRM addresses (companies + contacts) + touchpoint
    location history, tenant-scoped (2026-09-09)."""
    tenant_id = _get_tenant_id(request)
    if not q.strip():
        return {"items": []}
    like = f"%{q.strip()}%"
    rows = await db.execute(
        text(
            "SELECT DISTINCT loc FROM ("
            "  SELECT address AS loc FROM nexus_crm.companies WHERE tenant_id = :t AND address IS NOT NULL AND address ILIKE :q "
            "  UNION "
            "  SELECT address AS loc FROM nexus_crm.contacts WHERE tenant_id = :t AND address IS NOT NULL AND address ILIKE :q "
            "  UNION "
            "  SELECT location AS loc FROM nexus_crm.touchpoints WHERE tenant_id = :t AND location IS NOT NULL AND location ILIKE :q "
            ") x WHERE NULLIF(trim(loc), '') IS NOT NULL LIMIT 8"
        ),
        {"t": tenant_id, "q": like},
    )
    return {"items": [r[0] for r in rows.fetchall()]}


# ---------------------------------------------------------------------------
# A+B location autocomplete (2026-09-11, operator decision: "A+b")
#   B = local: company/contact addresses + touchpoint location history.
#       Tenant-specific and free, so it always runs and its hits come FIRST.
#   A = Google Places Autocomplete (New): fills the gaps local cannot cover.
#       Auth uses a service-account-free API key kept in backend/.secrets/
#       (gitignored) so the key never reaches the browser.
# Any Places problem (quota, network, bad key, disabled API) degrades silently to
# B — the Location field must never break because a third party is unhappy.
# ---------------------------------------------------------------------------
_PLACES_KEY_FILE = Path(__file__).resolve().parents[2] / ".secrets" / "google_places_api_key.txt"


def _places_api_key() -> str | None:
    try:
        return _PLACES_KEY_FILE.read_text().strip() or None
    except Exception:
        return None


async def _local_location_rows(db: AsyncSession, tenant_id: Any, q: str, limit: int) -> list[str]:
    rows = await db.execute(
        text(
            "SELECT DISTINCT loc FROM ("
            "  SELECT address AS loc FROM nexus_crm.companies WHERE tenant_id = :t AND address IS NOT NULL AND address ILIKE :q "
            "  UNION "
            "  SELECT address AS loc FROM nexus_crm.contacts WHERE tenant_id = :t AND address IS NOT NULL AND address ILIKE :q "
            "  UNION "
            "  SELECT location AS loc FROM nexus_crm.touchpoints WHERE tenant_id = :t AND location IS NOT NULL AND location ILIKE :q "
            ") x WHERE NULLIF(trim(loc), '') IS NOT NULL LIMIT :lim"
        ),
        {"t": tenant_id, "q": f"%{q.strip()}%", "lim": limit},
    )
    return [r[0] for r in rows.fetchall()]


async def _places_location_rows(q: str, session_token: str | None, limit: int) -> list[str]:
    key = _places_api_key()
    if not key or not q.strip():
        return []
    body: dict[str, Any] = {
        "input": q.strip(),
        "includedRegionCodes": ["hk"],
        "languageCode": "en",
    }
    if session_token:
        body["sessionToken"] = session_token
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                "https://places.googleapis.com/v1/places:autocomplete",
                headers={"X-Goog-Api-Key": key, "Content-Type": "application/json"},
                json=body,
            )
        if r.status_code != 200:
            return []
        out: list[str] = []
        for s in (r.json().get("suggestions") or []):
            t = ((s.get("placePrediction") or {}).get("text") or {}).get("text")
            if t:
                out.append(t)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


@router.get("/touchpoints/place-suggest")
async def suggest_place_locations(
    request: Request,
    q: str = "",
    session: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    """A+B location autocomplete. Local hits first (free, tenant-specific), then
    Google Places to fill the remaining slots. Returns [{value, source}]."""
    tenant_id = _get_tenant_id(request)
    if not q.strip():
        return {"items": []}
    local = await _local_location_rows(db, tenant_id, q, 8)
    seen = {l.strip().lower() for l in local if l}
    items = [{"value": l, "source": "local"} for l in local if l]
    if len(items) < 8:
        for p in await _places_location_rows(q, session, 8 - len(items)):
            k = p.strip().lower()
            if k and k not in seen:
                seen.add(k)
                items.append({"value": p, "source": "google"})
    return {"items": items}


@router.get("/touchpoints", response_model=ListResponse[TouchpointResponse])
async def list_touchpoints(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    contact_id: UUID | None = None,
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Touchpoint).where(Touchpoint.tenant_id == tenant_id)

    if contact_id:
        # SPEC contact-assoc-fix: touchpoint 關連有兩套 — direct contact_id column（單一主要聯絡人）
        # 同 touchpoint_participants join（multi-participant）。list filter 之前只用 participants → direct 記錄揾唔到。
        # 而家 OR 兩者 — count（KPI）同 list（tab/timeline）一致。
        base = base.where(
            or_(
                Touchpoint.contact_id == contact_id,
                Touchpoint.id.in_(
                    select(TouchpointParticipant.touchpoint_id).where(
                        TouchpointParticipant.contact_id == contact_id,
                        TouchpointParticipant.tenant_id == tenant_id,
                    )
                ),
            )
        )

    if company_id:
        # 011: company 關聯有兩套 — company_id（主要）+ touchpoint_companies join（multi）— OR 兩者
        base = base.where(
            or_(
                Touchpoint.company_id == company_id,
                Touchpoint.id.in_(
                    select(TouchpointCompany.touchpoint_id).where(
                        TouchpointCompany.company_id == company_id,
                        TouchpointCompany.tenant_id == tenant_id,
                    )
                ),
            )
        )

    if search:
        base = base.where(Touchpoint.title.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.options(selectinload(Touchpoint.company), selectinload(Touchpoint.participants), selectinload(Touchpoint.companies)).order_by(Touchpoint.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    items = []
    for t in rows:
        d = {col.name: getattr(t, col.name) for col in t.__table__.columns}
        d['company'] = {'id': str(t.company.id), 'name': t.company.name} if t.company else None
        d['participants'] = [{'id': str(p.id), 'name': p.name} for p in t.participants]
        d['companies'] = [{'id': str(c.id), 'name': c.name} for c in t.companies]
        items.append(d)

    return ListResponse(items=items, total=total)


@router.post("/touchpoints", response_model=TouchpointResponse, status_code=201)
async def create_touchpoint(
    request: Request,
    body: TouchpointCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    contact_ids = list(body.contact_ids or []) or (body.participants or [])  # participants alias (2026-09-09)
    data = body.model_dump(exclude={"contact_ids", "participants", "companies"})
    # Multi-company (011): companies 全列 → 第一個 = 主要 company_id
    company_list = list(body.companies or [])
    if company_list:
        data["company_id"] = company_list[0]
    touchpoint = Touchpoint(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=user_id,
        **data,
    )
    db.add(touchpoint)
    await db.flush()

    # Create participant records
    for cid in contact_ids:
        participant = TouchpointParticipant(
            tenant_id=tenant_id,
            touchpoint_id=touchpoint.id,
            contact_id=cid,
        )
        db.add(participant)

    # Multi-company (011): join rows（company_id 已設主要 = company_list[0]）
    for cid in company_list:
        if cid == touchpoint.company_id:
            continue
        db.add(TouchpointCompany(
            tenant_id=tenant_id,
            touchpoint_id=touchpoint.id,
            company_id=cid,
        ))

    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="touchpoint",
        entity_id=touchpoint.id,
        summary=f"Created touchpoint '{touchpoint.title}'",
        workspace_id=workspace_id,
    )

    await db.refresh(touchpoint)
    # Re-query with participants loaded
    result = await db.execute(
        select(Touchpoint).options(selectinload(Touchpoint.company), selectinload(Touchpoint.participants), selectinload(Touchpoint.companies)).where(Touchpoint.id == touchpoint.id)
    )
    t = result.scalar_one()
    d = {col.name: getattr(t, col.name) for col in t.__table__.columns}
    d['company'] = {'id': str(t.company.id), 'name': t.company.name} if t.company else None
    d['participants'] = [{'id': str(p.id), 'name': p.name} for p in t.participants]
    d['companies'] = [{'id': str(c.id), 'name': c.name} for c in t.companies]
    return d


@router.get("/touchpoints/{touchpoint_id}", response_model=TouchpointResponse)
async def get_touchpoint(
    request: Request,
    touchpoint_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Touchpoint).options(selectinload(Touchpoint.company), selectinload(Touchpoint.participants), selectinload(Touchpoint.companies)).where(
            Touchpoint.id == touchpoint_id, Touchpoint.tenant_id == tenant_id
        )
    )
    touchpoint = result.scalar_one_or_none()
    if not touchpoint:
        raise HTTPException(status_code=404, detail="Touchpoint not found")
    d = {col.name: getattr(touchpoint, col.name) for col in touchpoint.__table__.columns}
    d['company'] = {'id': str(touchpoint.company.id), 'name': touchpoint.company.name} if touchpoint.company else None
    d['participants'] = [{'id': str(p.id), 'name': p.name} for p in touchpoint.participants]
    return d


@router.patch("/touchpoints/{touchpoint_id}", response_model=TouchpointResponse)
async def update_touchpoint(
    request: Request,
    touchpoint_id: UUID,
    body: TouchpointUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Touchpoint).where(
            Touchpoint.id == touchpoint_id, Touchpoint.tenant_id == tenant_id
        )
    )
    touchpoint = result.scalar_one_or_none()
    if not touchpoint:
        raise HTTPException(status_code=404, detail="Touchpoint not found")

    changes = {}
    data = body.model_dump(exclude_unset=True)
    contact_ids = data.pop("contact_ids", None)
    if contact_ids is None:
        contact_ids = data.pop("participants", None)  # participants alias (2026-09-09)
    # Multi-company (011): companies 全列 → replace join + 主要 company_id
    company_list = data.pop("companies", None)
    if company_list is not None:
        if company_list:
            data["company_id"] = company_list[0]
        else:
            data["company_id"] = None
    for field, value in data.items():
        setattr(touchpoint, field, value)
        changes[field] = str(value)

    # Sync participants if contact_ids provided
    if contact_ids is not None:
        # Remove existing participants
        await db.execute(
            text("DELETE FROM nexus_crm.touchpoint_participants WHERE touchpoint_id = :tp_id AND tenant_id = :t_id"),
            {"tp_id": touchpoint_id, "t_id": tenant_id},
        )
        # Add new participants
        for cid in contact_ids:
            participant = TouchpointParticipant(
                tenant_id=tenant_id,
                touchpoint_id=touchpoint.id,
                contact_id=cid,
            )
            db.add(participant)

    # Sync companies (011) if provided — replace join rows
    if company_list is not None:
        await db.execute(
            text("DELETE FROM nexus_crm.touchpoint_companies WHERE touchpoint_id = :tp_id AND tenant_id = :t_id"),
            {"tp_id": touchpoint_id, "t_id": tenant_id},
        )
        for cid in company_list:
            if cid == touchpoint.company_id:
                continue
            db.add(TouchpointCompany(
                tenant_id=tenant_id,
                touchpoint_id=touchpoint.id,
                company_id=cid,
            ))

    touchpoint.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="touchpoint",
        entity_id=touchpoint.id,
        summary=f"Updated touchpoint '{touchpoint.title}'",
        changes=changes,
    )

    await db.flush()
    # Re-query with participants loaded
    result = await db.execute(
        select(Touchpoint).options(selectinload(Touchpoint.company), selectinload(Touchpoint.participants), selectinload(Touchpoint.companies)).where(Touchpoint.id == touchpoint.id)
    )
    t = result.scalar_one()
    d = {col.name: getattr(t, col.name) for col in t.__table__.columns}
    d['company'] = {'id': str(t.company.id), 'name': t.company.name} if t.company else None
    d['participants'] = [{'id': str(p.id), 'name': p.name} for p in t.participants]
    d['companies'] = [{'id': str(c.id), 'name': c.name} for c in t.companies]
    return d


@router.delete("/touchpoints/{touchpoint_id}", status_code=204)
async def delete_touchpoint(
    request: Request,
    touchpoint_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Touchpoint).where(
            Touchpoint.id == touchpoint_id, Touchpoint.tenant_id == tenant_id
        )
    )
    touchpoint = result.scalar_one_or_none()
    if not touchpoint:
        raise HTTPException(status_code=404, detail="Touchpoint not found")

    title = touchpoint.title
    await db.delete(touchpoint)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="touchpoint",
        entity_id=touchpoint_id,
        summary=f"Deleted touchpoint '{title}'",
    )

    return None


# ===========================================================================
# TASKS
# ===========================================================================


@router.get("/tasks", response_model=ListResponse[TaskResponse])
async def list_tasks(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    status_not: str | None = None,
    priority: str | None = None,
    priority_not: str | None = None,
    contact_id: UUID | None = None,
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Task).where(Task.tenant_id == tenant_id)

    if search:
        base = base.where(Task.title.ilike(f"%{search}%"))
    if status:
        vals = [v.strip() for v in status.split(',') if v.strip()]
        if len(vals) == 1:
            base = base.where(Task.status == vals[0])
        else:
            base = base.where(Task.status.in_(vals))
    if status_not:
        vals = [v.strip() for v in status_not.split(',') if v.strip()]
        if len(vals) == 1:
            base = base.where(Task.status != vals[0])
        else:
            base = base.where(Task.status.notin_(vals))
    if priority:
        vals = [v.strip() for v in priority.split(',') if v.strip()]
        if len(vals) == 1:
            base = base.where(Task.priority == vals[0])
        else:
            base = base.where(Task.priority.in_(vals))
    if priority_not:
        vals = [v.strip() for v in priority_not.split(',') if v.strip()]
        if len(vals) == 1:
            base = base.where(Task.priority != vals[0])
        else:
            base = base.where(Task.priority.notin_(vals))
    if contact_id:
        base = base.where(Task.contact_id == contact_id)
    if company_id:
        base = base.where(Task.company_id == company_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.options(selectinload(Task.company), selectinload(Task.contact)).order_by(Task.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    # Batch-load custom fields
    task_ids = [t.id for t in rows]
    cf_map = await _load_custom_fields(db, tenant_id, "tasks", task_ids)

    # Build response with resolved company names + custom fields
    items = []
    for t in rows:
        d = {col.name: getattr(t, col.name) for col in t.__table__.columns}
        d['company'] = {'id': str(t.company.id), 'name': t.company.name} if t.company else None
        d['contact'] = {'id': str(t.contact.id), 'name': t.contact.name} if t.contact else None
        d['custom_fields'] = cf_map.get(str(t.id), {})
        # Ensure native fields from model are present
        d['parent_task_id'] = str(t.parent_task_id) if t.parent_task_id else None
        d['recurring'] = t.recurring
        d['area'] = t.area
        items.append(d)

    return ListResponse(items=items, total=total)


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: Request,
    body: TaskCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    task = Task(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=user_id,
        **body.model_dump(exclude={'custom_fields'}),
    )
    db.add(task)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="task",
        entity_id=task.id,
        summary=f"Created task '{task.title}'",
        workspace_id=workspace_id,
    )

    # ── Notification: task assigned to someone else ──
    if task.assignee_id and task.assignee_id != user_id:
        from app.services.notification_service import notify
        await notify(
            db,
            tenant_id=tenant_id,
            user_id=task.assignee_id,
            module="task",
            title=f"📋 你被指派任務：{task.title}",
            body=task.description or f"Priority: {task.priority or 'medium'} · Due: {task.due_date or '未設定'}",
            priority="HIGH" if task.priority == "urgent" else "NORMAL",
            action_url="/tasks",
            group_key=f"task-assign-{task.id}",
            source_record_type="task",
            source_record_id=task.id,
        )

    # Write custom fields if provided
    if body.custom_fields:
        await _apply_task_cf(db, tenant_id, task.id, body.custom_fields)

    await db.refresh(task)
    # Return with custom fields
    d = {col.name: getattr(task, col.name) for col in task.__table__.columns}
    d['company'] = None
    cf_map = await _load_custom_fields(db, tenant_id, "tasks", [task.id])
    d['custom_fields'] = cf_map.get(str(task.id), {})
    d['parent_task_id'] = str(task.parent_task_id) if task.parent_task_id else None
    d['recurring'] = task.recurring
    d['area'] = task.area
    return d


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task).options(selectinload(Task.company), selectinload(Task.contact)).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Build response with resolved company + contact name + custom fields
    d = {col.name: getattr(task, col.name) for col in task.__table__.columns}
    d['company'] = {'id': str(task.company.id), 'name': task.company.name} if task.company else None
    d['contact'] = {'id': str(task.contact.id), 'name': task.contact.name} if task.contact else None
    d['contact'] = {'id': str(task.contact.id), 'name': task.contact.name} if task.contact else None
    cf_map = await _load_custom_fields(db, tenant_id, "tasks", [task.id])
    d['custom_fields'] = cf_map.get(str(task.id), {})
    d['parent_task_id'] = str(task.parent_task_id) if task.parent_task_id else None
    d['recurring'] = task.recurring
    d['area'] = task.area
    return d


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    request: Request,
    task_id: UUID,
    body: TaskUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    changes = {}
    body_dict = body.model_dump(exclude_unset=True)
    cf_update = body_dict.pop('custom_fields', None)

    for field, value in body_dict.items():
        setattr(task, field, value)
        changes[field] = str(value)

    # Sync completed_at when status flips to/from done (match todo endpoint behaviour)
    status_val = body_dict.get("status")
    if status_val == "done" and not task.completed_at:
        task.completed_at = datetime.now(timezone.utc)
    elif status_val and status_val != "done" and task.completed_at:
        task.completed_at = None

    # ── Notification: task marked done (notify the creator, unless they did it) ──
    if status_val == "done" and task.created_by and task.created_by != user_id:
        from app.services.notification_service import notify
        await notify(
            db,
            tenant_id=tenant_id,
            user_id=task.created_by,
            module="task",
            title=f"✅ 任務已完成：{task.title}",
            body="由同事標記為完成",
            priority="LOW",
            action_url="/tasks",
            group_key=f"task-done-{task.id}",
            source_record_type="task",
            source_record_id=task.id,
        )

    task.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="task",
        entity_id=task.id,
        summary=f"Updated task '{task.title}'",
        changes=changes,
    )

    # Update custom fields if provided
    if cf_update is not None:
        await _delete_task_cf(db, tenant_id, task.id)
        await _apply_task_cf(db, tenant_id, task.id, cf_update)

    await db.flush()
    # Re-query with relationships eager-loaded — lazy `task.company` after
    # refresh() would 500 during serialization (MissingGreenlet, async session).
    result = await db.execute(
        select(Task)
        .options(selectinload(Task.company), selectinload(Task.contact))
        .where(Task.id == task.id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one()

    # Return with custom fields
    d = {col.name: getattr(task, col.name) for col in task.__table__.columns}
    d['company'] = {'id': str(task.company.id), 'name': task.company.name} if task.company else None
    d['contact'] = {'id': str(task.contact.id), 'name': task.contact.name} if task.contact else None
    cf_map = await _load_custom_fields(db, tenant_id, "tasks", [task.id])
    d['custom_fields'] = cf_map.get(str(task.id), {})
    d['parent_task_id'] = str(task.parent_task_id) if task.parent_task_id else None
    d['recurring'] = task.recurring
    d['area'] = task.area
    return d


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    title = task.title
    # Delete custom fields first
    await _delete_task_cf(db, tenant_id, task.id)
    await db.delete(task)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="task",
        entity_id=task_id,
        summary=f"Deleted task '{title}'",
    )

    return None


# ===========================================================================
# NAME CARDS
# ===========================================================================


@router.get("/name-cards", response_model=ListResponse[NameCardResponse])
async def list_name_cards(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(NameCard).where(NameCard.tenant_id == tenant_id)

    if search:
        base = base.where(NameCard.raw_ocr_text.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(NameCard.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/name-cards", response_model=NameCardResponse, status_code=201)
async def create_name_card(
    request: Request,
    body: NameCardCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    name_card = NameCard(
        tenant_id=tenant_id,
        **body.model_dump(),
    )
    db.add(name_card)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="name_card",
        entity_id=name_card.id,
        summary="Created name card entry",
    )

    await db.refresh(name_card)
    return name_card


# ── NameCard upload → OCR → auto-create/link Contact ───────────────────
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "namecards"


@router.post("/name-cards/upload", status_code=201)
async def upload_name_card(
    request: Request,
    file: UploadFile = File(...),
    cropped: str = Form("0"),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Upload a namecard image → save + queue（pending_ocr）→ persistent worker OCR → 中央通知。

    WORKFLOW-2026-09: scan 即時放行 — crop/OCR/parse/dedup 由 app 內 namecard worker
    （file-lock single owner loop）處理 — 唔用 BackgroundTasks（gunicorn timeout 會殺 >30s task）。
    """
    import uuid as _uuid
    from pathlib import Path as _Path

    from app.services import namecard_ocr

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    # 1. Save image
    ext = _Path(file.filename or "card.jpg").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    card_id = _uuid.uuid4()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    rel_path = f"{card_id}{ext}"
    abs_path = UPLOAD_DIR / rel_path
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    abs_path.write_bytes(content)

    original_image_url = f"/api/v1/crm/name-cards/image/{rel_path}"
    image_url = original_image_url

    # WORKFLOW-2026-09: DB queue — 建立 pending_ocr row，persistent worker 負責處理
    # （唔用 BackgroundTasks — gunicorn timeout 會 kill 長 task → 卡 404）
    try:
        # 2026-09-10: 前端 Lens 微調確認過 → 該圖就係最終顯示圖（pre-cropped）。
        # Backend worker 唔會再自動 crop（唔覆蓋用戶版本），見 _process_name_card_bg。
        _precrop = cropped.strip().lower() in ("1", "true", "yes")
        db.add(NameCard(
            id=card_id,
            tenant_id=tenant_id,
            image_url=image_url,
            original_image_url=original_image_url,
            cropped_image_url=original_image_url if _precrop else None,
            display_image="cropped" if _precrop else "original",
            parsed_data={},
            review_candidates=[],
            dedup_status="pending_ocr",
            status="pending_ocr",
            matched_by=user_id,
        ))
        await db.commit()
    except Exception as _e:
        abs_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue namecard: {_e}")
    return {
        "ok": True,
        "status": "processing",
        "id": str(card_id),
        "message": "名片已收到 — 背景識別緊，完成會通知你",
    }


async def namecard_process_pending() -> int:
    """WORKFLOW-2026-09 worker tick: poll pending_ocr rows → 逐張行 pipeline。

    Caller: main.py single-owner loop（file lock）— 唔受 gunicorn request timeout 影響。
    回傳處理咗幾多張。
    """
    import uuid as _uuid
    from app.db import async_session
    # RLS FORCE：bare SELECT 0 rows — loop all tenants + per-tenant GUC（跟 notification_scan pattern）
    async with async_session() as _db:
        _tenant_ids = (
            await _db.execute(text("SELECT id FROM nexus_auth.nexus_auth_tenants"))
        ).scalars().all()
        _pend = []
        for _tid in _tenant_ids:
            await _db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(_tid)},
            )
            _rows = (
                await _db.execute(
                    select(NameCard)
                    .where(NameCard.status == "pending_ocr")
                    .order_by(NameCard.created_at)
                    .limit(2)
                )
            ).scalars().all()
            for r in _rows:
                _pend.append(
                    (str(r.id), str(r.tenant_id), r.image_url or "", r.matched_by, r.original_image_url or "", r.cropped_image_url or "")
                )
    done = 0
    for _cid, _tid, _img, _uid, _orig, _crop in _pend:
        try:
            _rel = _img.rsplit("/", 1)[-1]
            _wid = ""
            try:
                async with async_session() as _db2:
                    _r = await _db2.execute(
                        text("SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
                        {"t": _tid},
                    )
                    _f = _r.first()
                    _wid = str(_f[0]) if _f else ""
            except Exception:
                _wid = ""
            await _process_name_card_bg(
                _cid, _rel, _tid, str(_uid) if _uid else _tid, _wid, _img, _orig or _img, _crop,
            )
            done += 1
        except Exception as _e:  # noqa: BLE001 — worker 唔可以死
            print(f"[namecard-worker] {_cid} failed: {type(_e).__name__}: {_e}", flush=True)
    return done


async def _process_name_card_bg(
    card_id_str: str, rel_path: str, tenant_id: str, user_id: str,
    workspace_id: str, image_url: str, original_image_url: str,
    precropped_url: str = "",
):
    """Background pipeline（WORKFLOW-2026-09）: crop → OCR → agents → dedup(pending) → contact → 通知。"""
    import uuid as _uuid
    from pathlib import Path as _Path
    from app.db import async_session
    from app.services import namecard_ocr

    card_id = _uuid.UUID(card_id_str)
    abs_path = _Path(__file__).resolve().parents[2] / "uploads" / "namecards" / rel_path
    workspace_id = _uuid.UUID(workspace_id) if workspace_id else None

    try:
        async with async_session() as db:
            conn = await db.connection()
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            if user_id:
                await conn.execute(
                    text("SELECT set_config('app.user_id', :uid, true)"),
                    {"uid": user_id},
                )
            try:
              # default display = original until crop verified

                # 2. Crop + OCR-verify: keep a crop only if it preserves card content.
                # WORKFLOW-2026-09: scan 唔到 → recrop retry，最多 5 次（crop → verify fail → 再試）
                usage_reports: list = []  # core rule G08: central token collection
                from app.services import namecard_crop_pipeline
                crop_path = None
                cropped_image_url = None
                crop_attempts = 0
                # 2026-09-10: 前端 Lens 已確認裁剪 → 該圖就係最終顯示圖。
                # 唔好再自動 crop（會覆蓋用戶微調，而且自動 crop 失敗時會搞到
                # 顯示原圖 — Terrence 真機中過）。
                if precropped_url:
                    _cname = precropped_url.rsplit("/", 1)[-1]
                    _candidate = abs_path.parent / _cname
                    if _candidate.exists():
                        crop_path = _candidate
                        cropped_image_url = precropped_url
                for _attempt in range(5 if not cropped_image_url else 0):
                    crop_attempts += 1
                    try:
                        crop_result = namecard_crop_pipeline.crop_card_best(abs_path, usage_out=usage_reports)
                    except Exception:
                        crop_result = {"crop": None}
                    if crop_result.get("crop") is None:
                        break
                    try:
                        candidate = namecard_crop_pipeline.save_crop(crop_result["crop"], abs_path)
                        if namecard_ocr.verify_crop(abs_path, candidate, usage_out=usage_reports):
                            crop_path = candidate
                            cropped_image_url = f"/api/v1/crm/name-cards/image/{crop_path.name}"
                            break
                        candidate.unlink(missing_ok=True)
                        crop_path = None
                    except OSError:
                        crop_path = None
                        break

                # 3. OCR — use the verified crop when available (cleaner input → better parse)
                ocr_source = crop_path if crop_path is not None else abs_path
                raw_text = namecard_ocr.ocr_image(ocr_source, usage_out=usage_reports)
                parsed = namecard_ocr.parse_namecard(raw_text) if raw_text else {}

                # 3.5 Agent pipeline — Ingestion → Extraction (LLM JSON mode, fail-safe)
                s1 = namecard_agents.ingestion_agent(raw_text, parsed, image_url)
                await namecard_agents.persist_step(
                    db, tenant_id=tenant_id, signal_id=card_id, step=s1)
                s2 = namecard_agents.extraction_agent(s1.output["signal"], usage_out=usage_reports)
                await namecard_agents.persist_step(
                    db, tenant_id=tenant_id, signal_id=card_id, step=s2)
                parsed = s2.output["parsed"]

                # 3. Company match/create (normalised exact → fuzzy → create + enrich)
                company_id = None
                company_name = (parsed.get("company") or "").strip()
                comp = None
                if company_name:
                    _norm = namecard_llm.normalize_company_name(company_name)
                    if _norm:
                        comp = (
                            await db.execute(
                                select(Company).where(
                                    Company.tenant_id == tenant_id,
                                    func.lower(Company.name) == company_name.lower(),
                                )
                            )
                        ).scalar_one_or_none()
                        if comp is None and _norm:
                            # fuzzy: normalised name contains the other (case-insensitive)
                            comp_rows = (
                                await db.execute(
                                    select(Company).where(Company.tenant_id == tenant_id)
                                )
                            ).scalars().all()
                            for _c in comp_rows:
                                _cn = namecard_llm.normalize_company_name(_c.name or "")
                                if _cn and (_norm in _cn or _cn in _norm):
                                    comp = _c
                                    break
                if company_name and comp is None:
                    # Enrichment Agent — web research (Perplexity; {} on failure)
                    s4 = namecard_agents.enrichment_agent(company_name, usage_out=usage_reports)
                    await namecard_agents.persist_step(
                        db, tenant_id=tenant_id, signal_id=card_id, step=s4)
                    research = s4.output.get("research") or {}
                    comp = Company(
                        tenant_id=tenant_id, workspace_id=workspace_id, name=company_name,
                        website=research.get("website") or None,
                        industry=research.get("industry") or None,
                        address=research.get("address") or None,
                        size=research.get("size") or None,
                        notes=research.get("description") or None,
                        enriched_by_ai=bool(research),
                        enrichment_source_url=research.get("source_url") or None,
                        data_completeness_pct=namecard_agents.company_completeness_pct(
                            {"name": company_name, **research}),
                    )
                    db.add(comp)
                    await db.flush()
                    await _log_activity(
                        db, tenant_id=tenant_id, actor_id=user_id,
                        action="created", entity_type="company", entity_id=comp.id,
                        summary=f"Created company '{company_name}' (from namecard, web-enriched)",
                        workspace_id=workspace_id,
                    )
                company_id = comp.id if comp else None

                # 4. Contact dedup — Entity Resolution Agent (3-layer, tiered routing)
                contact_id = None
                status = "pending"
                dedup_status = "none"
                review_candidates: list[dict] = []
                email = (parsed.get("email") or "").strip().lower()
                phone = (parsed.get("phone") or "").strip()
                person_name = (parsed.get("name") or "").strip()

                # Gather tenant contacts once (with company names for the agent)
                cand_rows = (
                    await db.execute(
                        select(Contact)
                        .options(selectinload(Contact.company))
                        .where(Contact.tenant_id == tenant_id)
                    )
                ).scalars().all()
                existing_contacts = [{
                    "id": str(c.id), "name": c.name, "chinese_name": c.chinese_name,
                    "job_title": c.job_title,
                    "company_id": str(c.company_id) if c.company_id else "",
                    "company_name": c.company.name if c.company else "",
                    "email": c.email, "phone": c.phone, "office_phone": c.office_phone,
                } for c in cand_rows]

                s3 = namecard_agents.entity_resolution_agent(parsed, existing_contacts, company_id, usage_out=usage_reports)
                await namecard_agents.persist_step(
                    db, tenant_id=tenant_id, signal_id=card_id, step=s3)
                resolution = s3.output
                candidate = resolution.get("candidate")
                conf = s3.confidence

                if s3.decision == "auto_link" and candidate:
                    # WORKFLOW-2026-09（user）: 2+ duplicated records → pending area，就算 high-confidence 都唔自動 link —
                    # 因為可能係「換公司」case（舊卡要 keep versioning）— 用戶喺 pending 區決定併入/分開
                    status = "review"
                    dedup_status = "auto_match_pending"
                    review_candidates = [{
                        "contact_id": candidate["id"],
                        "confidence": round(conf, 2),
                        "reason": resolution.get("reason") or "高信心重複 — 建議併入，但需人手確認（可能係換公司要開新）",
                        "name": candidate.get("name") or "", "email": candidate.get("email") or "",
                        "phone": candidate.get("phone") or "", "company": candidate.get("company") or "",
                        "title": candidate.get("title") or "",
                    }]
                elif s3.decision == "review" and candidate:
                    # MEDIUM tier (0.7-0.95): user decides override vs keep-both
                    status = "review"
                    dedup_status = "llm_review"
                    review_candidates = [{
                        "contact_id": candidate["id"],
                        "confidence": round(conf, 2),
                        "reason": resolution.get("reason", ""),
                        "name": candidate.get("name") or "", "email": candidate.get("email") or "",
                        "phone": candidate.get("phone") or "", "company": candidate.get("company") or "",
                        "title": candidate.get("title") or "",
                    }]
                elif person_name:
                    # LOW tier / no candidates — create (flag unresolved when weak)
                    contact = Contact(
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        name=person_name,
                        chinese_name=(parsed.get("chinese_name") or "").strip() or None,
                        email=email or None,
                        phone=phone or None,
                        office_phone=(parsed.get("office_phone") or "").strip() or None,
                        job_title=(parsed.get("title") or "").strip() or None,
                        company_id=company_id,
                        address=(parsed.get("address") or "").strip() or None,
                        source="namecard",
                        namecard_path=image_url,
                        source_signal_id=card_id,
                        confidence_score=conf if conf else None,
                        dedup_status="unresolved" if resolution.get("tier") == "low" else "none",
                        last_verified_at=datetime.now(timezone.utc),
                        custom_fields={
                            "namecard_website": parsed.get("website") or "",
                            "namecard_linkedin": parsed.get("linkedin") or "",
                        },
                    )
                    db.add(contact)
                    await db.flush()
                    contact_id = contact.id
                    status = "created"
                    # LOW tier weak hint → surface candidate for later manual review
                    if resolution.get("tier") == "low" and candidate:
                        review_candidates = [{
                            "contact_id": candidate["id"],
                            "confidence": round(conf, 2),
                            "reason": resolution.get("reason", ""),
                            "name": candidate.get("name") or "", "email": candidate.get("email") or "",
                            "phone": candidate.get("phone") or "", "company": candidate.get("company") or "",
                            "title": candidate.get("title") or "",
                        }]
                    await _log_activity(
                        db, tenant_id=tenant_id, actor_id=user_id,
                        action="created", entity_type="contact", entity_id=contact.id,
                        summary=f"Created contact '{person_name}' from namecard", workspace_id=workspace_id,
                    )

                # 4.5 AI context suggestion — could this person have been met recently?
                context_note = ""
                try:
                    recent_tps = (
                        await db.execute(
                            select(Touchpoint).where(
                                Touchpoint.tenant_id == tenant_id,
                                Touchpoint.type.in_(["meeting", "call", "event"]),
                                Touchpoint.date >= datetime.now(timezone.utc) - timedelta(days=30),
                            ).order_by(Touchpoint.date.desc()).limit(10)
                        )
                    ).scalars().all()
                    if recent_tps:
                        _events = [{"title": t.title, "date": str(t.date),
                                    "location": t.location or ""} for t in recent_tps]
                        s5 = namecard_agents.inference_agent(parsed, _events, usage_out=usage_reports)
                        await namecard_agents.persist_step(
                            db, tenant_id=tenant_id, signal_id=card_id, step=s5)
                        if s5.output.get("suggestion"):
                            context_note = s5.output["suggestion"]
                            parsed["context_note"] = context_note
                            parsed["context_match"] = s5.output.get("matched_event") or ""
                except Exception:  # noqa: BLE001 — enrichment never breaks upload
                    context_note = ""

                # ── Record usage events (namecard module) — central token collection ──
                try:
                    await namecard_agents._record_namecard_usage(db, tenant_id, usage_reports)
                except Exception:
                    pass  # usage recording is best-effort

                # 5. Store NameCard row — get-or-update（pending_ocr row 已由 upload 建立 — worker 模式）
                name_card = (
                    await db.execute(select(NameCard).where(NameCard.id == card_id))
                ).scalar_one_or_none()
                if name_card is None:
                    name_card = NameCard(
                        id=card_id,
                        tenant_id=tenant_id,
                        contact_id=contact_id,
                        image_url=image_url,
                        original_image_url=original_image_url,
                        cropped_image_url=cropped_image_url,
                        display_image="cropped" if cropped_image_url else "original",
                        raw_ocr_text=raw_text,
                        parsed_data=parsed,
                        review_candidates=review_candidates if status == "review" else [],
                        dedup_status=dedup_status,
                        status=status,
                        matched_by=user_id,
                    )
                    db.add(name_card)
                else:
                    name_card.contact_id = contact_id
                    name_card.cropped_image_url = cropped_image_url
                    name_card.display_image = "cropped" if cropped_image_url else "original"
                    name_card.raw_ocr_text = raw_text
                    name_card.parsed_data = parsed
                    name_card.review_candidates = review_candidates if status == "review" else []
                    name_card.dedup_status = dedup_status
                    name_card.status = status
                await db.flush()
                await _log_activity(
                    db, tenant_id=tenant_id, actor_id=user_id,
                    action="created", entity_type="name_card", entity_id=name_card.id,
                    summary=f"Uploaded namecard → {status}" + (f" ({person_name})" if person_name else ""),
                    workspace_id=workspace_id,
                )

                # WORKFLOW-2026-09（user）: scan 完成 → 中央通知（企鵝 badge）— duplicate → HIGH + 提示處理
                try:
                    from app.models.notification import Notification as _NC
                    is_dup = status in ("review", "matched", "pending")
                    _nc_notif = _NC(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        source_module="namecards",
                        source_record_type="name_card",
                        source_record_id=card_id,
                        title=("⚠️ 名片重複 — 待處理" if is_dup else "📇 名片已入庫"),
                        body=(
                            f"「{person_name or '呢張名片'}」同現有聯絡人重複（2+ records）— 去名片庫 pending 區決定併入或開新"
                            if is_dup else f"「{person_name or '新聯絡人'}」已自動加入聯絡人"
                        ),
                        priority="HIGH" if is_dup else "NORMAL",
                        action_url=f"/namecards?focus={card_id}",
                    )
                    db.add(_nc_notif)
                    await db.flush()
                except Exception as _e:
                    print(f"[namecard-notify] failed: {type(_e).__name__}: {_e}", flush=True)

                await db.flush()
                await db.refresh(name_card)



                await db.commit()
                return name_card
            except Exception as e:
                await db.rollback()
                try:
                    from app.models.notification import Notification as _NCE
                    db.add(_NCE(
                        tenant_id=tenant_id, user_id=user_id,
                        source_module="namecards", source_record_type="name_card",
                        source_record_id=card_id,
                        title="⚠️ 名片識別失敗",
                        body=f"{type(e).__name__}: {str(e)[:200]}",
                        priority="HIGH",
                    ))
                    await db.commit()
                except Exception:
                    pass
                raise

    except Exception as e:
        # most outer: session setup / RLS fail also reported (fresh session)
        try:
            from app.db import async_session as _as2
            from app.models.notification import Notification as _NCE2
            async with _as2() as db2:
                conn2 = await db2.connection()
                await conn2.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
                db2.add(_NCE2(
                    tenant_id=tenant_id, user_id=user_id,
                    source_module="namecards", source_record_type="name_card",
                    source_record_id=card_id, title="namecard bg failed",
                    body=f"outer: {type(e).__name__}: {str(e)[:200]}", priority="HIGH",
                ))
                await db2.commit()
        except Exception:
            pass
        raise


@router.get("/name-cards/image/{filename}")
async def name_card_image(
    request: Request,
    filename: str,
):
    """Serve a stored namecard image (authenticated)."""
    from fastapi.responses import FileResponse

    # Path traversal guard
    safe = Path(filename).name
    path = UPLOAD_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)


@router.get("/name-cards/{name_card_id}", response_model=NameCardResponse)
async def get_name_card(
    request: Request,
    name_card_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(NameCard).where(
            NameCard.id == name_card_id, NameCard.tenant_id == tenant_id
        )
    )
    name_card = result.scalar_one_or_none()
    if not name_card:
        raise HTTPException(status_code=404, detail="NameCard not found")
    return name_card


# Namecard review 決策 action 詞彙 — 兩套歷史命名嘅統一入口（KB-039）。
# merge / overwrite  → 併入現有 contact（overwrite 係 Telegram IM 流程用嘅字）
# separate / keep_both → 開新 contact，舊卡保留
_RESOLVE_ACTION_ALIASES = {
    "merge": "merge",
    "overwrite": "merge",
    "separate": "separate",
    "keep_both": "separate",
}


@router.post("/name-cards/{name_card_id}/resolve", response_model=NameCardResponse)
async def resolve_name_card(
    request: Request,
    name_card_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_tenant_session),
):
    """WORKFLOW-2026-09 pending area: 決定張 pending 卡 併入（merge）現有 contact 定 開新（separate）。

    - merge: 舊卡 link 現有 contact + backfill 缺嘅 fields（email/phone/title 唔覆蓋）+ 唔再 pending
    - separate: 用卡資料開新 contact（換公司 case — 舊卡 keep versioning：呢張卡 link 新 contact，
      之前嗰張卡 link 舊 contact — 兩張卡各自係嗰個人嘅 checkpoint）
    兩者都會記 touchpoint（Name card scanned & linked）+ 中央通知。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    # 輸入先驗證（喺 DB 讀取之前）——未知 action 一律 422，唔可以靜默當 separate（KB-039）
    raw_action = str(body.get("action") or "merge").strip().lower()
    action = _RESOLVE_ACTION_ALIASES.get(raw_action)
    if action is None:
        raise HTTPException(
            status_code=422,
            detail="action must be merge | separate (aliases: overwrite, keep_both)",
        )

    card = (
        await db.execute(
            select(NameCard).where(NameCard.id == name_card_id, NameCard.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Name card not found")

    parsed = card.parsed_data or {}
    cands = card.review_candidates or []
    target_id = body.get("target_contact_id") or body.get("contact_id")
    contact_id: Any = None
    person_name = (parsed.get("name") or parsed.get("person_name") or "").strip()

    if action == "merge":
        cid = target_id or (cands[0].get("contact_id") if cands else None)
        if not cid:
            raise HTTPException(status_code=400, detail="沒有合併目標 — 揀一個現有聯絡人")
        existing = (
            await db.execute(
                select(Contact).where(Contact.id == cid, Contact.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if not existing:
            raise HTTPException(status_code=404, detail="合併目標聯絡人唔存在")
        contact_id = existing.id
        email = (parsed.get("email") or "").strip().lower()
        phone = (parsed.get("phone") or "").strip()
        updates = {}
        if not existing.email and email:
            updates["email"] = email
        if not existing.phone and phone:
            updates["phone"] = phone
        if not existing.job_title and parsed.get("title"):
            updates["job_title"] = str(parsed.get("title") or "").strip() or None if not updates.get("job_title") else updates["job_title"]
        if not existing.source:
            updates["source"] = "namecard"
        for k, v in updates.items():
            setattr(existing, k, v)
        existing.dedup_status = "merged_manual"
        card.status = "matched"
        card.dedup_status = "merged_manual"
        card.review_candidates = []
        await _log_activity(
            db, tenant_id=tenant_id, actor_id=user_id,
            action="updated", entity_type="contact", entity_id=existing.id,
            summary=f"Merged namecard into contact '{existing.name}'" + (f" ({', '.join(updates)})" if updates else ""),
            workspace_id=workspace_id,
        )
    else:  # separate — 開新聯絡人（換公司 case — 舊卡 keep 喺舊 contact）
        email = (parsed.get("email") or "").strip().lower() or None
        phone = (parsed.get("phone") or "").strip() or None
        new_c = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=person_name or "未知名片",
            chinese_name=(parsed.get("chinese_name") or "").strip() or None,
            email=email,
            phone=phone,
            office_phone=(parsed.get("office_phone") or "").strip() or None,
            job_title=(parsed.get("title") or "").strip() or None,
            address=(parsed.get("address") or "").strip() or None,
            source="namecard",
            namecard_path=card.image_url,
            custom_fields={
                "namecard_website": parsed.get("website") or "",
                "namecard_linkedin": parsed.get("linkedin") or "",
            },
            dedup_status="none",
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(new_c)
        await db.flush()
        contact_id = new_c.id
        card.status = "created"
        card.dedup_status = "none"
        card.review_candidates = []
        await _log_activity(
            db, tenant_id=tenant_id, actor_id=user_id,
            action="created", entity_type="contact", entity_id=new_c.id,
            summary=f"Created contact '{person_name or '未知名片'}' from namecard (separate)",
            workspace_id=workspace_id,
        )

    card.contact_id = contact_id
    card.matched_by = user_id

    # Touchpoint — Name card scanned & linked
    try:
        tp = Touchpoint(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=user_id,
            contact_id=contact_id,
            type="namecard",
            title="Name card scanned & linked",
            date=datetime.now().date(),
        )
        db.add(tp)
        await db.flush()
    except Exception as _e:  # noqa: BLE001 — touchpoint best-effort
        print(f"[namecard-resolve] touchpoint failed: {type(_e).__name__}: {_e}", flush=True)

    # 中央通知 — 已處理
    try:
        from app.models.notification import Notification as _NC2
        db.add(_NC2(
            tenant_id=tenant_id, user_id=user_id,
            source_module="namecards", source_record_type="name_card",
            source_record_id=card.id,
            title="✅ 名片已處理",
            body=(f"「{person_name or '呢張卡'}」已併入現有聯絡人" if action == "merge" else f"「{person_name or '呢張卡'}」已開新聯絡人（舊卡保留做 versioning）"),
            priority="NORMAL",
            action_url=f"/contacts/{contact_id}" if contact_id else f"/namecards?focus={card.id}",
        ))
        await db.flush()
    except Exception:
        pass

    await db.flush()
    await db.refresh(card)
    return card


@router.patch("/name-cards/{name_card_id}", response_model=NameCardResponse)
async def update_name_card(
    request: Request,
    name_card_id: UUID,
    body: NameCardUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(NameCard).where(
            NameCard.id == name_card_id, NameCard.tenant_id == tenant_id
        )
    )
    name_card = result.scalar_one_or_none()
    if not name_card:
        raise HTTPException(status_code=404, detail="NameCard not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "display_image":
            if value not in ("original", "cropped"):
                raise HTTPException(status_code=422, detail="display_image must be 'original' or 'cropped'")
            target_url = name_card.original_image_url if value == "original" else name_card.cropped_image_url
            if not target_url:
                raise HTTPException(status_code=422, detail=f"No {value} image exists on this card")
            name_card.display_image = value
            name_card.image_url = target_url  # keep legacy field in sync
            changes[field] = str(value)
            continue
        setattr(name_card, field, value)
        changes[field] = str(value)

    name_card.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="name_card",
        entity_id=name_card.id,
        summary="Updated name card",
        changes=changes,
    )

    await db.flush()
    await db.refresh(name_card)
    return name_card


@router.delete("/name-cards/{name_card_id}", status_code=204)
async def delete_name_card(
    request: Request,
    name_card_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(NameCard).where(
            NameCard.id == name_card_id, NameCard.tenant_id == tenant_id
        )
    )
    name_card = result.scalar_one_or_none()
    if not name_card:
        raise HTTPException(status_code=404, detail="NameCard not found")

    await db.delete(name_card)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="name_card",
        entity_id=name_card_id,
        summary="Deleted name card",
    )

    return None


@router.post("/name-cards/{name_card_id}/duplicate", response_model=NameCardResponse)
async def duplicate_name_card(
    request: Request,
    name_card_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a copy of a name card (new id, same image + parsed data,
    unlinked contact). Used by the V2 gallery '建立副本' action."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    src = (
        await db.execute(
            select(NameCard).where(
                NameCard.id == name_card_id, NameCard.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="NameCard not found")

    new_card = NameCard(
        tenant_id=tenant_id,
        image_url=src.image_url,
        original_image_url=src.original_image_url,
        cropped_image_url=src.cropped_image_url,
        display_image=src.display_image,
        raw_ocr_text=src.raw_ocr_text,
        parsed_data=src.parsed_data,
        review_candidates=[],
        tags=src.tags,
        field_confidence=src.field_confidence,
        duplicate_candidate=None,
        status="pending",
        dedup_status="none",
        contact_id=None,
    )
    db.add(new_card)
    await db.flush()
    await db.refresh(new_card)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="name_card",
        entity_id=new_card.id,
        summary="Duplicated name card",
    )

    return new_card


def _resolve_image_file(url: str | None) -> Path | None:
    """Map a stored image URL to its file on disk (name-guarded)."""
    if not url:
        return None
    path = UPLOAD_DIR / Path(url.rsplit("/", 1)[-1]).name
    return path if path.is_file() else None


@router.delete("/name-cards/{name_card_id}/image/{variant}", response_model=NameCardResponse)
async def delete_name_card_image(
    request: Request,
    name_card_id: UUID,
    variant: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete one image version (original | cropped).

    The remaining version automatically becomes the default; if both are gone
    the card has no image at all.
    """
    if variant not in ("original", "cropped"):
        raise HTTPException(status_code=422, detail="variant must be 'original' or 'cropped'")
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(NameCard).where(NameCard.id == name_card_id, NameCard.tenant_id == tenant_id)
    )
    name_card = result.scalar_one_or_none()
    if not name_card:
        raise HTTPException(status_code=404, detail="NameCard not found")

    url = name_card.original_image_url if variant == "original" else name_card.cropped_image_url
    if not url:
        raise HTTPException(status_code=404, detail=f"No {variant} image on this card")

    fpath = _resolve_image_file(url)
    if fpath is not None:
        try:
            fpath.unlink()
        except OSError:
            pass

    if variant == "original":
        name_card.original_image_url = None
    else:
        name_card.cropped_image_url = None

    # Auto-switch default: the remaining version wins; none left → no image.
    remaining = name_card.cropped_image_url if variant == "original" else name_card.original_image_url
    if remaining:
        name_card.display_image = "cropped" if name_card.cropped_image_url else "original"
        name_card.image_url = remaining
    else:
        name_card.display_image = None
        name_card.image_url = None

    name_card.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="name_card",
        entity_id=name_card.id,
        summary=f"Deleted {variant} image from name card",
        changes={"image_removed": variant, "display_image": name_card.display_image},
    )

    await db.flush()
    await db.refresh(name_card)
    return name_card


@router.post("/name-cards/{name_card_id}/recrop", response_model=NameCardResponse)
async def recrop_name_card(
    request: Request,
    name_card_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """(Re)generate the cropped version for an existing card, OCR-verified."""
    from app.services import namecard_crop_pipeline
    from app.services import namecard_ocr

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(NameCard).where(NameCard.id == name_card_id, NameCard.tenant_id == tenant_id)
    )
    name_card = result.scalar_one_or_none()
    if not name_card:
        raise HTTPException(status_code=404, detail="NameCard not found")

    src_path = _resolve_image_file(name_card.original_image_url or name_card.image_url)
    if src_path is None:
        raise HTTPException(status_code=404, detail="Source image file missing")

    # ── Record usage events (namecard module) — central token collection ──
    usage_reports: list = []  # core rule G08
    crop_result = namecard_crop_pipeline.crop_card_best(src_path, usage_out=usage_reports)
    if crop_result["crop"] is None:
        raise HTTPException(status_code=422, detail=f"Crop failed ({crop_result['method']})")
    try:
        from app.services.namecard_agents import _record_namecard_usage
        await _record_namecard_usage(db, tenant_id, usage_reports)
    except Exception:
        pass  # usage recording is best-effort

    crop_path = namecard_crop_pipeline.save_crop(crop_result["crop"], src_path)
    if not namecard_ocr.verify_crop(src_path, crop_path, usage_out=usage_reports):
        crop_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail="Crop rejected: OCR verification found content cut off",
        )

    cropped_url = f"/api/v1/crm/name-cards/image/{crop_path.name}"
    name_card.cropped_image_url = cropped_url
    if name_card.display_image != "original":
        name_card.display_image = "cropped"
        name_card.image_url = cropped_url
    name_card.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="name_card",
        entity_id=name_card.id,
        summary=f"Regenerated crop ({crop_result['method']})",
        changes={"cropped_image_url": cropped_url, "method": crop_result["method"]},
    )

    await db.flush()
    await db.refresh(name_card)
    return name_card




async def _notebook_id_in_tenant(db: AsyncSession, tenant_id, notebook_id, user_id=None) -> bool:
    """Notes V2 (T1.3/T1.5) — a note may only live in a notebook of its own tenant.

    T1.3 加嘅原因：notes.notebook_id 帶 global FK，而 notes 嘅 RLS trigger 只查 tenant_id，
    冇呢個 guard 就可以將自己嘅 note 掛去其他 tenant 嘅 notebook id（懸空跨 tenant 引用）。
    T1.5 之後另外要求係**自己**嘅 notebook（owner_user_id），唔係隨便同 tenant 一個。
    """
    if notebook_id is None:
        return True
    from sqlalchemy import text as _text

    sql = "SELECT 1 FROM nexus_crm.notebooks WHERE id = :id AND tenant_id = :t"
    params = {"id": str(notebook_id), "t": str(tenant_id)}
    if user_id is not None:
        sql += " AND owner_user_id = :u"
        params["u"] = str(user_id)
    row = (await db.execute(_text(sql), params)).first()
    return row is not None


async def _load_owned_note(db: AsyncSession, tenant_id, user_id, note_id):
    """Notes V2 (T1.5) — 私人筆記：只有作者本人讀得到。

    其他人一律 404（唔用 403），避免洩漏「呢個 note id 存在」。用於 get / patch /
    delete / tags / links / dismiss 所有以 note_id 為輸入嘅 endpoint。
    """
    note = (await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def _note_to_dict(note) -> dict:
    """Serialize Note → NoteResponse body（contact/company 要 eager-loaded，否則
    async session 下 lazy load 會 MissingGreenlet）。"""
    d = {col.name: getattr(note, col.name) for col in note.__table__.columns}
    d['contact'] = {'id': str(note.contact.id), 'name': note.contact.name} if note.contact else None
    d['company'] = {'id': str(note.company.id), 'name': note.company.name} if note.company else None
    return d


REVISION_KEEP = 30


REVISION_MIN_GAP = timedelta(minutes=5)


async def _snapshot_revision_if_due(db: AsyncSession, note, user_id) -> None:
    """Notes V2 Stage C (T-03) — 為「改動前狀態」留底。

    throttle 5 分鐘（REVISION_MIN_GAP）：autosave 每 1.5 秒就可能 PATCH 一次，冇
    throttle 會幾分鐘內爆幾百個 revision。5 分鐘粒度 =「改寫一批內容」一個還原點。
    只保留最近 REVISION_KEEP 版，避免無限增長。
    """
    last = (await db.execute(
        select(NoteRevision.created_at)
        .where(NoteRevision.note_id == note.id)
        .order_by(NoteRevision.version.desc())
        .limit(1)
    )).scalar_one_or_none()
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last) < REVISION_MIN_GAP:
            return

    db.add(NoteRevision(
        tenant_id=note.tenant_id,
        note_id=note.id,
        version=int(note.version or 1),
        title=note.title,
        content=note.content,
        created_by=user_id,
    ))
    await db.flush()

    old_ids = (await db.execute(
        select(NoteRevision.id)
        .where(NoteRevision.note_id == note.id)
        .order_by(NoteRevision.version.desc())
        .offset(REVISION_KEEP)
    )).scalars().all()
    if old_ids:
        await db.execute(delete(NoteRevision).where(NoteRevision.id.in_(old_ids)))


PREF_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,79}$")
# Revision preview 用：strip HTML tags（TipTap 存 HTML，唔可以原字俾用戶睇 markup）


HTML_TAG_RE = re.compile(r"<[^>]+>")

@router.get("/preferences/{key}")
async def get_preference(
    request: Request,
    key: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Notes V2 Stage D (T-14) — 讀使用者偏好（per-user key/value）。

    未有記錄就回 `value: None`（唔 404）—— 前端可以照用 default。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    if not PREF_KEY_RE.match(key or ""):
        raise HTTPException(status_code=422, detail="Invalid preference key")

    value = (await db.execute(
        select(UserPreference.value).where(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )).scalar_one_or_none()
    return {"key": key, "value": value}


@router.put("/preferences/{key}")
async def put_preference(
    request: Request,
    key: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Notes V2 Stage D (T-14) — 寫使用者偏好（upsert）。

    body = {"value": <any JSON>}；value=None 會刪除該 key（回復 default）。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    if not PREF_KEY_RE.match(key or ""):
        raise HTTPException(status_code=422, detail="Invalid preference key")

    body = await request.json()
    if not isinstance(body, dict) or "value" not in body:
        raise HTTPException(status_code=400, detail='Body must be {"value": ...}')
    value = body.get("value")

    row = (await db.execute(
        select(UserPreference).where(
            UserPreference.tenant_id == tenant_id,
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )).scalar_one_or_none()

    if value is None:
        if row:
            await db.delete(row)
            await db.flush()
        return {"key": key, "value": None}

    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(UserPreference(tenant_id=tenant_id, user_id=user_id, key=key, value=value))
    await db.flush()
    return {"key": key, "value": value}


async def _note_tag_map(db: AsyncSession, tenant_id, note_ids: list[UUID]) -> dict:
    """Notes V2 (T2.1) — return {note_id: [{id,name,color}, ...]} tenant-scoped."""
    if not note_ids:
        return {}
    rows = (await db.execute(
        select(NoteTag.note_id, Tag.id, Tag.name, Tag.color)
        .join(Tag, Tag.id == NoteTag.tag_id)
        .where(NoteTag.tenant_id == tenant_id, NoteTag.note_id.in_(note_ids))
        .order_by(Tag.name.asc())
    )).all()
    out: dict = {}
    for note_id, tag_id, name, color in rows:
        out.setdefault(note_id, []).append({"id": str(tag_id), "name": name, "color": color})
    return out


_NOTE_LINK_URL_PREFIX = {
    "contact": "/contacts/",
    "company": "/companies/",
    "project": "/projects/",
    "task": "/tasks/",
    "touchpoint": "/touchpoints/",
    "deal": "/deals/",
    "note": "/notes/",
}


async def _note_link_map(db: AsyncSession, tenant_id, note_ids: list[UUID]) -> dict:
    """Notes V2 (T3.1) — return {note_id: [{id,entity_type,entity_id,label,url}, ...]}."""
    if not note_ids:
        return {}
    rows = (await db.execute(
        select(NoteLink.note_id, NoteLink.id, NoteLink.entity_type, NoteLink.entity_id, NoteLink.label)
        .where(NoteLink.tenant_id == tenant_id, NoteLink.note_id.in_(note_ids))
        .order_by(NoteLink.created_at.asc())
    )).all()
    out: dict = {}
    for note_id, lid, etype, eid, label in rows:
        prefix = _NOTE_LINK_URL_PREFIX.get(etype or "", "")
        out.setdefault(note_id, []).append({
            "id": str(lid),
            "entity_type": etype,
            "entity_id": str(eid) if eid else None,
            "label": label,
            "url": f"{prefix}{eid}" if (eid and prefix) else None,
        })
    return out


# ═══════════════════════════════════════════════════════════════
# Notes module v2 — Notebooks（T1.2，2026-09-11）
# SPEC: docs/notes-module-v2-SPEC.md（Q6B：私人；Q1A 分 3 期）
# 用 raw SQL 直寫（唔加 ORM model），避免影響其他 module；RLS + tenant 過濾雙重。
# 顏色只准 SPEC 定嘅 8 個 design token 色。
# ═══════════════════════════════════════════════════════════════
NOTEBOOK_COLORS = {"blue", "purple", "success", "warning", "gold", "error", "pink", "ai"}


@router.get("/notebooks")
async def list_notebooks(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """List the caller's **own** notebooks + how many of their notes each holds.

    Notes v2 (T1.5) — 私人筆記：notebook 同 note_count 都只計自己（SPEC Q6/Q6b）。
    原本只 filter tenant_id → 同 tenant 同事嘅 notebook 同件數都會出現。
    """
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    rows = (await db.execute(
        _text(
            "SELECT b.id::text AS id, b.name, b.color, b.visibility_scope::text AS visibility_scope,"
            " b.created_at,"
            " (SELECT count(*) FROM nexus_crm.notes n"
            "   WHERE n.notebook_id = b.id AND n.tenant_id = b.tenant_id"
            "     AND n.created_by = :u AND n.deleted_at IS NULL) AS note_count"
            " FROM nexus_crm.notebooks b"
            " WHERE b.tenant_id = :t AND b.owner_user_id = :u"
            " ORDER BY b.created_at ASC"
        ),
        {"t": str(tenant_id), "u": str(user_id)},
    )).mappings().all()
    return [dict(r) for r in rows]


@router.post("/notebooks", status_code=201)
async def create_notebook(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """Create a notebook. Owner = caller; private by default (SPEC Q6B)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    body = await request.json()
    name = str((body or {}).get("name") or "").strip()[:120]
    color = str((body or {}).get("color") or "blue").lower()
    if not name:
        raise HTTPException(status_code=422, detail="Notebook name is required")
    if color not in NOTEBOOK_COLORS:
        raise HTTPException(status_code=422, detail=f"color must be one of {sorted(NOTEBOOK_COLORS)}")

    row = (await db.execute(
        _text(
            "INSERT INTO nexus_crm.notebooks (tenant_id, owner_user_id, name, color, visibility_scope)"
            " VALUES (:t, :u, :n, :c, 'private')"
            " RETURNING id::text AS id, name, color, created_at"
        ),
        {"t": str(tenant_id), "u": str(user_id), "n": name, "c": color},
    )).mappings().one()
    await db.commit()
    return dict(row)


@router.patch("/notebooks/{notebook_id}")
async def update_notebook(
    request: Request,
    notebook_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Rename / recolour a notebook. Only the owner's own notebook is touched."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")

    sets, params = [], {"t": str(tenant_id), "u": str(user_id), "id": str(notebook_id)}
    if "name" in body:
        name = str(body.get("name") or "").strip()[:120]
        if not name:
            raise HTTPException(status_code=422, detail="Notebook name cannot be empty")
        sets.append("name = :n")
        params["n"] = name
    if "color" in body:
        color = str(body.get("color") or "").lower()
        if color not in NOTEBOOK_COLORS:
            raise HTTPException(status_code=422, detail=f"color must be one of {sorted(NOTEBOOK_COLORS)}")
        sets.append("color = :c")
        params["c"] = color
    if not sets:
        raise HTTPException(status_code=422, detail="Nothing to update")

    row = (await db.execute(
        _text(
            f"UPDATE nexus_crm.notebooks SET {', '.join(sets)}, updated_at = now()"
            " WHERE id = :id AND tenant_id = :t AND owner_user_id = :u"
            " RETURNING id::text AS id, name, color, updated_at"
        ),
        params,
    )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notebook not found")
    await db.commit()
    return dict(row)


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(
    request: Request,
    notebook_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a notebook. Notes are kept — their notebook_id goes NULL (SPEC edge case #1)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    result = await db.execute(
        _text(
            "DELETE FROM nexus_crm.notebooks"
            " WHERE id = :id AND tenant_id = :t AND owner_user_id = :u"
        ),
        {"id": str(notebook_id), "t": str(tenant_id), "u": str(user_id)},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notebook not found")
    await db.commit()
    return None


# ===========================================================================
# NOTES V2 (T2.2) — Templates（12 款內建 + team/tenant 自訂）
# ===========================================================================

def _tpl_doc(*blocks):
    return {"type": "doc", "content": [b for b in blocks if b]}


def _tpl_h(text, level=2):
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def _tpl_p(text=""):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]} if text else {"type": "paragraph"}


def _tpl_bullets(*items):
    return {"type": "bulletList", "content": [
        {"type": "listItem", "content": [_tpl_p(i)]} for i in items
    ]}


def _tpl_tasks(*items):
    return {"type": "taskList", "content": [
        {"type": "taskItem", "attrs": {"checked": False}, "content": [_tpl_p(i)]} for i in items
    ]}


_SYSTEM_NOTE_TEMPLATES = [
    {"name": "會議記錄", "category": "meeting", "blocks": _tpl_doc(
        _tpl_h("會議記錄"), _tpl_p("日期："), _tpl_p("出席者："), _tpl_p("地點："),
        _tpl_h("議程", 3), _tpl_bullets(""),
        _tpl_h("討論要點", 3), _tpl_bullets(""),
        _tpl_h("行動項目", 3), _tpl_tasks("", ""),
    )},
    {"name": "客戶通話記錄", "category": "call", "blocks": _tpl_doc(
        _tpl_h("客戶通話記錄"), _tpl_p("客戶："), _tpl_p("聯絡人／職銜："), _tpl_p("日期時間："),
        _tpl_h("通話目的", 3), _tpl_p(""),
        _tpl_h("客戶需求", 3), _tpl_bullets(""),
        _tpl_h("跟進事項", 3), _tpl_tasks(""),
    )},
    {"name": "專案計劃", "category": "project", "blocks": _tpl_doc(
        _tpl_h("專案計劃"), _tpl_p("專案名稱："), _tpl_p("目標："),
        _tpl_h("範圍", 3), _tpl_bullets("包含：", "不包含："),
        _tpl_h("里程碑", 3), _tpl_tasks(""),
        _tpl_h("風險", 3), _tpl_bullets(""),
    )},
    {"name": "每週週報", "category": "weekly", "blocks": _tpl_doc(
        _tpl_h("每週週報"), _tpl_p("本週："),
        _tpl_h("完成事項", 3), _tpl_tasks(""),
        _tpl_h("進行中", 3), _tpl_tasks(""),
        _tpl_h("下週計劃", 3), _tpl_tasks(""),
        _tpl_h("需要支援", 3), _tpl_bullets(""),
    )},
    {"name": "銷售機會檢視", "category": "deal", "blocks": _tpl_doc(
        _tpl_h("銷售機會檢視"), _tpl_p("客戶："), _tpl_p("金額："), _tpl_p("階段："),
        _tpl_h("客戶痛點", 3), _tpl_bullets(""),
        _tpl_h("競爭對手", 3), _tpl_bullets(""),
        _tpl_h("下一步", 3), _tpl_tasks(""),
    )},
    {"name": "產品需求", "category": "product", "blocks": _tpl_doc(
        _tpl_h("產品需求"), _tpl_h("背景與問題", 3), _tpl_p(""),
        _tpl_h("需求描述", 3), _tpl_bullets(""),
        _tpl_h("驗收條件", 3), _tpl_tasks(""),
    )},
    {"name": "客戶拜訪報告", "category": "visit", "blocks": _tpl_doc(
        _tpl_h("客戶拜訪報告"), _tpl_p("客戶："), _tpl_p("拜訪日期："), _tpl_p("與會者："),
        _tpl_h("觀察與重點", 3), _tpl_bullets(""),
        _tpl_h("後續行動", 3), _tpl_tasks(""),
    )},
    {"name": "問題跟進", "category": "issue", "blocks": _tpl_doc(
        _tpl_h("問題跟進"), _tpl_p("問題描述："), _tpl_p("影響範圍："), _tpl_p("嚴重程度："),
        _tpl_h("處理過程", 3), _tpl_bullets(""),
        _tpl_h("待辦", 3), _tpl_tasks(""),
    )},
    {"name": "培訓筆記", "category": "training", "blocks": _tpl_doc(
        _tpl_h("培訓筆記"), _tpl_p("主題："), _tpl_p("講者："), _tpl_p("日期："),
        _tpl_h("重點摘錄", 3), _tpl_bullets(""),
        _tpl_h("心得", 3), _tpl_p(""),
        _tpl_h("行動", 3), _tpl_tasks(""),
    )},
    {"name": "頭腦風暴", "category": "brainstorm", "blocks": _tpl_doc(
        _tpl_h("頭腦風暴"), _tpl_p("主題："),
        _tpl_h("想法（唔批判）", 3), _tpl_bullets(""),
        _tpl_h("可行的方向", 3), _tpl_bullets(""),
        _tpl_h("下一步", 3), _tpl_tasks(""),
    )},
    {"name": "決策記錄", "category": "decision", "blocks": _tpl_doc(
        _tpl_h("決策記錄"), _tpl_p("決策："), _tpl_p("日期："), _tpl_p("決策者："),
        _tpl_h("考慮過嘅選項", 3), _tpl_bullets("", ""),
        _tpl_h("決定原因", 3), _tpl_p(""),
        _tpl_h("影響", 3), _tpl_bullets(""),
    )},
    {"name": "每日反思", "category": "daily", "blocks": _tpl_doc(
        _tpl_h("每日反思"), _tpl_p("日期："),
        _tpl_h("今日完成", 3), _tpl_tasks(""),
        _tpl_h("學到嘅事", 3), _tpl_bullets(""),
        _tpl_h("明日重點", 3), _tpl_tasks(""),
    )},
]


async def _ensure_system_templates(db, tenant_id) -> None:
    """Seed the 12 built-in template rows for this tenant once (idempotent by name)."""
    from sqlalchemy import text as _text

    have = set((await db.execute(_text(
        "SELECT name FROM nexus_crm.note_templates WHERE tenant_id = :t AND is_system = true"
    ), {"t": str(tenant_id)})).scalars().all())
    inserted = False
    for tpl in _SYSTEM_NOTE_TEMPLATES:
        if tpl["name"] in have:
            continue
        await db.execute(_text(
            "INSERT INTO nexus_crm.note_templates"
            " (tenant_id, name, category, team_id, is_system, blocks_json)"
            " VALUES (:t, :n, :c, NULL, true, CAST(:b AS jsonb))"
        ), {
            "t": str(tenant_id),
            "n": tpl["name"],
            "c": tpl.get("category"),
            "b": json.dumps(tpl["blocks"], ensure_ascii=False),
        })
        inserted = True
    if inserted:
        # NOTE: no commit here — get_tenant_session commits at teardown. Committing
        # mid-request drops the transaction-local app.tenant_id GUC → the following
        # SELECT would be filtered by RLS and return 0 rows.
        await db.flush()


def _tpl_json_to_html(node) -> str:
    """Minimal TipTap-JSON → HTML for template initialisation (current notes.content is HTML)."""
    import html as _html

    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    kids = node.get("content") or []
    inner = "".join(_tpl_json_to_html(k) for k in kids)
    if t == "doc":
        return inner
    if t == "paragraph":
        return f"<p>{inner}</p>"
    if t == "heading":
        lvl = int((node.get("attrs") or {}).get("level") or 2)
        lvl = min(max(lvl, 1), 3)
        return f"<h{lvl}>{inner}</h{lvl}>"
    if t == "text":
        return _html.escape(str(node.get("text") or ""))
    if t == "bulletList":
        return f"<ul>{inner}</ul>"
    if t == "orderedList":
        return f"<ol>{inner}</ol>"
    if t == "listItem":
        return f"<li>{inner}</li>"
    if t == "taskList":
        return f"<ul data-type=\"taskList\">{inner}</ul>"
    if t == "taskItem":
        checked = "true" if (node.get("attrs") or {}).get("checked") else "false"
        return f"<li data-type=\"taskItem\" data-checked=\"{checked}\">{inner}</li>"
    if t == "blockquote":
        return f"<blockquote>{inner}</blockquote>"
    if t == "codeBlock":
        return f"<pre><code>{inner}</code></pre>"
    if t == "hardBreak":
        return "<br />"
    return inner


@router.get("/note-templates")
async def list_note_templates(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """List note templates: the 12 built-ins (seeded on first call) + tenant custom ones."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    await _ensure_system_templates(db, tenant_id)
    rows = (await db.execute(_text(
        "SELECT id::text AS id, name, category, is_system, team_id::text AS team_id,"
        " blocks_json, suggested_link_types, created_at"
        " FROM nexus_crm.note_templates WHERE tenant_id = :t"
        " ORDER BY is_system DESC, category ASC NULLS LAST, name ASC"
    ), {"t": str(tenant_id)})).mappings().all()
    return [dict(r) for r in rows]


@router.post("/note-templates", status_code=201)
async def create_note_template(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """Create a custom (non-system) note template."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    name = str(body.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=422, detail="Template name is required")
    category = (str(body.get("category") or "custom").strip() or "custom")[:40]
    blocks = body.get("blocks_json") if isinstance(body.get("blocks_json"), dict) else {"type": "doc", "content": [{"type": "paragraph"}]}
    row = (await db.execute(_text(
        "INSERT INTO nexus_crm.note_templates"
        " (tenant_id, name, category, team_id, is_system, blocks_json)"
        " VALUES (:t, :n, :c, NULL, false, CAST(:b AS jsonb))"
        " RETURNING id::text AS id, name, category, is_system, blocks_json, created_at"
    ), {"t": str(tenant_id), "n": name, "c": category, "b": json.dumps(blocks, ensure_ascii=False)})).mappings().one()
    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id, action="created",
        entity_type="note_template", entity_id=row["id"],
        summary=f"Created note template '{name}'",
    )
    await db.flush()
    return dict(row)


@router.patch("/note-templates/{template_id}")
async def update_note_template(
    request: Request,
    template_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Update a custom template only (system templates are read-only)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    sets, params = [], {"t": str(tenant_id), "id": str(template_id)}
    if "name" in body:
        name = str(body.get("name") or "").strip()[:120]
        if not name:
            raise HTTPException(status_code=422, detail="Template name cannot be empty")
        sets.append("name = :n")
        params["n"] = name
    if "category" in body:
        sets.append("category = :c")
        params["c"] = (str(body.get("category") or "custom").strip() or "custom")[:40]
    if isinstance(body.get("blocks_json"), dict):
        sets.append("blocks_json = CAST(:b AS jsonb)")
        params["b"] = json.dumps(body["blocks_json"], ensure_ascii=False)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    result = await db.execute(_text(
        "UPDATE nexus_crm.note_templates SET " + ", ".join(sets) +
        " WHERE id = :id AND tenant_id = :t AND is_system = false"
    ), params)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Template not found (or system template)")
    row = (await db.execute(_text(
        "SELECT id::text AS id, name, category, is_system, blocks_json, created_at"
        " FROM nexus_crm.note_templates WHERE id = :id AND tenant_id = :t"
    ), params)).mappings().one()
    return dict(row)


@router.delete("/note-templates/{template_id}", status_code=204)
async def delete_note_template(
    request: Request,
    template_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a custom template (system templates cannot be deleted)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    result = await db.execute(_text(
        "DELETE FROM nexus_crm.note_templates"
        " WHERE id = :id AND tenant_id = :t AND is_system = false"
    ), {"id": str(template_id), "t": str(tenant_id)})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Template not found (or system template)")
    return None


@router.post("/notes/from-template", response_model=NoteResponse, status_code=201)
async def create_note_from_template(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """Create a note initialised from a template (blocks → content)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    template_id = body.get("template_id")
    if not template_id:
        raise HTTPException(status_code=422, detail="template_id is required")

    tpl = (await db.execute(_text(
        "SELECT id::text AS id, name, blocks_json FROM nexus_crm.note_templates"
        " WHERE id = :id AND tenant_id = :t"
    ), {"id": str(template_id), "t": str(tenant_id)})).mappings().first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    content = _tpl_json_to_html(tpl["blocks_json"])
    note = Note(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=user_id,
        title=tpl["name"],
        content=content,
        notebook_id=body.get("notebook_id"),
        template_id=template_id,
    )
    db.add(note)
    await db.flush()
    await sync_note_mentions(db, tenant_id=tenant_id, note_id=note.id, html=note.content)
    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id, action="created",
        entity_type="note", entity_id=note.id,
        summary=f"Created note from template '{tpl['name']}'", workspace_id=workspace_id,
    )
    await db.refresh(note)
    return note


@router.post("/note-templates/purge-empty-drafts")
async def purge_empty_template_drafts(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """Remove untouched template-created notes older than 24h (SPEC edge case #5)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    rows = (await db.execute(_text(
        "SELECT n.id::text AS id, n.title, n.content, t.blocks_json"
        " FROM nexus_crm.notes n"
        " JOIN nexus_crm.note_templates t ON t.id = n.template_id"
        " WHERE n.tenant_id = :t AND n.created_by = :u AND n.template_id IS NOT NULL"
        "   AND n.created_at < now() - interval '24 hours'"
    ), {"t": str(tenant_id), "u": str(user_id)})).mappings().all()
    deleted = 0
    for r in rows:
        tpl_html = _tpl_json_to_html(r["blocks_json"])
        if (r["content"] or "").strip() == tpl_html.strip():
            await db.execute(_text("DELETE FROM nexus_crm.notes WHERE id = :id AND tenant_id = :t"), {"id": r["id"], "t": str(tenant_id)})
            deleted += 1
    return {"deleted": deleted}


@router.get("/notes", response_model=ListResponse[NoteResponse])
async def list_notes(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    tag_id: UUID | None = None,
    notebook_id: UUID | None = None,
    uncategorized: bool = False,
    sort: str = "updated_desc",
    # spec §8.3 反向查詢：邊啲筆記 mention 咗呢個 object（行 idx_note_links_entity）。
    # 注意：仍然受「私人筆記 = 只回自己寫嘅」filter 限制（同 list 其他分支一致）。
    mention_of_type: str | None = None,
    mention_of_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    # Notes v2 (T1.5) — 私人筆記：list 只回自己寫嘅筆記（SPEC Q6 / edge case #2）。
    # 呢個 filter 同 notebook / tag / link / search 所有分支共用，所以 count 亦一致。
    base = select(Note).where(
        Note.tenant_id == tenant_id,
        Note.created_by == user_id,
        Note.deleted_at.is_(None),  # T-04 soft delete：正常 list 唔出已刪嘅
    )

    if search:
        base = base.where(
            or_(
                Note.title.ilike(f"%{search}%"),
                Note.content.ilike(f"%{search}%"),
            )
        )

    if company_id:
        base = base.where(Note.company_id == company_id)
    if mention_of_type and mention_of_id:
        base = base.where(
            Note.id.in_(
                select(NoteLink.note_id).where(
                    NoteLink.tenant_id == tenant_id,
                    NoteLink.entity_type == mention_of_type.strip().lower(),
                    NoteLink.entity_id == mention_of_id,
                )
            )
        )
    if contact_id:
        base = base.where(Note.contact_id == contact_id)
    if project_id:
        base = base.where(Note.project_id == project_id)
    if task_id:
        base = base.where(Note.task_id == task_id)
    if tag_id:
        # Notes V2 (T2.1) — filter notes carrying a given tag.
        base = base.where(
            Note.id.in_(
                select(NoteTag.note_id).where(
                    NoteTag.tenant_id == tenant_id, NoteTag.tag_id == tag_id
                )
            )
        )
    # Notes V2 (T1.3) — 3-pane workspace: scope the middle list to one notebook.
    # uncategorized=True is the "未分類" pseudo-notebook (notebook deleted or never set).
    if uncategorized:
        base = base.where(Note.notebook_id.is_(None))
    elif notebook_id:
        base = base.where(Note.notebook_id == notebook_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Notes V2 (T1.3) — sort options from the list toolbar. Pinned always floats
    # to the top; the chosen key breaks the tie (default = most recently edited).
    sort_map = {
        "updated_desc": Note.updated_at.desc(),
        "created_desc": Note.created_at.desc(),
        "created_asc": Note.created_at.asc(),
        "title_asc": func.lower(Note.title).asc(),
    }
    items_q = (
        base.options(selectinload(Note.company))
        .order_by(Note.pinned.desc(), sort_map.get(sort, Note.updated_at.desc()), Note.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(items_q)).scalars().all()

    tag_map = await _note_tag_map(db, tenant_id, [n.id for n in rows])
    link_map = await _note_link_map(db, tenant_id, [n.id for n in rows])

    # Build response with resolved company names
    items = []
    for n in rows:
        d = {col.name: getattr(n, col.name) for col in n.__table__.columns}
        d['company'] = {'id': str(n.company.id), 'name': n.company.name} if n.company else None
        d['note_tags'] = tag_map.get(n.id, [])
        d['note_links'] = link_map.get(n.id, [])
        items.append(d)

    return ListResponse(items=items, total=total)


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(
    request: Request,
    body: NoteCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    if not await _notebook_id_in_tenant(db, tenant_id, body.notebook_id, user_id):
        raise HTTPException(status_code=422, detail="notebook_id does not belong to this tenant")

    note = Note(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=user_id,
        **body.model_dump(),
    )
    db.add(note)
    await db.flush()

    # Notes V2 @mention → note_links（spec §7：server 由 canonical content 推導）
    await sync_note_mentions(db, tenant_id=tenant_id, note_id=note.id, html=note.content)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="note",
        entity_id=note.id,
        summary=f"Created note '{note.title or '(untitled)'}'",
        workspace_id=workspace_id,
    )

    await db.refresh(note)
    return note


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(
    request: Request,
    note_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Note).options(selectinload(Note.company)).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    # Build response with resolved company name
    d = {col.name: getattr(note, col.name) for col in note.__table__.columns}
    d['company'] = {'id': str(note.company.id), 'name': note.company.name} if note.company else None
    d['note_tags'] = (await _note_tag_map(db, tenant_id, [note.id])).get(note.id, [])
    d['note_links'] = (await _note_link_map(db, tenant_id, [note.id])).get(note.id, [])
    return d


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    request: Request,
    note_id: UUID,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    payload = body.model_dump(exclude_unset=True)
    # ── T-02 樂觀鎖：expected_version 唔係 Note 欄位，要先抽走 ──
    expected_version = payload.pop("expected_version", None)
    if "notebook_id" in payload and not await _notebook_id_in_tenant(db, tenant_id, payload["notebook_id"], user_id):
        raise HTTPException(status_code=422, detail="notebook_id does not belong to this tenant")

    if expected_version is not None and int(expected_version) != int(note.version or 1):
        # 另一個 tab／裝置／（將來）共享編輯者已經改過 → 唔好靜默覆蓋。
        # 409 body 帶最新 version + updated_at 俾前端提示用戶重新載入。
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_conflict",
                "expected_version": int(expected_version),
                "current_version": int(note.version or 1),
                "updated_at": note.updated_at.isoformat() if note.updated_at else None,
            },
        )

    # ── T-03 revision：改之前先留底「被取代嘅舊狀態」（5 分鐘 throttle）──
    if any(k in payload for k in ("title", "content")):
        await _snapshot_revision_if_due(db, note, user_id)

    changes = {}
    for field, value in payload.items():
        setattr(note, field, value)
        changes[field] = str(value)

    note.updated_at = datetime.now(timezone.utc)
    note.version = int(note.version or 1) + 1

    # Notes V2 @mention → note_links：內容有變先重新同步（刪走唔再 mention 嘅）。
    if "content" in changes:
        await sync_note_mentions(db, tenant_id=tenant_id, note_id=note.id, html=note.content)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="note",
        entity_id=note.id,
        summary=f"Updated note '{note.title or '(untitled)'}'",
        changes=changes,
    )

    await db.flush()
    # Re-query with relationships eager-loaded — lazy contact/company would 500
    # during serialization (MissingGreenlet, async session) for notes that have them.
    result = await db.execute(
        select(Note)
        .options(selectinload(Note.contact), selectinload(Note.company))
        .where(Note.id == note.id, Note.tenant_id == tenant_id)
    )
    note = result.scalar_one()
    d = {col.name: getattr(note, col.name) for col in note.__table__.columns}
    d['contact'] = {'id': str(note.contact.id), 'name': note.contact.name} if note.contact else None
    d['company'] = {'id': str(note.company.id), 'name': note.company.name} if note.company else None
    d['note_links'] = (await _note_link_map(db, tenant_id, [note.id])).get(note.id, [])
    return d


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    request: Request,
    note_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    title = note.title
    # ── T-04 soft delete：唔真刪，只標記 deleted_at（前端 5 秒內可撤銷）──
    note.deleted_at = datetime.now(timezone.utc)
    note.updated_at = datetime.now(timezone.utc)
    note.version = int(note.version or 1) + 1

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="note",
        entity_id=note_id,
        summary=f"Deleted note '{title or '(untitled)'}'",
    )

    return None


@router.post("/notes/{note_id}/restore", response_model=NoteResponse)
async def restore_note(
    request: Request,
    note_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Notes V2 Stage B (T-04) — 撤銷刪除。

    同樣只限作者（T1.5）。Idempotent：已經唔係 deleted 狀態就照回傳目前內容。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    note = (await db.execute(
        select(Note)
        .options(selectinload(Note.contact), selectinload(Note.company))
        .where(Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id)
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if note.deleted_at is not None:
        note.deleted_at = None
        note.updated_at = datetime.now(timezone.utc)
        note.version = int(note.version or 1) + 1
        await _log_activity(
            db,
            tenant_id=tenant_id,
            actor_id=user_id,
            action="restored",
            entity_type="note",
            entity_id=note_id,
            summary=f"Restored note '{note.title or '(untitled)'}'",
        )
        await db.flush()

    return _note_to_dict(note)


@router.get("/trash/notes")
async def list_trashed_notes(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
    days: int = 30,
    limit: int = 100,
):
    """Notes V2 Stage B (T-04) — 最近刪除（預設 30 日內），俾 UI 做還原入口。

    ⚠️ 路徑刻意用 /trash/notes 而唔係 /notes/trash：後者會被先註冊嘅
    `GET /notes/{note_id}` match 到，"trash" 當 UUID 解析失敗 → 422。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 180)))

    rows = (await db.execute(
        select(Note)
        .where(
            Note.tenant_id == tenant_id,
            Note.created_by == user_id,
            Note.deleted_at.isnot(None),
            Note.deleted_at >= since,
        )
        .order_by(Note.deleted_at.desc())
        .limit(max(1, min(limit, 200)))
    )).scalars().all()

    return {
        "items": [
            {
                "id": str(n.id),
                "title": n.title,
                "notebook_id": str(n.notebook_id) if n.notebook_id else None,
                "deleted_at": n.deleted_at.isoformat() if n.deleted_at else None,
            }
            for n in rows
        ]
    }


@router.get("/notes/{note_id}/revisions")
async def list_note_revisions(
    request: Request,
    note_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
    limit: int = 30,
):
    """Notes V2 Stage C (T-03) — 版本history（新→舊）。只限作者。"""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    await _load_owned_note(db, tenant_id, user_id, note_id)

    rows = (await db.execute(
        select(
            NoteRevision.id, NoteRevision.version, NoteRevision.title,
            NoteRevision.created_at, NoteRevision.content,
        )
        .where(NoteRevision.tenant_id == tenant_id, NoteRevision.note_id == note_id)
        .order_by(NoteRevision.version.desc())
        .limit(max(1, min(limit, 50)))
    )).mappings().all()

    out = []
    for r in rows:
        content = r["content"] or ""
        # 唔回全文（History drawer 只需要預覽）；要還原就 call restore endpoint。
        # ⚠️ 一定要真 strip HTML tags：先前只係 content.replace("<", " <") → preview 會出
        # 原字 markup（視覺檢查捉到 drawer 顯示 `<h2>` `<strong>` 咁樣俾用戶睇）。
        plain = HTML_TAG_RE.sub(" ", content)
        for _ent, _ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
            plain = plain.replace(_ent, _ch)
        plain = " ".join(plain.split())
        out.append({
            "id": str(r["id"]),
            "version": r["version"],
            "title": r["title"],
            "preview": plain[:160],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"items": out, "total": len(out)}


@router.post("/notes/{note_id}/revisions/{revision_id}/restore", response_model=NoteResponse)
async def restore_note_revision(
    request: Request,
    note_id: UUID,
    revision_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Notes V2 Stage C (T-03) — 還原到某個版本。

    還原動作本身都算一次修改：先為「目前狀態」留底（唔理 throttle，因為係破壞性操作），
    再套用舊版內容，version +1。所以還原之後仲可以還原返轉頭。
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    note = (await db.execute(
        select(Note)
        .options(selectinload(Note.contact), selectinload(Note.company))
        .where(Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id)
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    rev = (await db.execute(
        select(NoteRevision).where(
            NoteRevision.id == revision_id,
            NoteRevision.note_id == note_id,
            NoteRevision.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if not rev:
        raise HTTPException(status_code=404, detail="Revision not found")

    # 無條件留底目前狀態（唔 throttle）：還原係破壞性 → 必須可以再還原返轉頭
    db.add(NoteRevision(
        tenant_id=note.tenant_id,
        note_id=note.id,
        version=int(note.version or 1),
        title=note.title,
        content=note.content,
        created_by=user_id,
    ))

    note.title = rev.title
    note.content = rev.content
    note.updated_at = datetime.now(timezone.utc)
    note.version = int(note.version or 1) + 1

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="note",
        entity_id=note_id,
        summary=f"Restored note '{note.title or '(untitled)'}' to v{rev.version}",
    )
    await db.flush()
    return _note_to_dict(note)


# ===========================================================================
# NOTES V2 (T2.1) — Tags on notes (reuse nexus_crm.tags + note_tags junction)
# ===========================================================================

@router.post("/notes/{note_id}/tags", response_model=list[NoteTagRef])
async def attach_note_tag(
    request: Request,
    note_id: UUID,
    body: NoteTagAttach,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Attach a tag to a note.

    Reuses an existing tenant tag by id, or finds-or-creates by name
    (case-insensitive) so the same tag name never duplicates. Idempotent.
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    note = (await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    tag = None
    if body.tag_id:
        tag = (await db.execute(
            select(Tag).where(Tag.id == body.tag_id, Tag.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name or tag_id is required")
        tag = (await db.execute(
            select(Tag).where(Tag.tenant_id == tenant_id, func.lower(Tag.name) == name.lower())
        )).scalars().first()
        if not tag:
            tag = Tag(tenant_id=tenant_id, name=name, color=body.color, entity_type="note")
            db.add(tag)
            await db.flush()

    existing = (await db.execute(
        select(NoteTag).where(
            NoteTag.tenant_id == tenant_id,
            NoteTag.note_id == note_id,
            NoteTag.tag_id == tag.id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(NoteTag(tenant_id=tenant_id, note_id=note_id, tag_id=tag.id))
        await _log_activity(
            db,
            tenant_id=tenant_id,
            actor_id=user_id,
            action="updated",
            entity_type="note",
            entity_id=note_id,
            summary=f"Tagged note '{note.title or '(untitled)'}' with '{tag.name}'",
        )
        await db.flush()

    refs = await _note_tag_map(db, tenant_id, [note_id])
    return [NoteTagRef(**r) for r in refs.get(note_id, [])]


@router.delete("/notes/{note_id}/tags/{tag_id}", status_code=204)
async def detach_note_tag(
    request: Request,
    note_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Detach a tag from a note (idempotent — 204 even if not attached)."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    # T1.5 私人筆記：唔係自己嘅 note → 404（唔可以靠瞎試 note_id 改人哋嘅 tag）
    await _load_owned_note(db, tenant_id, user_id, note_id)

    await db.execute(
        delete(NoteTag).where(
            NoteTag.tenant_id == tenant_id,
            NoteTag.note_id == note_id,
            NoteTag.tag_id == tag_id,
        )
    )
    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="note",
        entity_id=note_id,
        summary="Removed a tag from note",
    )
    return None


# ===========================================================================
# NOTES V2 (T3.1) — @mention / +Link record (nogte_links)
# ===========================================================================

_NOTE_LINK_TYPES = {"contact", "company", "project", "task", "touchpoint", "deal", "note"}


@router.post("/notes/{note_id}/links", response_model=list[NoteLinkRef])
async def add_note_link(
    request: Request,
    note_id: UUID,
    body: NoteLinkCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Link a note to a CRM record (@mention / +Link record). Idempotent."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    entity_type = (body.entity_type or "").strip().lower()
    if entity_type not in _NOTE_LINK_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity_type")

    note = (await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # spec §5.4：寫 polymorphic link 之前一定要驗 referenced object 同 tenant 存在
    # （呢種關係冇 FK 保護）。重用 mention 白名單，唔好兩處各有一份。
    if entity_type in MENTION_ENTITY_TABLES and body.entity_id is not None:
        _tbl = MENTION_ENTITY_TABLES[entity_type]
        _hit = (await db.execute(
            text(
                f"SELECT 1 FROM nexus_crm.{_tbl}"
                " WHERE tenant_id = :t AND id = :i"
                + (" AND deleted_at IS NULL" if _tbl == "notes" else "")
                + " LIMIT 1"
            ),
            {"t": str(tenant_id), "i": str(body.entity_id)},
        )).first()
        if not _hit:
            raise HTTPException(status_code=422, detail="entity_id does not belong to this tenant")

    existing = (await db.execute(
        select(NoteLink).where(
            NoteLink.tenant_id == tenant_id,
            NoteLink.note_id == note_id,
            NoteLink.entity_type == entity_type,
            NoteLink.entity_id == body.entity_id,
        )
    )).scalar_one_or_none()
    if existing:
        if body.label and existing.label != body.label:
            existing.label = body.label
            await db.flush()
        # 用戶明確加 link → 標記 source='manual'，令之後 content sync 唔會刪佢。
        # （唯一約束係 (note_id, entity_type, entity_id)，所以手動加一個已經被
        #   @mention 嘅 object 會行呢條 UPDATE 分支而唔係 INSERT。）
        if await mentions_ready(db):
            await db.execute(
                text("UPDATE nexus_crm.note_links SET source = 'manual' WHERE id = :i"),
                {"i": str(existing.id)},
            )
    else:
        db.add(NoteLink(
            tenant_id=tenant_id,
            note_id=note_id,
            entity_type=entity_type,
            entity_id=body.entity_id,
            label=body.label,
        ))
        await _log_activity(
            db,
            tenant_id=tenant_id,
            actor_id=user_id,
            action="updated",
            entity_type="note",
            entity_id=note_id,
            summary=f"Linked note '{note.title or '(untitled)'}' to {entity_type} {body.label or ''}".strip(),
        )
        await db.flush()

    refs = await _note_link_map(db, tenant_id, [note_id])
    return [NoteLinkRef(**r) for r in refs.get(note_id, [])]


@router.delete("/notes/{note_id}/links/{link_id}", status_code=204)
async def remove_note_link(
    request: Request,
    note_id: UUID,
    link_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Remove a note ↔ record link (idempotent — 204)."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    # T1.5 私人筆記：唔係自己嘅 note → 404
    await _load_owned_note(db, tenant_id, user_id, note_id)

    await db.execute(
        delete(NoteLink).where(
            NoteLink.tenant_id == tenant_id,
            NoteLink.note_id == note_id,
            NoteLink.id == link_id,
        )
    )
    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="note",
        entity_id=note_id,
        summary="Removed a record link from note",
    )
    return None


# ===========================================================================
# NOTES V2 (T3.3) — Rule-based link suggestions（規則比對；唔用 LLM）
# ===========================================================================

def _strip_html_text(html: str) -> str:
    import re as _re

    txt = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=_re.S | _re.I)
    txt = _re.sub(r"<[^>]+>", " ", txt)
    return _re.sub(r"\s+", " ", txt).strip()


async def _suggested_links_for_note(db: AsyncSession, tenant_id, note) -> list[dict]:
    """Suggest known contact/company names that appear in the note text (rule-based)."""
    from sqlalchemy import text as _text

    txt = _strip_html_text(note.content or "")
    if not txt or len(txt) < 3:
        return []
    rows = (await db.execute(_text(
        "SELECT id::text AS entity_id, btrim(name) AS label, 'contact' AS entity_type"
        " FROM nexus_crm.contacts"
        " WHERE tenant_id = :t AND name IS NOT NULL AND length(btrim(name)) >= 3"
        "   AND position(lower(btrim(name)) in lower(:txt)) > 0"
        " UNION ALL "
        "SELECT id::text, btrim(name), 'company'"
        " FROM nexus_crm.companies"
        " WHERE tenant_id = :t AND name IS NOT NULL AND length(btrim(name)) >= 3"
        "   AND position(lower(btrim(name)) in lower(:txt)) > 0"
        " LIMIT 8"
    ), {"t": str(tenant_id), "txt": txt[:20000]})).mappings().all()
    if not rows:
        return []

    linked = {(r[0], r[1]) for r in (await db.execute(_text(
        "SELECT entity_type, entity_id::text FROM nexus_crm.note_links"
        " WHERE tenant_id = :t AND note_id = :n"
    ), {"t": str(tenant_id), "n": str(note.id)})).all()}
    dismissed = {(r[0], r[1]) for r in (await db.execute(_text(
        "SELECT entity_type, entity_id::text FROM nexus_crm.note_link_dismissals"
        " WHERE tenant_id = :t AND note_id = :n"
    ), {"t": str(tenant_id), "n": str(note.id)})).all()}

    out: list[dict] = []
    for r in rows:
        key = (r["entity_type"], r["entity_id"])
        if key in linked or key in dismissed:
            continue
        out.append({"entity_type": r["entity_type"], "entity_id": r["entity_id"], "label": r["label"]})
        if len(out) >= 5:
            break
    return out


@router.post("/notes/link-suggestions")
async def note_link_suggestions(request: Request, db: AsyncSession = Depends(get_tenant_session)):
    """Batch rule-based link suggestions for up to 20 notes → {note_id: [suggestion, ...]}."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    body = await request.json()
    raw = (body or {}).get("note_ids") or []
    ids: list[UUID] = []
    for x in raw[:20]:
        try:
            ids.append(UUID(str(x)))
        except Exception:
            continue
    if not ids:
        return {}
    # T1.5 私人筆記：只為自己嘅 note 出建議（原本淨係 filter tenant）
    rows = (await db.execute(
        select(Note).where(
            Note.tenant_id == tenant_id, Note.id.in_(ids), Note.created_by == user_id
        )
    )).scalars().all()
    out: dict = {}
    for n in rows:
        s = await _suggested_links_for_note(db, tenant_id, n)
        if s:
            out[str(n.id)] = s
    return out


@router.post("/notes/{note_id}/dismiss-link", status_code=204)
async def dismiss_note_link(
    request: Request,
    note_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Remember a dismissed suggestion → never suggested again (SPEC #11)."""
    from sqlalchemy import text as _text

    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    entity_type = str(body.get("entity_type") or "").strip().lower()
    if entity_type not in _NOTE_LINK_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity_type")

    note = (await db.execute(
        select(Note).where(
            Note.id == note_id, Note.tenant_id == tenant_id, Note.created_by == user_id,
            Note.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    entity_id = body.get("entity_id")
    await db.execute(_text(
        "INSERT INTO nexus_crm.note_link_dismissals (tenant_id, note_id, entity_type, entity_id)"
        " VALUES (:t, :n, :e, :i)"
        " ON CONFLICT (note_id, entity_type, entity_id) DO NOTHING"
    ), {
        "t": str(tenant_id),
        "n": str(note_id),
        "e": entity_type,
        "i": str(entity_id) if entity_id else None,
    })
    return None


# ===========================================================================
# NOTES V2 (T3.2) — Media upload (image / video / attachment / voice)
# ===========================================================================

NOTES_MEDIA_DIR = Path(__file__).resolve().parents[2] / "uploads" / "notes"
MAX_NOTE_MEDIA_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/notes/media", status_code=201)
async def upload_note_media(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Notes v2 (T3.2) — upload media for a note.

    Stores the file under backend/uploads/notes using an unguessable UUID
    filename and returns a persistent URL that any session can open (NOT a
    blob: URL). Reuses the existing name-card storage pattern.
    """
    import uuid as _uuid
    from pathlib import Path as _Path

    _get_tenant_id(request)  # auth + tenant context gate

    NOTES_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = (_Path(file.filename or "file.bin").suffix or "").lower()[:10]
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
        ext = ""
    fname = f"{_uuid.uuid4().hex}{ext}"

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_NOTE_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100MB)")

    (NOTES_MEDIA_DIR / fname).write_bytes(content)

    return {
        "url": f"/api/v1/crm/notes/media/{fname}",
        "filename": file.filename or fname,
        "content_type": file.content_type or "application/octet-stream",
        "size": len(content),
    }


@router.get("/notes/media/{filename}")
async def serve_note_media(request: Request, filename: str):
    """Serve stored note media.

    Same approach as /name-cards/image/{filename}: unguessable UUID filename
    so the URL stays openable across sessions / tabs without extra headers.
    """
    from fastapi.responses import FileResponse

    safe = Path(filename).name
    path = NOTES_MEDIA_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path)


# ===========================================================================
# ACTIVITY LOG  (read‑only + create; no update / delete)
# ===========================================================================


@router.get("/activity-log", response_model=ListResponse[ActivityLogResponse])
async def list_activity_log(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    entity_type: str | None = None,
    action: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(ActivityLog).where(ActivityLog.tenant_id == tenant_id)

    if entity_type:
        base = base.where(ActivityLog.entity_type == entity_type)
    if action:
        base = base.where(ActivityLog.action == action)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/activity-log", response_model=ActivityLogResponse, status_code=201)
async def create_activity_log_entry(
    request: Request,
    body: ActivityLogCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    entry = ActivityLog(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_id=user_id or body.actor_id if hasattr(body, "actor_id") else user_id,
        **body.model_dump(),
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.get("/activity-log/{log_id}", response_model=ActivityLogResponse)
async def get_activity_log_entry(
    request: Request,
    log_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(ActivityLog).where(
            ActivityLog.id == log_id, ActivityLog.tenant_id == tenant_id
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="ActivityLog entry not found")
    return entry


# ===========================================================================
# TAGS
# ===========================================================================


@router.get("/tags", response_model=ListResponse[TagResponse])
async def list_tags(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    entity_type: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Tag).where(Tag.tenant_id == tenant_id)

    if search:
        base = base.where(Tag.name.ilike(f"%{search}%"))
    if entity_type:
        base = base.where(Tag.entity_type == entity_type)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Tag.name.asc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()

    return ListResponse(items=list(rows), total=total)


@router.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    request: Request,
    body: TagCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    tag = Tag(
        tenant_id=tenant_id,
        **body.model_dump(),
    )
    db.add(tag)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="tag",
        entity_id=tag.id,
        summary=f"Created tag '{tag.name}'",
    )

    await db.refresh(tag)
    return tag


@router.get("/tags/{tag_id}", response_model=TagResponse)
async def get_tag(
    request: Request,
    tag_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.tenant_id == tenant_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.patch("/tags/{tag_id}", response_model=TagResponse)
async def update_tag(
    request: Request,
    tag_id: UUID,
    body: TagUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.tenant_id == tenant_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
        changes[field] = str(value)

    tag.updated_at = datetime.now(timezone.utc) if hasattr(tag, 'updated_at') else None

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="tag",
        entity_id=tag.id,
        summary=f"Updated tag '{tag.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    request: Request,
    tag_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.tenant_id == tenant_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    name = tag.name
    await db.delete(tag)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="tag",
        entity_id=tag_id,
        summary=f"Deleted tag '{name}'",
    )

    return None


# ===========================================================================
# NAMECARD TAGS (V2 module) — dedicated tag definitions for name cards
# ===========================================================================

@router.get("/namecard-tags", response_model=ListResponse[NameCardTagResponse])
async def list_namecard_tags(
    request: Request,
    with_counts: bool = False,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List name card tags. When with_counts=true, each tag carries the number
    of name_cards whose tags[] array contains that label."""
    tenant_id = _get_tenant_id(request)
    rows = (await db.execute(
        select(NameCardTag).where(NameCardTag.tenant_id == tenant_id).order_by(NameCardTag.label.asc())
    )).scalars().all()

    label_counts: dict[str, int] = {}
    if with_counts:
        cards = (await db.execute(
            select(NameCard.tags).where(NameCard.tenant_id == tenant_id)
        )).scalars().all()
        for tg_list in cards:
            for label in (tg_list or []):
                label_counts[label] = label_counts.get(label, 0) + 1

    items = [
        NameCardTagResponse(
            id=t.id, tenant_id=t.tenant_id, label=t.label, color=t.color,
            usage_count=label_counts.get(t.label, 0), created_at=t.created_at,
        )
        for t in rows
    ]
    return ListResponse(items=items, total=len(items))


@router.post("/namecard-tags", response_model=NameCardTagResponse, status_code=201)
async def create_namecard_tag(
    request: Request,
    body: NameCardTagCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(status_code=422, detail="label is required")
    dup = (await db.execute(
        select(NameCardTag).where(NameCardTag.tenant_id == tenant_id, NameCardTag.label == label)
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail=f"Tag '{label}' already exists")
    tag = NameCardTag(tenant_id=tenant_id, label=label, color=body.color)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id, action="created",
        entity_type="namecard_tag", entity_id=tag.id, summary=f"Created namecard tag '{label}'",
        workspace_id=getattr(request.state, "workspace_id", None),
    )
    usage_count = 0  # a fresh tag has no cards attached yet
    return NameCardTagResponse(
        id=tag.id, tenant_id=tag.tenant_id, label=tag.label,
        color=tag.color, usage_count=usage_count, created_at=tag.created_at,
    )


@router.patch("/namecard-tags/{tag_id}", response_model=NameCardTagResponse)
async def update_namecard_tag(
    request: Request,
    tag_id: UUID,
    body: NameCardTagUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    tag = (await db.execute(
        select(NameCardTag).where(NameCardTag.id == tag_id, NameCardTag.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="NameCard tag not found")
    changes: list[str] = []
    if body.label is not None and body.label.strip() and body.label.strip() != tag.label:
        old_label = tag.label
        tag.label = body.label.strip()
        # Keep name_cards in sync: relabel every card carrying the old label.
        cards = (await db.execute(
            select(NameCard).where(NameCard.tenant_id == tenant_id)
        )).scalars().all()
        for card in cards:
            tg = card.tags or []
            if old_label in tg:
                card.tags = [old_label if x == old_label else x for x in tg]
        changes.append(f"label {old_label}→{tag.label}")
    if body.color is not None and body.color != tag.color:
        tag.color = body.color
        changes.append("color")
    if changes:
        await _log_activity(
            db, tenant_id=tenant_id, actor_id=user_id, action="updated",
            entity_type="namecard_tag", entity_id=tag_id, summary=f"Updated namecard tag: {', '.join(changes)}",
            workspace_id=getattr(request.state, "workspace_id", None),
        )
    await db.flush()
    await db.refresh(tag)
    return NameCardTagResponse(
        id=tag.id, tenant_id=tag.tenant_id, label=tag.label,
        color=tag.color, usage_count=0, created_at=tag.created_at,
    )


@router.delete("/namecard-tags/{tag_id}", status_code=204)
async def delete_namecard_tag(
    request: Request,
    tag_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a tag definition and strip its label from every name_card."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    tag = (await db.execute(
        select(NameCardTag).where(NameCardTag.id == tag_id, NameCardTag.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="NameCard tag not found")
    label = tag.label
    cards = (await db.execute(
        select(NameCard).where(NameCard.tenant_id == tenant_id)
    )).scalars().all()
    for card in cards:
        tg = card.tags or []
        if label in tg:
            card.tags = [x for x in tg if x != label]
    await db.delete(tag)
    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id, action="deleted",
        entity_type="namecard_tag", entity_id=tag_id, summary=f"Deleted namecard tag '{label}'",
        workspace_id=getattr(request.state, "workspace_id", None),
    )
    return None


@router.post("/namecard-tags/merge", response_model=ListResponse[NameCardTagResponse])
async def merge_namecard_tags(
    request: Request,
    body: NameCardTagMergeRequest,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Merge several tag definitions into one survivor label. Every name_card
    carrying any of the merged labels is relabelled to the survivor."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    into_label = (body.into_label or "").strip()
    if not into_label or len(body.tag_ids) < 1:
        raise HTTPException(status_code=422, detail="into_label and at least one tag_id required")
    tags = (await db.execute(
        select(NameCardTag).where(
            NameCardTag.tenant_id == tenant_id, NameCardTag.id.in_(body.tag_ids)
        )
    )).scalars().all()
    if not tags:
        raise HTTPException(status_code=404, detail="None of the tag ids found")
    old_labels = [t.label for t in tags if t.label != into_label]
    # Relabel cards
    cards = (await db.execute(
        select(NameCard).where(NameCard.tenant_id == tenant_id)
    )).scalars().all()
    for card in cards:
        tg = card.tags or []
        if any(x in tg for x in old_labels):
            card.tags = [into_label if x in old_labels else x for x in tg]
    # Keep survivor definition (or create one if it didn't exist)
    survivor = (await db.execute(
        select(NameCardTag).where(NameCardTag.tenant_id == tenant_id, NameCardTag.label == into_label)
    )).scalar_one_or_none()
    if not survivor:
        survivor = NameCardTag(tenant_id=tenant_id, label=into_label, color=tags[0].color)
        db.add(survivor)
    # Delete the merged-away definitions (except the survivor itself)
    for t in tags:
        if t.label != into_label:
            await db.delete(t)
    await db.flush()
    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id, action="updated",
        entity_type="namecard_tag", entity_id=survivor.id,
        summary=f"Merged {len(old_labels)} tag(s) into '{into_label}'",
        workspace_id=getattr(request.state, "workspace_id", None),
    )
    rows = (await db.execute(
        select(NameCardTag).where(NameCardTag.tenant_id == tenant_id).order_by(NameCardTag.label.asc())
    )).scalars().all()
    return ListResponse(items=[
        NameCardTagResponse(id=t.id, tenant_id=t.tenant_id, label=t.label, color=t.color, usage_count=0, created_at=t.created_at)
        for t in rows
    ], total=len(rows))


@router.post("/namecard-tags/ai-cleanup-scan", response_model=NameCardTagCleanupResponse)
async def namecard_tags_ai_cleanup_scan(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Proactively suggest near-duplicate tags to merge. Uses simple string
    similarity (token-sorted ratio) on the merged label surface. Production can
    swap this for embedding-based semantic matching."""
    tenant_id = _get_tenant_id(request)
    rows = (await db.execute(
        select(NameCardTag).where(NameCardTag.tenant_id == tenant_id)
    )).scalars().all()
    labels = sorted({t.label for t in rows})
    groups: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            key = tuple(sorted([a, b]))
            if key in seen:
                continue
            ratio = _token_sort_ratio(a, b)
            if ratio >= 70:
                seen.add(key)
                survivor = max(a, b, key=lambda x: _usage_or_0(x, rows))
                groups.append({
                    "tag_ids": [_def_id(label, rows) for label in (a, b)],
                    "group_label": survivor,
                    "reason": f"字面相似度 {ratio}%",
                })
    return NameCardTagCleanupResponse(groups=groups)


def _token_sort_ratio(a: str, b: str) -> int:
    import re
    norm = lambda s: sorted(re.findall(r"[\w]+|[\u4e00-\u9fff]+", s.lower()))
    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return 0
    seta, setb = set(ta), set(tb)
    inter = seta & setb
    union = seta | setb
    if not union:
        return 0
    return int(round(len(inter) / len(union) * 100))


def _usage_or_0(label: str, rows) -> int:
    # rough proxy for choosing survivor: longer/most common label wins
    return len(label)


def _def_id(label: str, rows):
    for r in rows:
        if r.label == label:
            return r.id
    raise HTTPException(status_code=404, detail=f"Tag '{label}' missing")


# ===========================================================================
# PROJECTS
# ===========================================================================


@router.get("/projects", response_model=ListResponse[ProjectResponse])
async def list_projects(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    base = select(Project).where(Project.tenant_id == tenant_id).options(selectinload(Project.company))

    if search:
        base = base.where(Project.name.ilike(f"%{search}%"))
    if status:
        base = base.where(Project.status == status)
    if priority:
        base = base.where(Project.priority == priority)
    if company_id:
        base = base.where(Project.company_id == company_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = base.order_by(Project.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(items_q)).scalars().all()
    items = []
    for p in rows:
        item = p.__dict__.copy()
        if p.company:
            item['company'] = {'id': str(p.company.id), 'name': p.company.name}
        items.append(item)
    return ListResponse(items=items, total=total)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: Request,
    body: ProjectCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    project = Project(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        **body.model_dump(),
    )
    db.add(project)
    await db.flush()

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="created",
        entity_type="project",
        entity_id=project.id,
        summary=f"Created project '{project.name}'",
        workspace_id=workspace_id,
    )

    # ── Notification: project assigned to a PM/sales owner (not the creator) ──
    target = project.project_manager_id or project.sales_owner_id
    if target and target != user_id:
        from app.services.notification_service import notify
        await notify(
            db,
            tenant_id=tenant_id,
            user_id=target,
            module="project",
            title=f"📁 你被指派項目：{project.name}",
            body=project.description or f"Deadline: {project.deadline or '未設定'}",
            priority="HIGH" if project.priority == "high" else "NORMAL",
            action_url="/projects",
            group_key=f"project-assign-{project.id}",
            source_record_type="project",
            source_record_id=project.id,
        )

    await db.refresh(project)
    result = await db.execute(
        select(Project).options(selectinload(Project.company)).where(Project.id == project.id)
    )
    project = result.scalar_one()
    item = project.__dict__.copy()
    if project.company:
        item['company'] = {'id': str(project.company.id), 'name': project.company.name}
    return item


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id).options(selectinload(Project.company))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    item = project.__dict__.copy()
    if project.company:
        item['company'] = {'id': str(project.company.id), 'name': project.company.name}
    return item


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    request: Request,
    project_id: UUID,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    changes = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
        changes[field] = str(value)

    project.updated_at = datetime.now(timezone.utc)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="updated",
        entity_type="project",
        entity_id=project.id,
        summary=f"Updated project '{project.name}'",
        changes=changes,
    )

    await db.flush()
    await db.refresh(project)
    result = await db.execute(
        select(Project).options(selectinload(Project.company)).where(Project.id == project.id)
    )
    project = result.scalar_one()
    item = project.__dict__.copy()
    if project.company:
        item['company'] = {'id': str(project.company.id), 'name': project.company.name}
    return item


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    name = project.name
    await db.delete(project)

    await _log_activity(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="deleted",
        entity_type="project",
        entity_id=project_id,
        summary=f"Deleted project '{name}'",
    )

    return None


# ===========================================================================
# Project Calendar Event CRUD
# ===========================================================================


@router.get("/calendar-events", response_model=list[ProjectCalendarEventResponse])
async def list_all_calendar_events(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = getattr(request.state, "user_id", None)
    base = (
        select(ProjectCalendarEvent)
        .where(
            ProjectCalendarEvent.tenant_id == tenant_id,
            # per-user calendar isolation: own events + shared (no-owner) ones
            (ProjectCalendarEvent.owner_user_id == user_id)
            | (ProjectCalendarEvent.owner_user_id.is_(None)),
        )
        .order_by(ProjectCalendarEvent.start.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(base)
    return result.scalars().all()


@router.get("/calendar-events/{event_id}", response_model=ProjectCalendarEventResponse)
async def get_calendar_event(
    event_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Fetch a single calendar event by id — powers IM-push deep links (/l/m/{id})."""
    tenant_id = _get_tenant_id(request)
    user_id = getattr(request.state, "user_id", None)
    evt = (
        await db.execute(
            select(ProjectCalendarEvent).where(
                ProjectCalendarEvent.tenant_id == tenant_id,
                ProjectCalendarEvent.id == event_id,
                # per-user calendar isolation: own events + shared (no-owner) ones
                (ProjectCalendarEvent.owner_user_id == user_id)
                | (ProjectCalendarEvent.owner_user_id.is_(None)),
            )
        )
    ).scalar_one_or_none()
    if not evt:
        raise HTTPException(404, "Event not found")
    return evt


@router.get("/projects/{project_id}/calendar-events", response_model=list[ProjectCalendarEventResponse])
async def list_calendar_events(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(ProjectCalendarEvent).where(
            ProjectCalendarEvent.tenant_id == tenant_id,
            ProjectCalendarEvent.project_id == project_id,
        ).order_by(ProjectCalendarEvent.start)
    )
    rows = result.scalars().all()
    return list(rows)


@router.post("/projects/{project_id}/calendar-events", response_model=ProjectCalendarEventResponse, status_code=201)
async def create_calendar_event(
    request: Request,
    project_id: UUID,
    body: ProjectCalendarEventCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = ProjectCalendarEvent(
        tenant_id=tenant_id,
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        event_type=body.event_type or "milestone",
        start=body.start,
        end=body.end,
        is_all_day=body.is_all_day or False,
        color=body.color or "#00693E",
        location=body.location,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="calendar_event", entity_id=obj.id,
        summary=f"Created calendar event '{obj.title}' for project",
    )
    return obj


@router.post("/calendar-events", response_model=ProjectCalendarEventResponse, status_code=201)
async def create_calendar_event_standalone(
    request: Request,
    body: ProjectCalendarEventCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    obj = ProjectCalendarEvent(
        tenant_id=tenant_id,
        owner_user_id=user_id,           # ← 獨立 event 屬於自己（唔係 sync 嘅）
        project_id=body.project_id,       # 可以 None = 獨立 event
        title=body.title,
        description=body.description,
        event_type=body.event_type or "milestone",
        start=body.start,
        end=body.end,
        is_all_day=body.is_all_day or False,
        color=body.color or "#00693E",
        location=body.location,
        source="manual",                 # ← 標記手動建立（唔會被 sync delete）
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="created", entity_type="calendar_event", entity_id=obj.id,
        summary=f"Created calendar event '{obj.title}'",
    )
    return obj


@router.patch("/calendar-events/{event_id}", response_model=ProjectCalendarEventResponse)
async def update_calendar_event(
    request: Request,
    event_id: UUID,
    body: ProjectCalendarEventUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(ProjectCalendarEvent).where(
            ProjectCalendarEvent.id == event_id,
            ProjectCalendarEvent.tenant_id == tenant_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    for field in ("title", "description", "event_type", "start", "end", "is_all_day", "color", "location"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(obj, field, val)
    obj.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(obj)

    # ── Notification: event rescheduled (notify owner if someone else changed it) ──
    changed_time = body.start is not None or body.end is not None
    if changed_time and obj.owner_user_id and obj.owner_user_id != user_id:
        from app.services.notification_service import notify
        await notify(
            db,
            tenant_id=tenant_id,
            user_id=obj.owner_user_id,
            module="calendar",
            title=f"🔄 日程已改期：{obj.title}",
            body=f"新時間：{obj.start.strftime('%m-%d %H:%M') if obj.start else '?'}",
            priority="NORMAL",
            action_url="/calendar",
            group_key=f"cal-resched-{obj.id}",
            source_record_type="calendar_event",
            source_record_id=obj.id,
        )

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="updated", entity_type="calendar_event", entity_id=obj.id,
        summary=f"Updated calendar event '{obj.title}'",
    )
    return obj


@router.delete("/calendar-events/{event_id}", status_code=204)
async def delete_calendar_event(
    request: Request,
    event_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    result = await db.execute(
        select(ProjectCalendarEvent).where(
            ProjectCalendarEvent.id == event_id,
            ProjectCalendarEvent.tenant_id == tenant_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    title = obj.title
    await db.delete(obj)

    await _log_activity(
        db, tenant_id=tenant_id, actor_id=user_id,
        action="deleted", entity_type="calendar_event", entity_id=event_id,
        summary=f"Deleted calendar event '{title}'",
    )
    return None


# ===========================================================================
# Global CRM Search — unified search across all entities
# ===========================================================================


@router.get("/search")
async def global_crm_search(
    request: Request,
    q: str,
    limit: int = 10,
    types: str = Query("", description="Comma-separated entity types to filter (contact,company,deal,task,project,touchpoint,note). Empty = all."),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Search across all CRM entities (contacts, companies, deals, tasks,
    projects, touchpoints, notes) using a single UNION ALL query.

    Returns a flat result list with id, type, label, sub, url.
    """
    tenant_id = _get_tenant_id(request)
    pattern = f"%{q}%"
    type_list = [t.strip() for t in types.split(",") if t.strip()] if types else []
    # Whitelist guard — these values are inlined into SQL below (safe: fixed
    # enum of entity types, no user free-text).
    _VALID_TYPES = {"contact", "company", "deal", "task", "project", "touchpoint", "note"}
    type_list = [t for t in type_list if t in _VALID_TYPES]

    # ── Type filter (whitelist inline — safe: fixed entity-type enum) ──
    type_where = ""
    count_type_where = ""
    if type_list:
        safe = ",".join(f"'{t}'" for t in type_list)
        type_where = f"WHERE results.type IN ({safe})"
        count_type_where = f"WHERE cnt.type IN ({safe})"

    # ── Main data query with UNION ALL ────────────────────────────────
    data_sql = text(
        """
        SELECT id, type, label, sub, url
        FROM (
            SELECT
                c.id::text                AS id,
                'contact'                 AS type,
                c.name                    AS label,
                COALESCE(c.email, '')     AS sub,
                '/contacts/' || c.id::text AS url
            FROM nexus_crm.contacts c
            WHERE c.tenant_id = :tenant_id
              AND (c.name       ILIKE :q
                OR c.email      ILIKE :q
                OR c.phone      ILIKE :q
                OR c.chinese_name ILIKE :q)

            UNION ALL

            SELECT
                co.id::text                 AS id,
                'company'                   AS type,
                co.name                     AS label,
                COALESCE(co.industry, '')   AS sub,
                '/companies/' || co.id::text AS url
            FROM nexus_crm.companies co
            WHERE co.tenant_id = :tenant_id
              AND (co.name     ILIKE :q
                OR co.domain   ILIKE :q
                OR co.industry ILIKE :q)

            UNION ALL

            SELECT
                d.id::text                AS id,
                'deal'                    AS type,
                d.name                    AS label,
                ''                        AS sub,
                '/deals/' || d.id::text   AS url
            FROM nexus_crm.deals d
            WHERE d.tenant_id = :tenant_id
              AND (d.name  ILIKE :q
                OR d.notes ILIKE :q)

            UNION ALL

            SELECT
                t.id::text               AS id,
                'task'                   AS type,
                t.title                  AS label,
                ''                       AS sub,
                '/tasks/' || t.id::text  AS url
            FROM nexus_crm.tasks t
            WHERE t.tenant_id = :tenant_id
              AND t.title ILIKE :q

            UNION ALL

            SELECT
                p.id::text                 AS id,
                'project'                  AS type,
                p.name                     AS label,
                ''                         AS sub,
                '/projects/' || p.id::text AS url
            FROM nexus_crm.projects p
            WHERE p.tenant_id = :tenant_id
              AND p.name ILIKE :q

            UNION ALL

            SELECT
                tp.id::text                   AS id,
                'touchpoint'                  AS type,
                tp.title                      AS label,
                ''                            AS sub,
                '/touchpoints/' || tp.id::text AS url
            FROM nexus_crm.touchpoints tp
            WHERE tp.tenant_id = :tenant_id
              AND tp.title ILIKE :q

            UNION ALL

            SELECT
                n.id::text               AS id,
                'note'                   AS type,
                COALESCE(n.title, '')    AS label,
                LEFT(COALESCE(n.content, ''), 200) AS sub,
                '/notes/' || n.id::text  AS url
            FROM nexus_crm.notes n
            WHERE n.tenant_id = :tenant_id
              AND (n.title   ILIKE :q
                OR n.content ILIKE :q)
        ) results
        {type_where}
        LIMIT :limit
        """.format(type_where=type_where)
    )

    # ── Count query (same filters, no data) ───────────────────────────
    count_sql = text(
        """
        SELECT COUNT(*) FROM (
            SELECT 'contact' AS type, c.id FROM nexus_crm.contacts c
             WHERE c.tenant_id = :tenant_id
               AND (c.name ILIKE :q OR c.email ILIKE :q OR c.phone ILIKE :q OR c.chinese_name ILIKE :q)
            UNION ALL
            SELECT 'company' AS type, co.id FROM nexus_crm.companies co
             WHERE co.tenant_id = :tenant_id
               AND (co.name ILIKE :q OR co.domain ILIKE :q OR co.industry ILIKE :q)
            UNION ALL
            SELECT 'deal' AS type, d.id FROM nexus_crm.deals d
             WHERE d.tenant_id = :tenant_id
               AND (d.name ILIKE :q OR d.notes ILIKE :q)
            UNION ALL
            SELECT 'task' AS type, t.id FROM nexus_crm.tasks t
             WHERE t.tenant_id = :tenant_id AND t.title ILIKE :q
            UNION ALL
            SELECT 'project' AS type, p.id FROM nexus_crm.projects p
             WHERE p.tenant_id = :tenant_id AND p.name ILIKE :q
            UNION ALL
            SELECT 'touchpoint' AS type, tp.id FROM nexus_crm.touchpoints tp
             WHERE tp.tenant_id = :tenant_id AND tp.title ILIKE :q
            UNION ALL
            SELECT 'note' AS type, n.id FROM nexus_crm.notes n
             WHERE n.tenant_id = :tenant_id
               AND (n.title ILIKE :q OR n.content ILIKE :q)
        ) cnt
        {type_where}
        """.format(type_where=count_type_where)
    )

    params = {"tenant_id": tenant_id, "q": pattern, "limit": limit}

    rows = (await db.execute(data_sql, params)).fetchall()
    total = (await db.execute(count_sql, params)).scalar() or 0

    results = [
        {
            "id": row.id,
            "type": row.type,
            "label": row.label,
            "sub": row.sub,
            "url": row.url,
        }
        for row in rows
    ]

    return {"results": results, "total": total}

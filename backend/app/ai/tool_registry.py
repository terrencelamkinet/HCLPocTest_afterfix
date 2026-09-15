"""
Tool registry — canonical catalog of all AI-callable tools.

Every tool that the AI layer can invoke is registered in TOOL_REGISTRY.
Handlers call SQLAlchemy models directly (no service layer dependency).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Coroutine
from uuid import UUID

from sqlalchemy import and_, func, select, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.session.context import AISessionContext
from app.models.crm import (
    Company,
    Contact,
    NameCard,
    Note,
    NoteLink,
    Project,
    ProjectCalendarEvent,
    Task,
    Touchpoint,
    TouchpointParticipant,
)
from app.models.crm_module_b import Deal, DealStage
from app.models.crm_module_c import ProjectStage  # noqa: F401 — registers projects.stage_id FK target
from app.models.ai.user_memory import UserMemory

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDef:
    """Definition of a single tool the AI agent can call."""

    key: str
    type: str  # "read" | "write"
    module: str  # dotted module path, e.g. "app.services.crm.companies"
    requires_confirmation: bool = False
    handler: Callable[..., Coroutine[Any, Any, Any]] | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper: convert an ORM row to a plain dict
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance to a dict, coercing UUIDs to strings."""
    d = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, UUID):
            val = str(val)
        elif isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def _contact_with_company(row: Any) -> dict[str, Any]:
    """Serialize a Contact incl. resolved company name (eager-loaded via selectinload)."""
    d = _row_to_dict(row)
    comp = getattr(row, "company", None)
    if comp is not None:
        d["company"] = {"id": str(comp.id), "name": comp.name}
    return d


# ---------------------------------------------------------------------------
# 10 READ tool handlers
# ---------------------------------------------------------------------------


async def _search_companies(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Search companies by name or domain, tenant-scoped. Fuzzy fallback via pg_trgm."""
    query = params.get("query", "")
    limit = min(params.get("limit", 20), 100)

    # Step 1: ILIKE exact/substring match
    base = select(Company).where(Company.tenant_id == ctx.tenant_id)
    if query:
        base = base.where(
            or_(
                Company.name.ilike(f"%{query}%"),
                Company.domain.ilike(f"%{query}%"),
            )
        )
    base = base.order_by(Company.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    if rows:
        return [_row_to_dict(r) for r in rows]

    # Step 2: Fuzzy trigram fallback (handles typos like "systexx" → "SYSTEX")
    if query:
        fuzzy = await db.execute(
            text("""
                SELECT id FROM nexus_crm.companies
                WHERE tenant_id = :tid
                AND (similarity(name, :q) > 0.2 OR similarity(domain, :q) > 0.2)
                ORDER BY similarity(name, :q) DESC
                LIMIT :lim
            """),
            {"tid": ctx.tenant_id, "q": query, "lim": limit},
        )
        fids = [r[0] for r in fuzzy.fetchall()]
        if fids:
            base = select(Company).where(Company.id.in_(fids)).order_by(Company.created_at.desc())
            rows = (await db.execute(base)).scalars().all()
            return [_row_to_dict(r) for r in rows]

    return []


async def _get_company_detail(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Get a single company by UUID."""
    company_id = UUID(params["company_id"])
    result = await db.execute(
        select(Company).where(
            Company.id == company_id, Company.tenant_id == ctx.tenant_id
        )
    )
    company = result.scalar_one_or_none()
    if not company:
        return None
    return _row_to_dict(company)


async def _search_contacts(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Search contacts by name, email or phone, tenant-scoped. Fuzzy fallback via pg_trgm."""
    query = params.get("query", "")
    limit = min(params.get("limit", 20), 100)
    company_id = params.get("company_id")

    # Step 1: ILIKE match
    base = (
        select(Contact)
        .options(selectinload(Contact.company))
        .where(Contact.tenant_id == ctx.tenant_id)
    )

    if query:
        base = base.where(
            or_(
                Contact.name.ilike(f"%{query}%"),
                Contact.chinese_name.ilike(f"%{query}%"),
                Contact.email.ilike(f"%{query}%"),
                Contact.phone.ilike(f"%{query}%"),
            )
        )
    if company_id:
        base = base.where(Contact.company_id == UUID(company_id))

    base = base.order_by(Contact.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    if rows:
        return [_contact_with_company(r) for r in rows]

    # Step 2: Fuzzy trigram fallback
    if query:
        fuzzy = await db.execute(
            text("""
                SELECT id FROM nexus_crm.contacts
                WHERE tenant_id = :tid
                AND (similarity(name, :q) > 0.2 OR similarity(chinese_name, :q) > 0.2 OR similarity(email, :q) > 0.2)
                ORDER BY similarity(name, :q) DESC
                LIMIT :lim
            """),
            {"tid": ctx.tenant_id, "q": query, "lim": limit},
        )
        fids = [r[0] for r in fuzzy.fetchall()]
        if fids:
            base = (
                select(Contact)
                .options(selectinload(Contact.company))
                .where(Contact.id.in_(fids))
                .order_by(Contact.created_at.desc())
            )
            rows = (await db.execute(base)).scalars().all()
            return [_contact_with_company(r) for r in rows]

    return []


async def _get_contact_detail(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    """Get a single contact by UUID."""
    contact_id = UUID(params["contact_id"])
    result = await db.execute(
        select(Contact)
        .options(selectinload(Contact.company))
        .where(Contact.id == contact_id, Contact.tenant_id == ctx.tenant_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        return None
    d = _row_to_dict(contact)
    if contact.company:
        d["company"] = {"id": str(contact.company.id), "name": contact.company.name}
    return d


async def _search_projects(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Search projects by name/code, optionally filtered by status/company."""
    query = params.get("query", "")
    status = params.get("status")
    company_id = params.get("company_id")
    limit = min(params.get("limit", 20), 100)

    base = (
        select(Project)
        .options(selectinload(Project.company))
        .where(Project.tenant_id == ctx.tenant_id)
    )

    if query:
        base = base.where(Project.name.ilike(f"%{query}%"))
    if status:
        base = base.where(Project.status == status)
    if company_id:
        base = base.where(Project.company_id == UUID(company_id))

    base = base.order_by(Project.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        if r.company:
            d["company"] = {"id": str(r.company.id), "name": r.company.name}
        items.append(d)
    return items


async def _search_notes(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Search notes by title/content — tenant + **owner** scoped.

    空 query = 攞最近 updated_at 嘅筆記（跟其他 search_* tool 嘅既有慣例）。
    回傳 shape 固定（AI context / citation / 前端 deep link 用）：
    id / title / snippet / updated_at / url（有 record filter 時多一個 relation）。

    ⚠️ 2026-09-13 修正：筆記係**私人**嘅 —— `list_notes`（crm.py）filter
    `created_by == user_id`（SPEC Q6），RAG 索引亦因此故意唔收 notes
    （reindex.py `NOTE_INDEXING_ENABLED = False`，怕 tenant 共享索引漏私人筆記）。
    所以呢度一定要跟返 owner filter；唔係嘅話同事嘅私人筆記會經 AI 漏出去。

    🆕 spec §16：可傳 contact_id / company_id / project_id / task_id 攞「呢個
    record 嘅相關筆記」。關係一律用 durable relation：notes 自己嘅 FK ＋
    `note_links`（@mention 由 server 從 canonical content 抽出）——
    **唔靠文字相似去猜關係**。relation = attached（FK）／mention（note_links）。
    """
    query = (params.get("query") or "").strip()
    limit = min(int(params.get("limit", 20)), 100)

    def _as_uuid(v: Any) -> UUID | None:
        try:
            return UUID(str(v))
        except (TypeError, ValueError):
            return None

    # record filter → (note_links entity_type, uuid, notes 自己嘅 FK 欄)
    _rec_cols = {
        "contact_id": ("contact", Note.contact_id),
        "company_id": ("company", Note.company_id),
        "project_id": ("project", Note.project_id),
        "task_id": ("task", Note.task_id),
    }
    recs: list[tuple[str, UUID, Any]] = []
    for _key, (_etype, _col) in _rec_cols.items():
        if params.get(_key):
            _uid = _as_uuid(params.get(_key))
            if _uid:
                recs.append((_etype, _uid, _col))

    base = select(Note).where(
        Note.tenant_id == ctx.tenant_id,
        Note.created_by == ctx.user_id,  # 私人筆記：只搜自己寫嘅（同 list_notes 一致）
        Note.deleted_at.is_(None),  # Notes V2 soft delete — 正常 query 一律 filter
    )

    mention_ids: set[UUID] = set()
    if recs:
        linked = select(NoteLink.note_id).where(
            NoteLink.tenant_id == ctx.tenant_id,
            or_(*[
                and_(NoteLink.entity_type == _et, NoteLink.entity_id == _uid)
                for _et, _uid, _ in recs
            ]),
        )
        mention_ids = {nid for nid in (await db.execute(linked)).scalars().all() if nid}
        base = base.where(
            or_(*[_col == _uid for _, _uid, _col in recs], Note.id.in_(mention_ids))
        )

    if query:
        base = base.where(
            or_(
                Note.title.ilike(f"%{query}%"),
                Note.content.ilike(f"%{query}%"),
            )
        )
    base = base.order_by(Note.updated_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    items: list[dict[str, Any]] = []
    for r in rows:
        # content 可能係 editor 出嘅 HTML → 去 tag 再壓空白做 snippet
        snippet = re.sub(r"<[^>]+>", " ", r.content or "")
        snippet = " ".join(snippet.split())[:200]
        title = (r.title or "").strip()
        if not title:
            # 空 title 唔好出空白 label — 用 content 首 40 字代替
            title = snippet[:40] or "(無標題筆記)"
        item = {
            "id": str(r.id),
            "title": title,
            "snippet": snippet,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "url": f"/notes/{r.id}",
        }
        if recs:
            # 畀 AI 睇到關係來源（spec §16：帶 relation 以便引用）
            item["relation"] = (
                "attached" if any(getattr(r, _col.key) == _uid for _, _uid, _col in recs) else "mention"
            )
        items.append(item)
    return items


async def _list_tasks(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """List tasks, optionally filtered by project/assignee/status/contact/company."""
    project_id = params.get("project_id")
    assignee_id = params.get("assignee_id")
    status = params.get("status")
    contact_id = params.get("contact_id")
    company_id = params.get("company_id")
    limit = min(params.get("limit", 50), 200)

    base = (
        select(Task)
        .options(selectinload(Task.company))
        .where(Task.tenant_id == ctx.tenant_id)
    )

    if project_id:
        base = base.where(Task.deal_id == UUID(project_id))
    if assignee_id:
        base = base.where(Task.assignee_id == UUID(assignee_id))
    if status:
        base = base.where(Task.status == status)
    if contact_id:
        base = base.where(Task.contact_id == UUID(contact_id))
    if company_id:
        base = base.where(Task.company_id == UUID(company_id))

    base = base.order_by(Task.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        if r.company:
            d["company"] = {"id": str(r.company.id), "name": r.company.name}
        d["parent_task_id"] = str(r.parent_task_id) if r.parent_task_id else None
        items.append(d)
    return items


async def _list_touchpoints(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """List touchpoints, optionally filtered by company or contact."""
    company_id = params.get("company_id")
    contact_id = params.get("contact_id")
    limit = min(params.get("limit", 50), 200)

    base = (
        select(Touchpoint)
        .options(selectinload(Touchpoint.company), selectinload(Touchpoint.participants))
        .where(Touchpoint.tenant_id == ctx.tenant_id)
    )

    if contact_id:
        base = base.where(
            Touchpoint.id.in_(
                select(TouchpointParticipant.touchpoint_id).where(
                    TouchpointParticipant.contact_id == UUID(contact_id),
                    TouchpointParticipant.tenant_id == ctx.tenant_id,
                )
            )
        )

    if company_id:
        base = base.where(Touchpoint.company_id == UUID(company_id))

    base = base.order_by(Touchpoint.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        if r.company:
            d["company"] = {"id": str(r.company.id), "name": r.company.name}
        d["participants"] = [
            {"id": str(p.id), "name": p.name} for p in r.participants
        ]
        items.append(d)
    return items


async def _get_dashboard_summary(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Aggregate counts from multiple CRM tables for a dashboard overview."""
    tid = ctx.tenant_id
    period_str = params.get("period", "30d")

    # Determine the cutoff date based on period
    cutoff_map = {"7d": 7, "30d": 30, "90d": 90}
    days = cutoff_map.get(period_str, 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Run all counts concurrently
    company_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Company).where(Company.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    contact_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Contact).where(Contact.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    project_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Project).where(Project.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    task_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Task).where(Task.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    open_task_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Task)
                .where(Task.tenant_id == tid, Task.status.in_(["pending", "in_progress"]))
                .subquery()
            )
        )
    ).scalar() or 0

    deal_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Deal).where(Deal.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    open_deal_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Deal).where(Deal.tenant_id == tid, Deal.status == "open").subquery()
            )
        )
    ).scalar() or 0

    # Recent activity — items created in the period
    recent_companies = (
        await db.execute(
            select(func.count()).select_from(
                select(Company)
                .where(Company.tenant_id == tid, Company.created_at >= cutoff)
                .subquery()
            )
        )
    ).scalar() or 0

    recent_contacts = (
        await db.execute(
            select(func.count()).select_from(
                select(Contact)
                .where(Contact.tenant_id == tid, Contact.created_at >= cutoff)
                .subquery()
            )
        )
    ).scalar() or 0

    recent_tasks = (
        await db.execute(
            select(func.count()).select_from(
                select(Task)
                .where(Task.tenant_id == tid, Task.created_at >= cutoff)
                .subquery()
            )
        )
    ).scalar() or 0

    # Touchpoints
    touchpoint_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Touchpoint).where(Touchpoint.tenant_id == tid).subquery()
            )
        )
    ).scalar() or 0

    return {
        "period": period_str,
        "companies": company_count,
        "contacts": contact_count,
        "projects": project_count,
        "tasks": task_count,
        "open_tasks": open_task_count,
        "deals": deal_count,
        "open_deals": open_deal_count,
        "touchpoints": touchpoint_count,
        "recent": {
            "new_companies": recent_companies,
            "new_contacts": recent_contacts,
            "new_tasks": recent_tasks,
        },
    }


async def _search_deals(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Search deals by name, optionally filtered by stage."""
    query = params.get("query", "")
    stage = params.get("stage")
    limit = min(params.get("limit", 20), 100)

    base = select(Deal).where(Deal.tenant_id == ctx.tenant_id)

    if query:
        base = base.where(Deal.name.ilike(f"%{query}%"))
    if stage:
        base = base.where(Deal.stage_id == UUID(stage))

    base = base.order_by(Deal.created_at.desc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["amount"] = float(r.amount) if r.amount is not None else None
        items.append(d)
    return items


async def _get_upcoming_events(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Get upcoming project calendar events."""
    days_ahead = params.get("days_ahead", 30)
    limit = min(params.get("limit", 20), 100)

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=int(days_ahead))

    base = (
        select(ProjectCalendarEvent)
        .where(
            ProjectCalendarEvent.tenant_id == ctx.tenant_id,
            ProjectCalendarEvent.start >= now,
            ProjectCalendarEvent.start <= cutoff,
            # per-user calendar isolation: own events + shared (no-owner) ones.
            # owner_user_id IS NULL = project/workspace events visible to all.
            (ProjectCalendarEvent.owner_user_id == ctx.user_id)
            | (ProjectCalendarEvent.owner_user_id.is_(None)),
        )
        .order_by(ProjectCalendarEvent.start.asc())
        .limit(limit)
    )

    rows = (await db.execute(base)).scalars().all()
    evts = [_row_to_dict(r) for r in rows]

    # T1.2（2026-09-04）：Canceled event 處理 — Outlook/Google sync 會將取消咗
    # 嘅 event 以 title prefix「Canceled: 」另起一條（原 event 保留唔刪）。
    # 9/3 briefing 實證 bug：正常版 + Canceled 版兩條並排出街，canceled 當正常行程。
    # 處理：① Canceled 版 title 剝走 prefix + 標 status=cancelled（照出，等 LLM/
    #     UI 顯示「已取消」+ 原時間）② 有 canceled 對應嘅正常版 skip（避免 duplicate）
    _cancel_keys: set[tuple[str, str]] = set()
    for e in evts:
        t = (e.get("title") or "").strip()
        if t.startswith("Canceled: "):
            _cancel_keys.add((t[len("Canceled: "):].strip(), str(e.get("start") or "")))
    deduped: list[dict[str, Any]] = []
    for e in evts:
        t = (e.get("title") or "").strip()
        if t.startswith("Canceled: "):
            e["title"] = t[len("Canceled: "):].strip()
            e["status"] = "cancelled"  # 原 row 冇 status column — 由 sync prefix 推斷
            deduped.append(e)
        elif (t, str(e.get("start") or "")) in _cancel_keys:
            continue  # 正常版但有 canceled 對應 → 已取消，唔當有效行程出
        else:
            deduped.append(e)
    return deduped


# ---------------------------------------------------------------------------
# 3 WRITE tool handlers (draft-only for now; execute mode not yet implemented)
# ---------------------------------------------------------------------------


async def _create_task_draft(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
    mode: str = "draft",
) -> dict[str, Any]:
    """Validate task creation params and return a preview dict.

    In "draft" mode: validates required fields and returns a preview.
    In "execute" mode: validates and creates the actual Task record.
    """
    errors: list[str] = []
    if not params.get("title"):
        errors.append("'title' is required")

    preview = {
        "action": "create_task",
        "title": params.get("title"),
        "description": params.get("description"),
        "assignee_id": params.get("assignee_id"),
        "due_date": params.get("due_date"),
        "priority": params.get("priority", "medium"),
        "status": "pending",
        "validated": len(errors) == 0,
    }

    if errors:
        preview["errors"] = errors
        return preview

    if mode == "execute":
        task = Task(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            title=params["title"],
            description=params.get("description"),
            assignee_id=UUID(params["assignee_id"]) if params.get("assignee_id") else None,
            due_date=(
                datetime.strptime(params["due_date"], "%Y-%m-%d").date()
                if params.get("due_date")
                else None
            ),
            priority=params.get("priority", "medium"),
            created_by=ctx.user_id,
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        preview["id"] = str(task.id)
        preview["created_at"] = task.created_at.isoformat()

    return preview


async def _create_touchpoint_draft(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
    mode: str = "draft",
) -> dict[str, Any]:
    """Validate touchpoint creation params and return a preview dict."""
    errors: list[str] = []
    if not params.get("type"):
        errors.append("'type' is required (call, email, meeting, note, other)")
    if not params.get("summary"):
        errors.append("'summary' is required")

    preview = {
        "action": "create_touchpoint",
        "type": params.get("type"),
        "summary": params.get("summary"),
        "company_id": params.get("company_id"),
        "company_name": params.get("company_name"),
        "contact_id": params.get("contact_id"),
        "occurred_at": params.get("occurred_at"),
        "validated": len(errors) == 0,
    }

    if errors:
        preview["errors"] = errors
        return preview

    if mode == "execute":
        # 2026-09-09: company_name fallback（batch 鏈 — 公司啱啱由前一個 action 建好）
        company_id = params.get("company_id")
        if not company_id and (params.get("company_name") or params.get("company")):
            cid = await _resolve_company_id(ctx, db, params)
            if cid:
                company_id = cid
        touchpoint = Touchpoint(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            title=params["summary"],
            type=params["type"],
            description=params.get("summary"),
            company_id=UUID(company_id) if company_id else None,
            contact_id=UUID(params["contact_id"]) if params.get("contact_id") else None,
            date=(
                datetime.fromisoformat(params["occurred_at"])
                if params.get("occurred_at")
                else datetime.now(timezone.utc)
            ),
            created_by=ctx.user_id,
        )
        db.add(touchpoint)
        await db.flush()
        await db.refresh(touchpoint)
        preview["id"] = str(touchpoint.id)
        preview["created_at"] = touchpoint.created_at.isoformat()

    return preview


async def _create_company_draft(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
    mode: str = "draft",
) -> dict[str, Any]:
    """Validate company creation params and return a preview.

    2026-09-09: 新增 — 之前 TOOL_REGISTRY 冇 create_company_draft →
    AI 想建公司只能文字問 → confirm loop（Terrence bug report）。
    """
    errors: list[str] = []
    if not params.get("name"):
        errors.append("'name' is required")

    # 2026-09-09: duplicate detection — CRM 唔應該有同名公司。draft 顯示警告、
    # execute 直接 link 現有（唔建 duplicate）— 之前 AI 唔識 detect → Tontec
    # 建立咗兩個（7月 + 今日 18:59 duplicate bug）。
    existing_company = None
    try:
        existing_company = (
            await db.execute(
                select(Company).where(
                    Company.tenant_id == ctx.tenant_id,
                    func.lower(Company.name) == func.lower(params.get("name", "")),
                )
            )
        ).scalars().first()
    except Exception:
        existing_company = None

    preview = {
        "action": "create_company",
        "name": params.get("name"),
        "domain": params.get("domain"),
        "industry": params.get("industry"),
        "size": params.get("size"),
        "phone": params.get("phone"),
        "website": params.get("website"),
        "address": params.get("address"),
        "notes": params.get("notes"),
        "validated": len(errors) == 0,
    }
    if existing_company is not None:
        preview["duplicate_warning"] = (
            f"⚠️ 同名公司已存在（{existing_company.name}，id={existing_company.id}）"
            "— 唔會建立重複，會 link 去現有記錄"
        )
    if errors:
        preview["errors"] = errors
        return preview

    if mode == "execute":
        if existing_company is not None:
            # 唔建 duplicate — 返回現有公司 id
            preview["id"] = str(existing_company.id)
            preview["created_at"] = existing_company.created_at.isoformat()
            preview["duplicate_merged"] = True
            return preview
        company = Company(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            name=params["name"],
            domain=params.get("domain"),
            industry=params.get("industry"),
            size=params.get("size"),
            phone=params.get("phone"),
            website=params.get("website"),
            address=params.get("address"),
            notes=params.get("notes"),
            owner_id=ctx.user_id,
        )
        db.add(company)
        await db.flush()
        await db.refresh(company)
        preview["id"] = str(company.id)
        preview["created_at"] = company.created_at.isoformat()
    return preview


async def _resolve_company_id(ctx, db: AsyncSession, params: dict[str, Any]) -> str | None:
    """Resolve company from UUID or name (tenant-scoped). None if not found."""
    if params.get("company_id"):
        return str(params["company_id"])
    name = params.get("company_name") or params.get("company")
    if not name:
        return None
    row = (
        await db.execute(
            text("SELECT id FROM nexus_crm.companies WHERE tenant_id=:tid AND (name ILIKE :n OR domain ILIKE :n) ORDER BY created_at LIMIT 1"),
            {"tid": str(ctx.tenant_id), "n": f"%{name}%"},
        )
    ).first()
    return str(row[0]) if row else None


async def _create_contact_draft(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
    mode: str = "draft",
) -> dict[str, Any]:
    """Validate contact creation params and return a preview.

    2026-09-09: 新增 — 之前冇 create_contact_draft → AI 建聯絡人淨文字（同上 bug）。
    支援 company_id（UUID）或 company_name（自動 resolve — AI 通常傳名）。
    """
    errors: list[str] = []
    if not params.get("name") and not params.get("email"):
        errors.append("'name' (or 'email') is required")
    company_id = await _resolve_company_id(ctx, db, params)
    company_pending = False
    if (params.get("company_name") or params.get("company")) and not company_id:
        if mode == "execute":
            # Batch confirm: company action should have run first; if it still
            # can't be resolved the chain is broken — surface the error.
            errors.append(
                f"公司 '{params.get('company_name') or params.get('company')}' 未建立 — 請先用 create_company_draft 建立公司"
            )
        else:
            # Draft stage: company may be another pending draft in the same
            # batch (company → contact chain). Don't error — mark pending and
            # re-resolve at execute time.
            company_pending = True

    # 2026-09-09: merge-aware — CRM 已存在（email 或 name+email match）→ 唔好盲建
    # duplicate。draft 顯示警告；execute 時：params 有提供而現有 record 缺嘅
    # field 先補（update），完全冇新資料就 bypass（返回現有 id）。
    # Ada Wong ×2 / Ben Au ×2 duplicates 就係以前冇呢個邏輯累積嘅。
    existing_contact = None
    try:
        _q = None
        if params.get("email"):
            _q = select(Contact).where(
                Contact.tenant_id == ctx.tenant_id,
                func.lower(Contact.email) == func.lower(params["email"]),
            )
        elif params.get("name"):
            _q = select(Contact).where(
                Contact.tenant_id == ctx.tenant_id,
                func.lower(Contact.name) == func.lower(params["name"]),
            )
        if _q is not None:
            existing_contact = (
                await db.execute(_q)
            ).scalars().first()
    except Exception:
        existing_contact = None

    preview = {
        "action": "create_contact",
        "name": params.get("name"),
        "chinese_name": params.get("chinese_name"),
        "email": params.get("email"),
        "phone": params.get("phone"),
        "job_title": params.get("job_title"),
        "department": params.get("department"),
        "company_id": company_id,
        "company_name": params.get("company_name") or params.get("company"),
        "company_pending": company_pending,
        "notes": params.get("notes"),
        "validated": len(errors) == 0,
    }
    if existing_contact is not None:
        preview["duplicate_warning"] = (
            f"⚠️ 已存在同名/同 email 聯絡人（{existing_contact.name}）"
            "— 唔會建立重複；如有新資料會補入現有記錄"
        )
    if errors:
        preview["errors"] = errors
        return preview

    if mode == "execute":
        if existing_contact is not None:
            # merge: 有提供而現有缺嘅 field 先補
            merged_fields: list[str] = []
            for f, val in (
                ("phone", params.get("phone")),
                ("job_title", params.get("job_title")),
                ("department", params.get("department")),
                ("chinese_name", params.get("chinese_name")),
                ("notes", params.get("notes")),
            ):
                if val and not getattr(existing_contact, f):
                    setattr(existing_contact, f, val)
                    merged_fields.append(f)
            if company_id and not existing_contact.company_id:
                existing_contact.company_id = UUID(company_id)
                merged_fields.append("company_id")
            if merged_fields:
                await db.flush()  # onupdate 自動 refresh updated_at
                preview["id"] = str(existing_contact.id)
                preview["merged"] = True
                preview["merged_fields"] = merged_fields
                return preview
            # 完全冇新資料 → bypass（唔建 duplicate、唔改動）
            preview["id"] = str(existing_contact.id)
            preview["duplicate_merged"] = True
            preview["bypassed"] = True
            return preview
        # Re-resolve: the company may have been created by an earlier action
        # in this batch (execute mode re-runs resolve above — company_id fresh).
        contact = Contact(
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            company_id=UUID(company_id) if company_id else None,
            name=params.get("name"),
            chinese_name=params.get("chinese_name"),
            email=params.get("email"),
            phone=params.get("phone"),
            job_title=params.get("job_title"),
            department=params.get("department"),
            notes=params.get("notes"),
            owner_id=ctx.user_id,
        )
        db.add(contact)
        await db.flush()
        await db.refresh(contact)
        preview["id"] = str(contact.id)
        preview["created_at"] = contact.created_at.isoformat()
    return preview


async def _update_contact_draft(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
    mode: str = "draft",
) -> dict[str, Any]:
    """Validate contact update params and return a preview dict.

    In "draft" mode: validates params, looks up the contact, and shows
    what would be changed.
    In "execute" mode: performs the actual update.
    """
    errors: list[str] = []
    contact_id_str = params.get("contact_id")
    if not contact_id_str:
        errors.append("'contact_id' is required")

    contact = None
    if contact_id_str:
        try:
            contact_id = UUID(contact_id_str)
            result = await db.execute(
                select(Contact).where(
                    Contact.id == contact_id, Contact.tenant_id == ctx.tenant_id
                )
            )
            contact = result.scalar_one_or_none()
            if not contact:
                errors.append(f"Contact '{contact_id_str}' not found")
        except ValueError:
            # Fallback: AI sometimes passes the contact *name* or *email* instead
            # of a UUID. Resolve by exact match (tenant-scoped) so the draft
            # still works.
            q = contact_id_str.strip().lower()
            result = await db.execute(
                select(Contact)
                .where(
                    Contact.tenant_id == ctx.tenant_id,
                    or_(
                        func.lower(Contact.name) == q,
                        func.lower(Contact.email) == q,
                    ),
                )
                .limit(2)
            )
            matches = result.scalars().all()
            if len(matches) == 1:
                contact = matches[0]
                contact_id_str = str(contact.id)
            elif len(matches) > 1:
                errors.append(
                    f"Ambiguous contact '{contact_id_str}' — multiple matches, use contact_id UUID"
                )
            else:
                errors.append(f"Invalid contact_id format: {contact_id_str}")

    changes = {}
    # When called from the confirm endpoint, `params` IS the stored preview
    # dict ({"action", "contact_id", "current", "changes", ...}), not the
    # original AI params.  Reuse the preview's changes in that case.
    if isinstance(params.get("changes"), dict) and params.get("action") == "update_contact":
        changes = dict(params["changes"])
    else:
        for field in ("name", "email", "phone", "notes"):
            if field in params and params[field] is not None:
                changes[field] = params[field]

    preview = {
        "action": "update_contact",
        "contact_id": contact_id_str,
        "current": _row_to_dict(contact) if contact else None,
        "changes": changes,
        "validated": len(errors) == 0,
    }

    if errors:
        preview["errors"] = errors
        return preview

    if mode == "execute" and contact:
        for field, value in changes.items():
            setattr(contact, field, value)
        contact.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(contact)
        preview["result"] = _row_to_dict(contact)

    return preview


# ---------------------------------------------------------------------------
# Generic update-draft factory — powers update_company / update_project /
# update_task / update_namecard.  Same draft→confirm→execute contract as
# update_contact_draft: resolve target (UUID, or name/email fallback),
# preview changes, execute only with preview's authoritative changes.
# ---------------------------------------------------------------------------


def _make_update_handler(
    model: Any,
    id_param: str,
    action_name: str,
    editable_fields: tuple[str, ...],
    match_fields: tuple[str, ...] = ("name",),
) -> Callable[..., Coroutine[Any, Any, Any]]:
    # Column-type coercion map: JSON-ish params arrive as strings from the AI,
    # but DB columns are typed.  Coerce before setattr so flush() doesn't blow.
    from sqlalchemy import Boolean, Date, DateTime, Numeric

    def _coerce(field: str, value: Any) -> Any:
        col = model.__table__.columns.get(field)
        if col is None or not isinstance(value, str):
            return value
        t = col.type
        if isinstance(t, DateTime):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.fromisoformat(f"{value}T00:00:00+00:00")
        if isinstance(t, Date):
            return datetime.strptime(value, "%Y-%m-%d").date()
        if isinstance(t, Numeric):
            try:
                return float(value)
            except ValueError:
                return value
        if isinstance(t, Boolean):
            return value.strip().lower() in ("true", "1", "yes")
        return value

    async def handler(
        ctx: AISessionContext,
        params: dict[str, Any],
        db: AsyncSession,
        mode: str = "draft",
    ) -> dict[str, Any]:
        errors: list[str] = []
        id_str = params.get(id_param)
        obj = None
        if not id_str:
            errors.append(f"'{id_param}' is required")
        else:
            try:
                obj_id = UUID(id_str)
                result = await db.execute(
                    select(model).where(
                        model.id == obj_id, model.tenant_id == ctx.tenant_id
                    )
                )
                obj = result.scalar_one_or_none()
                if not obj:
                    errors.append(f"{model.__name__} '{id_str}' not found")
            except ValueError:
                # Fallback: AI sometimes passes a name/email instead of a UUID.
                q = id_str.strip().lower()
                if match_fields:
                    conds = [func.lower(getattr(model, f)) == q for f in match_fields]
                    result = await db.execute(
                        select(model)
                        .where(model.tenant_id == ctx.tenant_id, or_(*conds))
                        .limit(2)
                    )
                    matches = result.scalars().all()
                    if len(matches) == 1:
                        obj = matches[0]
                        id_str = str(obj.id)
                    elif len(matches) > 1:
                        errors.append(
                            f"Ambiguous {model.__name__} '{id_str}' — multiple matches, use {id_param} UUID"
                        )
                    else:
                        errors.append(f"Invalid {id_param} format: {id_str}")
                else:
                    errors.append(f"Invalid {id_param} format: {id_str}")

        changes: dict[str, Any] = {}
        # When called from the confirm endpoint, `params` IS the stored preview
        # dict — reuse its changes instead of re-deriving an empty dict.
        if isinstance(params.get("changes"), dict) and params.get("action") == action_name:
            changes = dict(params["changes"])
        else:
            for field in editable_fields:
                if field in params and params[field] is not None:
                    changes[field] = params[field]

        preview: dict[str, Any] = {
            "action": action_name,
            id_param: id_str,
            "current": _row_to_dict(obj) if obj else None,
            "changes": changes,
            "validated": len(errors) == 0,
        }
        if errors:
            preview["errors"] = errors
            return preview

        if mode == "execute" and obj:
            for field, value in changes.items():
                if field in editable_fields:
                    setattr(obj, field, _coerce(field, value))
            obj.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(obj)
            preview["result"] = _row_to_dict(obj)
        return preview

    return handler


_update_company_draft = _make_update_handler(
    Company,
    "company_id",
    "update_company",
    (
        "name", "domain", "industry", "size", "phone", "address", "website",
        "notes", "tags", "category", "ceo_name", "linkedin_url", "status",
    ),
)
_update_project_draft = _make_update_handler(
    Project,
    "project_id",
    "update_project",
    (
        "name", "project_code", "status", "priority", "description",
        "budget_amount", "start_date", "deadline",
    ),
)
_update_task_draft = _make_update_handler(
    Task,
    "task_id",
    "update_task",
    (
        "title", "description", "due_date", "priority", "status",
        "notes_html", "is_important", "reminder_at",
    ),
)
_update_namecard_draft = _make_update_handler(
    NameCard,
    "namecard_id",
    "update_namecard",
    ("status", "dedup_status"),
    match_fields=(),  # UUID only — name cards have no natural name column
)

# ═══════════════════════════════════════════════════════════
# 天氣 tool（2026-09-08 fix — Terrence: Telegram/CRM AI「未能連接天氣服務」）
# 同一 HKO source（briefing_sources.weather）— 令 tool-calling chat 路徑都有天氣
# ═══════════════════════════════════════════════════════════
def _hko_desc_short(icon: Any) -> tuple[str, str]:
    try:
        n = int(icon)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "天氣", "🌤️"
    if n <= 50:
        return "天晴", "☀️"
    if n == 51:
        return "短暫陽光", "🌤️"
    if n == 52:
        return "間中多雲", "🌥️"
    if 53 <= n <= 55:
        return "多雲", "☁️"
    if 60 <= n <= 65:
        return "微雨", "🌦️"
    if 70 <= n <= 73:
        return "下雨", "🌧️"
    if 74 <= n <= 79:
        return "大雨/雷暴", "⛈️"
    if 80 <= n <= 88:
        return "有霧", "🌫️"
    if n >= 91:
        return "大風", "💨"
    return "多雲", "☁️"


async def _get_hk_weather(ctx: Any, params: dict[str, Any], db: Any, mode: str | None = None) -> dict[str, Any]:
    """香港實時天氣（HKO Open Data rhrread — 同 briefing 同一 source）。"""
    try:
        from app.ai import briefing_sources as bs

        opts: dict[str, Any] = {}
        if params.get("region"):
            opts["region"] = [params["region"]]
        wl = await bs.weather(ctx, db, options=opts)
        if not wl or wl[0].get("temperature") is None:
            return {"error": "天氣資料暫時未能獲取（HKO 服務冇回應）"}
        w = wl[0]
        desc, emoji = _hko_desc_short(w.get("icon") or 0)
        result: dict[str, Any] = {
            "place": w.get("place", "香港"),
            "temperature": f"{w['temperature']}°C",
            "condition": f"{emoji} {desc}",
            "updated_at": w.get("updated_at", ""),
        }
        if w.get("humidity") is not None:
            result["humidity"] = f"{w['humidity']}%"
        if w.get("rainfall_mm") is not None:
            result["rainfall_mm"] = w["rainfall_mm"]
        return result
    except Exception as e:  # pragma: no cover — 外部服務失敗都要有嘢返
        return {"error": f"天氣資料未能獲取: {e}"}


# ---------------------------------------------------------------------------
# Memory READ handler — explicit, user-traceable long-term recall (Tier 3 path)
# ---------------------------------------------------------------------------
# 2026-09-10: memory is no longer ONLY silently injected (top-of-mind Tier 1/2).
# The model can now *choose* to call `search_memory` when it needs the user's
# longer-term context — every such call is logged by the read-agent loop with
# name/args/outcome, so memory use becomes transparent and auditable instead of
# an invisible prefix on every prompt. This is also the only path that reaches
# Tier 3 (archive / older rows): the silent injector never loads it.
#
# These two constants mirror app/routers/ai.py (duplicated deliberately to
# avoid a circular import: routers.ai imports this module).
_MEMORY_CONFIDENCE_FLOOR = 0.5   # = _MEMORY_MIN_CONFIDENCE
_MEMORY_FRESHNESS_DAYS = 30      # = _MEMORY_MAX_AGE_DAYS

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def memory_query_tokens(text: str) -> set[str]:
    """CJK + latin token set: latin words (≥2 chars) + CJK bigrams.

    Single CJK characters are deliberately EXCLUDED — with 1-char terms a
    common character like 日 (今日 vs 到期日) or 期 spuriously matches almost
    anything, which defeats relevance gating. Bigrams carry the real signal.
    """
    t = (text or "").lower()
    toks = set(re.findall(r"[a-z0-9]{2,}", t))
    cjk = _CJK_RE.findall(t)
    toks.update(a + b for a, b in zip(cjk, cjk[1:]))
    return toks


def memory_relevance_score(query: str, content: str) -> float:
    """0..1 keyword-overlap score between *query* and a memory line.

    Shared by the router's relevance gate and this tool so both agree on what
    "relevant to the current question" means.
    """
    q = memory_query_tokens(query)
    if not q:
        return 0.0
    c = memory_query_tokens(content)
    if not c:
        return 0.0
    return len(q & c) / float(len(q))


async def _search_memory(
    ctx: AISessionContext,
    params: dict[str, Any],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Recall the caller's own cross-session memory (READ-only, per-user).

    RLS (app.tenant_id) + an explicit user_id filter keep this strictly to the
    caller's own rows. Weak inferences (confidence below the floor) never
    surface, even here. ``include_archive=True`` drops the freshness gate so
    the model can reach Tier 3 archive rows on explicit request.
    """
    query = str(params.get("query") or "").strip()
    try:
        limit = int(params.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))
    category = params.get("category")
    include_archive = bool(params.get("include_archive", False))

    stmt = select(UserMemory).where(
        UserMemory.tenant_id == ctx.tenant_id,
        UserMemory.user_id == ctx.user_id,
    )
    if category:
        stmt = stmt.where(UserMemory.category == str(category))
    else:
        stmt = stmt.where(UserMemory.category != "daily")
    stmt = stmt.where(
        func.coalesce(UserMemory.confidence, 0.0) >= _MEMORY_CONFIDENCE_FLOOR
    )
    if not include_archive:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_MEMORY_FRESHNESS_DAYS)
        stmt = stmt.where(UserMemory.last_accessed >= cutoff)
    stmt = stmt.order_by(UserMemory.last_accessed.desc()).limit(100)

    rows = list((await db.execute(stmt)).scalars().all())

    if query:
        scored = [
            (memory_relevance_score(query, r.content), r) for r in rows
        ]
        scored = [(s, r) for s, r in scored if s > 0]
        scored.sort(key=lambda t: t[0], reverse=True)
        rows = [r for _, r in scored[:limit]]
    else:
        rows = rows[:limit]

    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for r in rows:
        # "summary" is picked up by the shared context-line renderer
        # (name/title/summary) so recalled memory renders as a clean bullet.
        out.append({
            "category": r.category,
            "summary": f"[{r.category}] {r.content}",
            "content": r.content,
            "source": r.source,
            "confidence": r.confidence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
        r.last_accessed = now
    return out


TOOL_REGISTRY: dict[str, ToolDef] = {
    # fmt: off
    # ---- 10 READ tools -----------------------------------------------------
    "get_hk_weather": ToolDef(
        key="get_hk_weather",
        type="read",
        module="app.services.crm.weather",
        input_schema={
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": ["hk_island", "kowloon", "nt_east", "nt_west", "all_hk"],
                    "description": "Optional region filter (default: all HK)",
                },
            },
        },
        handler=_get_hk_weather,
    ),
    "search_companies": ToolDef(
        key="search_companies",
        type="read",
        module="app.services.crm.companies",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for company name or domain"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_search_companies,
    ),
    "get_company_detail": ToolDef(
        key="get_company_detail",
        type="read",
        module="app.services.crm.companies",
        input_schema={
            "type": "object",
            "properties": {
                "company_id": {"type": "string", "format": "uuid", "description": "Company UUID"},
            },
            "required": ["company_id"],
        },
        handler=_get_company_detail,
    ),
    "search_contacts": ToolDef(
        key="search_contacts",
        type="read",
        module="app.services.crm.contacts",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for name (EN or Chinese), email or phone"},
                "company_id": {"type": "string", "format": "uuid", "description": "Optional company filter"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_search_contacts,
    ),
    "get_contact_detail": ToolDef(
        key="get_contact_detail",
        type="read",
        module="app.services.crm.contacts",
        input_schema={
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "format": "uuid", "description": "Contact UUID"},
            },
            "required": ["contact_id"],
        },
        handler=_get_contact_detail,
    ),
    "search_projects": ToolDef(
        key="search_projects",
        type="read",
        module="app.services.crm.projects",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for project name or code"},
                "status": {"type": "string", "description": "Filter by status"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_search_projects,
    ),
    "search_notes": ToolDef(
        key="search_notes",
        type="read",
        module="app.services.crm.notes",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for note title or content"},
                "limit": {"type": "integer", "default": 20},
                "contact_id": {"type": "string", "format": "uuid", "description": "Optional: notes related to this contact (attached FK or @mention link)"},
                "company_id": {"type": "string", "format": "uuid", "description": "Optional: notes related to this company (attached FK or @mention link)"},
                "project_id": {"type": "string", "format": "uuid", "description": "Optional: notes related to this project"},
                "task_id": {"type": "string", "format": "uuid", "description": "Optional: notes related to this task"},
            },
        },
        handler=_search_notes,
    ),
    "list_tasks": ToolDef(
        key="list_tasks",
        type="read",
        module="app.services.crm.tasks",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "format": "uuid", "description": "Optional project filter"},
                "assignee_id": {"type": "string", "format": "uuid", "description": "Optional assignee filter"},
                "status": {"type": "string", "description": "Filter by status"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        handler=_list_tasks,
    ),
    "list_touchpoints": ToolDef(
        key="list_touchpoints",
        type="read",
        module="app.services.crm.touchpoints",
        input_schema={
            "type": "object",
            "properties": {
                "company_id": {"type": "string", "format": "uuid", "description": "Optional company filter"},
                "contact_id": {"type": "string", "format": "uuid", "description": "Optional contact filter"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        handler=_list_touchpoints,
    ),
    "get_dashboard_summary": ToolDef(
        key="get_dashboard_summary",
        type="read",
        module="app.services.crm.dashboard",
        input_schema={
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["7d", "30d", "90d"], "default": "30d"},
            },
        },
        handler=_get_dashboard_summary,
    ),
    "search_deals": ToolDef(
        key="search_deals",
        type="read",
        module="app.services.crm.deals",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for deal name or description"},
                "stage": {"type": "string", "description": "Filter by pipeline stage"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_search_deals,
    ),
    "get_upcoming_events": ToolDef(
        key="get_upcoming_events",
        type="read",
        module="app.services.crm.events",
        input_schema={
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "default": 30, "description": "How many days to look ahead"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_get_upcoming_events,
    ),
    # ---- Memory recall (READ) — explicit, user-traceable Tier 3 access -------
    "search_memory": ToolDef(
        key="search_memory",
        type="read",
        # module MUST stay under app.services.crm.* — the permission guard
        # rejects any other prefix (system_module_out_of_bounds).
        module="app.services.crm.memory",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to recall about the user — their preferences, known facts or prior context. Keywords matching the user's message work best."},
                "category": {"type": "string", "description": "Optional category filter: preference / fact / interest / contact_pref / project_pref / workflow"},
                "limit": {"type": "integer", "default": 5, "description": "Max memory rows to return (1-20)"},
                "include_archive": {"type": "boolean", "default": False, "description": "Also include older (Tier 3 archive) memories not normally surfaced"},
            },
        },
        handler=_search_memory,
    ),
    # ---- 3 WRITE tools (all require confirmation) --------------------------
    "create_company_draft": ToolDef(
        key="create_company_draft",
        type="write",
        module="app.services.crm.companies",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Company name (required)"},
                "domain": {"type": "string", "description": "Company domain e.g. tontec.com"},
                "industry": {"type": "string", "description": "Industry"},
                "size": {"type": "string", "description": "1-10 / 11-50 / 51-200 / 201-1000 / 1000+"},
                "phone": {"type": "string"},
                "website": {"type": "string"},
                "address": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name"],
        },
        handler=_create_company_draft,
    ),
    "create_contact_draft": ToolDef(
        key="create_contact_draft",
        type="write",
        module="app.services.crm.contacts",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact full name"},
                "chinese_name": {"type": "string"},
                "email": {"type": "string", "format": "email"},
                "phone": {"type": "string", "description": "Mobile phone"},
                "job_title": {"type": "string"},
                "department": {"type": "string"},
                "company_id": {"type": "string", "format": "uuid", "description": "Company UUID (or use company_name)"},
                "company_name": {"type": "string", "description": "Company name — auto-resolved to UUID (must exist first)"},
                "notes": {"type": "string"},
            },
            "required": ["name"],
        },
        handler=_create_contact_draft,
    ),
    "create_task_draft": ToolDef(
        key="create_task_draft",
        type="write",
        module="app.services.crm.tasks",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "assignee_id": {"type": "string", "format": "uuid", "description": "Assignee user UUID"},
                "due_date": {"type": "string", "format": "date", "description": "Due date YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            },
            "required": ["title"],
        },
        handler=_create_task_draft,
    ),
    "create_touchpoint_draft": ToolDef(
        key="create_touchpoint_draft",
        type="write",
        module="app.services.crm.touchpoints",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "company_id": {"type": "string", "format": "uuid", "description": "Company UUID"},
                "contact_id": {"type": "string", "format": "uuid", "description": "Contact UUID"},
                "type": {"type": "string", "enum": ["call", "email", "meeting", "note", "other"]},
                "summary": {"type": "string", "description": "Touchpoint summary"},
                "occurred_at": {"type": "string", "format": "date-time", "description": "ISO 8601 timestamp"},
            },
            "required": ["type", "summary"],
        },
        handler=_create_touchpoint_draft,
    ),
    "update_contact_draft": ToolDef(
        key="update_contact_draft",
        type="write",
        module="app.services.crm.contacts",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "format": "uuid", "description": "Contact UUID"},
                "name": {"type": "string", "description": "Updated name"},
                "email": {"type": "string", "format": "email", "description": "Updated email"},
                "phone": {"type": "string", "description": "Updated phone number"},
                "notes": {"type": "string", "description": "Additional notes"},
            },
            "required": ["contact_id"],
        },
        handler=_update_contact_draft,
    ),
    "update_company_draft": ToolDef(
        key="update_company_draft",
        type="write",
        module="app.services.crm.companies",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "company_id": {"type": "string", "format": "uuid", "description": "Company UUID"},
                "name": {"type": "string", "description": "Updated company name"},
                "domain": {"type": "string", "description": "Company domain"},
                "industry": {"type": "string", "description": "Industry"},
                "size": {"type": "string", "description": "Company size"},
                "phone": {"type": "string", "description": "Phone"},
                "address": {"type": "string", "description": "Address"},
                "website": {"type": "string", "description": "Website URL"},
                "notes": {"type": "string", "description": "Notes"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "ceo_name": {"type": "string", "description": "CEO name"},
                "linkedin_url": {"type": "string", "description": "LinkedIn URL"},
                "status": {"type": "string", "description": "Status"},
            },
            "required": ["company_id"],
        },
        handler=_update_company_draft,
    ),
    "update_project_draft": ToolDef(
        key="update_project_draft",
        type="write",
        module="app.services.crm.projects",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "format": "uuid", "description": "Project UUID"},
                "name": {"type": "string", "description": "Updated project name"},
                "project_code": {"type": "string", "description": "Project code"},
                "status": {"type": "string", "description": "Status"},
                "priority": {"type": "string", "description": "Priority"},
                "description": {"type": "string", "description": "Description"},
                "budget_amount": {"type": "number", "description": "Budget amount"},
                "start_date": {"type": "string", "format": "date", "description": "Start date YYYY-MM-DD"},
                "deadline": {"type": "string", "format": "date", "description": "Deadline YYYY-MM-DD"},
            },
            "required": ["project_id"],
        },
        handler=_update_project_draft,
    ),
    "update_task_draft": ToolDef(
        key="update_task_draft",
        type="write",
        module="app.services.crm.tasks",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "format": "uuid", "description": "Task UUID"},
                "title": {"type": "string", "description": "Updated title"},
                "description": {"type": "string", "description": "Updated description"},
                "due_date": {"type": "string", "format": "date", "description": "Due date YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "status": {"type": "string", "description": "Status"},
                "notes_html": {"type": "string", "description": "Rich-text notes"},
                "is_important": {"type": "boolean", "description": "Important flag"},
                "reminder_at": {"type": "string", "format": "date-time", "description": "Reminder timestamp"},
            },
            "required": ["task_id"],
        },
        handler=_update_task_draft,
    ),
    "update_namecard_draft": ToolDef(
        key="update_namecard_draft",
        type="write",
        module="app.services.crm.namecards",
        requires_confirmation=True,
        input_schema={
            "type": "object",
            "properties": {
                "namecard_id": {"type": "string", "format": "uuid", "description": "NameCard UUID"},
                "status": {"type": "string", "description": "Status"},
                "dedup_status": {"type": "string", "description": "Dedup status"},
            },
            "required": ["namecard_id"],
        },
        handler=_update_namecard_draft,
    ),
    # fmt: on
}

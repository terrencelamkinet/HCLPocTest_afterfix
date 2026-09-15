"""
Penguin CRM — MS To Do clone router.

Prefix: /api/v1/crm/todo
Covers: task lists (smart + user), tasks with steps/categories/attachments,
list sharing, My Day, and computed smart list endpoints.
"""

from uuid import UUID
from datetime import datetime, timezone, date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import func, select, or_, and_, update, delete, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import aiofiles
import aiofiles.os
import os
import re as _re
import uuid as _uuid

from app.db import get_tenant_session
from app.models.crm import (
    Task,
    TaskList,
    TaskStep,
    TaskCategory,
    TaskCategoryMap,
    TaskAttachment,
    ListShare,
)
from app.models import User, TenantMember
from app.schemas.crm import (
    ListResponse,
    TaskListCreate,
    TaskListUpdate,
    TaskListResponse,
    TaskCreateTodo,
    TaskUpdateTodo,
    TaskResponseTodo,
    TaskStepCreate,
    TaskStepUpdate,
    TaskStepReorder,
    TaskStepResponse,
    TaskCategoryCreate,
    TaskCategoryResponse,
    TaskCategoryMapCreate,
    TaskAttachmentResponse,
    ListShareCreate,
    ListShareResponse,
)

router = APIRouter(prefix="/api/v1/crm/todo", tags=["todo"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "tasks")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_tenant_id(request: Request) -> UUID:
    if getattr(request.state, "auth_status", "") == "expired":
        raise HTTPException(status_code=401, detail="Token expired")
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(status_code=403, detail="Tenant not identified")
    return tid


def _get_user_id(request: Request) -> UUID | None:
    return getattr(request.state, "user_id", None)


async def _get_smart_list_id(db: AsyncSession, tenant_id: UUID, name: str) -> UUID | None:
    """Return the ID of a smart list by name for the given tenant."""
    result = await db.execute(
        select(TaskList.id).where(
            TaskList.tenant_id == tenant_id,
            TaskList.is_smart == True,
            TaskList.name == name,
        )
    )
    return result.scalar_one_or_none()


async def _enrich_task(task: Task) -> dict[str, Any]:
    """Convert ORM task to dict with steps/categories/attachments."""
    d = {col.name: getattr(task, col.name) for col in task.__table__.columns}
    d["steps"] = [
        {col.name: getattr(s, col.name) for col in s.__table__.columns}
        for s in (getattr(task, "steps", None) or [])
    ]
    d["categories"] = [
        {col.name: getattr(c, col.name) for col in c.__table__.columns}
        for c in (getattr(task, "categories", None) or [])
    ]
    d["attachments"] = [
        {col.name: getattr(a, col.name) for col in a.__table__.columns}
        for a in (getattr(task, "attachments", None) or [])
    ]
    return d


# ===========================================================================
# LISTS
# ===========================================================================


@router.get("/lists", response_model=ListResponse[TaskListResponse])
async def list_lists(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List task lists for tenant (smart lists first, then user lists)."""
    tenant_id = _get_tenant_id(request)

    q = (
        select(TaskList)
        .where(TaskList.tenant_id == tenant_id)
        .order_by(TaskList.is_smart.desc(), TaskList.sort_order.asc(), TaskList.name.asc())
    )
    rows = (await db.execute(q)).scalars().all()
    return ListResponse(items=list(rows), total=len(rows))


@router.post("/lists", response_model=TaskListResponse, status_code=201)
async def create_list(
    request: Request,
    body: TaskListCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a user list."""
    tenant_id = _get_tenant_id(request)
    lst = TaskList(tenant_id=tenant_id, **body.model_dump())
    db.add(lst)
    await db.flush()
    await db.refresh(lst)
    return lst


@router.patch("/lists/{list_id}", response_model=TaskListResponse)
async def update_list(
    request: Request,
    list_id: UUID,
    body: TaskListUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Update a list (name, color, icon, sort_order)."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskList).where(TaskList.id == list_id, TaskList.tenant_id == tenant_id)
    )
    lst = result.scalar_one_or_none()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(lst, field, value)
    lst.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(lst)
    return lst


@router.delete("/lists/{list_id}", status_code=204)
async def delete_list(
    request: Request,
    list_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a user list (smart lists cannot be deleted)."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskList).where(TaskList.id == list_id, TaskList.tenant_id == tenant_id)
    )
    lst = result.scalar_one_or_none()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    if lst.is_smart:
        raise HTTPException(status_code=400, detail="Cannot delete a smart list")

    # Unlink tasks that belong to this list
    await db.execute(
        update(Task).where(Task.list_id == list_id, Task.tenant_id == tenant_id).values(list_id=None)
    )
    await db.delete(lst)
    return None


@router.post("/lists/{list_id}/share", response_model=ListShareResponse, status_code=201)
async def share_list(
    request: Request,
    list_id: UUID,
    body: ListShareCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Share a list with another user."""
    tenant_id = _get_tenant_id(request)
    # Verify list exists
    result = await db.execute(
        select(TaskList).where(TaskList.id == list_id, TaskList.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="List not found")

    share = ListShare(list_id=list_id, user_id=body.user_id, permission=body.permission)
    db.add(share)
    await db.flush()
    await db.refresh(share)
    return share


@router.delete("/lists/{list_id}/unshare/{user_id}", status_code=204)
async def unshare_list(
    request: Request,
    list_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Remove a user's share access to a list."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskList).where(TaskList.id == list_id, TaskList.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="List not found")

    await db.execute(
        delete(ListShare).where(
            ListShare.list_id == list_id, ListShare.user_id == user_id
        )
    )
    return None


# ===========================================================================
# TASKS
# ===========================================================================


@router.get("/tasks", response_model=ListResponse[dict[str, Any]])
async def list_tasks(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    list_id: UUID | None = None,
    smart: str | None = None,
    contact_id: UUID | None = None,
    company_id: UUID | None = None,
    deal_id: UUID | None = None,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List tasks with filters. Compatible with MS To Do smart views."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    base = select(Task).where(Task.tenant_id == tenant_id)

    # Smart list filter
    if smart == "myday":
        base = base.where(Task.my_day_date == date.today(), Task.status != "done")
    elif smart == "important":
        base = base.where(Task.is_important == True, Task.status != "done")
    elif smart == "planned":
        base = base.where(Task.due_date.isnot(None), Task.status != "done")
    elif smart == "all":
        pass  # 'all' shows every task (MS To Do "Tasks" behaviour) — completed sink to bottom, so ticked tasks stay visible as done
    elif smart == "completed":
        base = base.where(Task.status == "done")
    elif smart == "assigned":
        if user_id:
            base = base.where(Task.assignee_id == user_id, Task.status != "done")
    elif smart == "due_today":
        base = base.where(Task.due_date == date.today(), Task.status != "done")

    if list_id:
        base = base.where(Task.list_id == list_id)
    if contact_id:
        base = base.where(Task.contact_id == contact_id)
    if company_id:
        base = base.where(Task.company_id == company_id)
    if deal_id:
        base = base.where(Task.deal_id == deal_id)
    if status:
        base = base.where(Task.status == status)
    if priority:
        base = base.where(Task.priority == priority)
    if search:
        base = base.where(Task.title.ilike(f"%{search}%"))

    # Count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch with eager loads
    items_q = (
        base.options(
            selectinload(Task.steps),
            selectinload(Task.categories),
            selectinload(Task.attachments),
        )
        .order_by(
            *((case((Task.status == "done", 1), else_=0), Task.created_at.desc())
              if smart == "all" else (Task.created_at.desc(),))
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(items_q)).scalars().all()

    items = [await _enrich_task(t) for t in rows]
    return ListResponse(items=items, total=total)


@router.post("/tasks", response_model=TaskResponseTodo, status_code=201)
async def create_task(
    request: Request,
    body: TaskCreateTodo,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a task. Defaults list_id to the 'All' smart list if not specified."""
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)
    workspace_id = getattr(request.state, "workspace_id", None)

    data = body.model_dump()
    if not data.get("list_id"):
        all_list_id = await _get_smart_list_id(db, tenant_id, "All")
        if all_list_id:
            data["list_id"] = all_list_id

    task = Task(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=user_id,
        **{k: v for k, v in data.items() if hasattr(Task, k)},
    )
    db.add(task)
    await db.flush()
    # SPEC notifications-revamp T3: 任務指派俾人（creator ≠ assignee）→ 通知 assignee
    try:
        if task.assignee_id and str(task.assignee_id) != str(user_id):
            from app.services.notification_writer import notify_event
            _due_txt = f"到期：{task.due_date}" if getattr(task, "due_date", None) else "無限期"
            await notify_event(
                db, tenant_id, task.assignee_id,
                source_module="business",
                source_record_type="task",
                source_record_id=task.id,
                title=f"新任務指派：{str(task.title)[:80]}",
                body=_due_txt,
                group_key=f"task_assign:{task.id}",
            )
    except Exception:
        pass
    await db.refresh(task)
    # Reload with relationships
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.steps),
            selectinload(Task.categories),
            selectinload(Task.attachments),
        )
        .where(Task.id == task.id)
    )
    task = result.scalar_one()
    return await _enrich_task(task)


@router.get("/tasks/{task_id}", response_model=dict[str, Any])
async def get_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get task with steps, categories, and attachments."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.steps),
            selectinload(Task.categories),
            selectinload(Task.attachments),
        )
        .where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return await _enrich_task(task)


@router.patch("/tasks/{task_id}", response_model=dict[str, Any])
async def update_task(
    request: Request,
    task_id: UUID,
    body: TaskUpdateTodo,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Update a task (all MS To Do fields supported)."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    # If marking as done, set completed_at
    if body.status == "done" and not task.completed_at:
        task.completed_at = datetime.now(timezone.utc)
    elif body.status and body.status != "done" and task.completed_at:
        task.completed_at = None

    task.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Reload with relationships
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.steps),
            selectinload(Task.categories),
            selectinload(Task.attachments),
        )
        .where(Task.id == task.id)
    )
    task = result.scalar_one()
    return await _enrich_task(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a task."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    return None


@router.get("/users/{user_id}")
async def get_tenant_user(
    request: Request,
    user_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Return one tenant user by id (for EntitySearch label fetch). Tenant-scoped."""
    tenant_id = _get_tenant_id(request)
    row = (
        await db.execute(
            select(User)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(TenantMember.tenant_id == tenant_id, User.id == user_id)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(row.id),
        "email": row.email,
        "display_name": row.display_name or "",
        "name": row.display_name or row.email,
    }


@router.get("/users")
async def list_tenant_users(
    request: Request,
    search: str = "",
    db: AsyncSession = Depends(get_tenant_session),
):
    """List users that belong to the current tenant (for assignee search).

    Strict tenant isolation: joins TenantMember on the caller's tenant_id,
    never exposing users from other tenants.
    """
    tenant_id = _get_tenant_id(request)
    pattern = f"%{search}%"
    q = (
        select(User)
        .join(TenantMember, TenantMember.user_id == User.id)
        .where(TenantMember.tenant_id == tenant_id)
        .order_by(User.email)
    )
    if search:
        q = q.where(
            or_(
                User.email.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )
    rows = (await db.execute(q.limit(20))).scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name or "",
        }
        for u in rows
    ]


# ===========================================================================
# STEPS
# ===========================================================================


@router.post("/tasks/{task_id}/steps", response_model=TaskStepResponse, status_code=201)
async def create_step(
    request: Request,
    task_id: UUID,
    body: TaskStepCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a step on a task."""
    tenant_id = _get_tenant_id(request)
    # Verify task exists
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    # Get max sort_order
    max_order = (
        await db.execute(
            select(func.coalesce(func.max(TaskStep.sort_order), -1)).where(
                TaskStep.task_id == task_id
            )
        )
    ).scalar() or -1

    step = TaskStep(task_id=task_id, title=body.title, sort_order=max_order + 1)
    db.add(step)
    await db.flush()
    await db.refresh(step)
    return step


@router.patch("/tasks/{task_id}/steps/{step_id}", response_model=TaskStepResponse)
async def update_step(
    request: Request,
    task_id: UUID,
    step_id: UUID,
    body: TaskStepUpdate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Update a step (title, is_completed)."""
    tenant_id = _get_tenant_id(request)
    # Verify task exists
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(TaskStep).where(TaskStep.id == step_id, TaskStep.task_id == task_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(step, field, value)
    await db.flush()
    await db.refresh(step)
    return step


@router.delete("/tasks/{task_id}/steps/{step_id}", status_code=204)
async def delete_step(
    request: Request,
    task_id: UUID,
    step_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a step."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(TaskStep).where(TaskStep.id == step_id, TaskStep.task_id == task_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    await db.delete(step)
    return None


@router.patch("/tasks/{task_id}/steps/reorder", response_model=list[TaskStepResponse])
async def reorder_steps(
    request: Request,
    task_id: UUID,
    body: TaskStepReorder,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Reorder steps by providing an ordered array of step IDs."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(TaskStep).where(TaskStep.task_id == task_id)
    )
    steps = result.scalars().all()
    step_map = {str(s.id): s for s in steps}

    for idx, sid in enumerate(body.step_ids):
        step = step_map.get(str(sid))
        if step:
            step.sort_order = idx

    await db.flush()

    # Return re-ordered steps
    result = await db.execute(
        select(TaskStep)
        .where(TaskStep.task_id == task_id)
        .order_by(TaskStep.sort_order.asc())
    )
    return list(result.scalars().all())


# ===========================================================================
# CATEGORIES
# ===========================================================================


@router.get("/categories")
async def list_categories(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List all task categories for the tenant."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskCategory)
        .where(TaskCategory.tenant_id == tenant_id)
        .order_by(TaskCategory.name)
    )
    rows = result.scalars().all()
    return {
        "items": [
            {"id": str(c.id), "name": c.name, "color": c.color}
            for c in rows
        ],
        "total": len(rows),
    }


@router.post("/tasks/{task_id}/categories", status_code=201)
async def add_task_category(
    request: Request,
    task_id: UUID,
    body: TaskCategoryMapCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Add a category to a task."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify category exists
    result = await db.execute(
        select(TaskCategory.id).where(TaskCategory.id == body.category_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Category not found")

    # Check if already mapped
    existing = await db.execute(
        select(TaskCategoryMap).where(
            TaskCategoryMap.task_id == task_id,
            TaskCategoryMap.category_id == body.category_id,
        )
    )
    if not existing.scalar_one_or_none():
        db.add(TaskCategoryMap(task_id=task_id, category_id=body.category_id))
        await db.flush()

    return {"status": "ok"}


@router.delete("/tasks/{task_id}/categories/{category_id}", status_code=204)
async def remove_task_category(
    request: Request,
    task_id: UUID,
    category_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Remove a category from a task."""
    await db.execute(
        delete(TaskCategoryMap).where(
            TaskCategoryMap.task_id == task_id,
            TaskCategoryMap.category_id == category_id,
        )
    )
    return None


def _safe_upload_name(name: str | None) -> str:
    """2026-09-15 SAST（AppScan：path traversal / arbitrary file write）。

    之前 `os.path.join(dir, file.filename)` 直接用 client 提供嘅檔名 →
    filename 帶 `../../` 就可以寫出 uploads 目錄（例如覆蓋 .env / systemd unit）。
    呢度只取 basename、只准 [A-Za-z0-9._-]、prepend 隨機 hex，保證寫唔出目錄。
    """
    base = os.path.basename((name or "").replace("\\", "/"))
    base = _re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")[-80:]
    if not base:
        base = "file"
    return f"{_uuid.uuid4().hex[:8]}_{base}"


# ===========================================================================
# ATTACHMENTS
# ===========================================================================


@router.post("/tasks/{task_id}/attachments", response_model=TaskAttachmentResponse, status_code=201)
async def upload_attachment(
    request: Request,
    task_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Upload a file attachment to a task."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task.id).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    # Ensure upload dir
    task_upload_dir = os.path.join(UPLOAD_DIR, str(task_id))
    await aiofiles.os.makedirs(task_upload_dir, exist_ok=True)

    # Save file
    # 2026-09-15 SAST：唔可以用 client 檔名砌 path（`../` 可寫出 uploads 目錄）。
    content = await file.read()
    safe_name = _safe_upload_name(file.filename)
    file_path = os.path.join(task_upload_dir, safe_name)
    if not os.path.realpath(file_path).startswith(os.path.realpath(task_upload_dir) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename")
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    attachment = TaskAttachment(
        task_id=task_id,
        filename=file.filename,
        file_size=len(content),
        content_type=file.content_type,
        storage_path=file_path,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)
    return attachment


@router.get("/tasks/{task_id}/attachments/{attachment_id}")
async def download_attachment(
    request: Request,
    task_id: UUID,
    attachment_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Download a file attachment."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskAttachment).where(
            TaskAttachment.id == attachment_id,
            TaskAttachment.task_id == task_id,
        )
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if not att.storage_path or not await aiofiles.os.path.isfile(att.storage_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(att.storage_path, media_type=att.content_type, filename=att.filename)


@router.delete("/tasks/{task_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    request: Request,
    task_id: UUID,
    attachment_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Delete a file attachment."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TaskAttachment).where(
            TaskAttachment.id == attachment_id,
            TaskAttachment.task_id == task_id,
        )
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Delete file from disk
    if att.storage_path and await aiofiles.os.path.isfile(att.storage_path):
        await aiofiles.os.remove(att.storage_path)

    await db.delete(att)
    return None


# ===========================================================================
# MY DAY
# ===========================================================================


@router.get("/my-day/toggle/{task_id}")
async def toggle_my_day(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Toggle a task in/out of My Day."""
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    today = date.today()
    if task.my_day_date == today:
        task.my_day_date = None
    else:
        task.my_day_date = today

    task.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"my_day_date": task.my_day_date.isoformat() if task.my_day_date else None}


@router.post("/my-day/add-all-due-today")
async def add_all_due_today_to_my_day(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Add all due-today tasks to My Day."""
    tenant_id = _get_tenant_id(request)
    today = date.today()

    result = await db.execute(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.due_date == today,
            Task.status != "done",
            Task.my_day_date.is_(None),
        )
    )
    tasks = result.scalars().all()
    for t in tasks:
        t.my_day_date = today
        t.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return {"added": len(tasks)}


@router.post("/my-day/clear")
async def clear_my_day(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Clear all My Day tasks."""
    tenant_id = _get_tenant_id(request)
    today = date.today()

    result = await db.execute(
        select(Task).where(
            Task.tenant_id == tenant_id,
            Task.my_day_date == today,
        )
    )
    tasks = result.scalars().all()
    for t in tasks:
        t.my_day_date = None
        t.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return {"cleared": len(tasks)}


# ===========================================================================
# SMART LISTS
# ===========================================================================


@router.get("/smart/{smart_type}", response_model=ListResponse[dict[str, Any]])
async def list_smart_list(
    request: Request,
    smart_type: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Return a computed smart list.

    Types: important, planned, completed, assigned, due_today, all
    """
    tenant_id = _get_tenant_id(request)
    user_id = _get_user_id(request)

    base = select(Task).where(Task.tenant_id == tenant_id)

    if smart_type == "important":
        base = base.where(Task.is_important == True, Task.status != "done")
    elif smart_type == "planned":
        base = base.where(Task.due_date.isnot(None), Task.status != "done")
    elif smart_type == "completed":
        base = base.where(Task.status == "done")
    elif smart_type == "assigned":
        if user_id:
            base = base.where(Task.assignee_id == user_id, Task.status != "done")
    elif smart_type == "due_today":
        base = base.where(Task.due_date == date.today(), Task.status != "done")
    elif smart_type == "all":
        base = base.where(Task.status != "done")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown smart type: {smart_type}")

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items_q = (
        base.options(
            selectinload(Task.steps),
            selectinload(Task.categories),
            selectinload(Task.attachments),
        )
        .order_by(Task.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(items_q)).scalars().all()

    items = [await _enrich_task(t) for t in rows]
    return ListResponse(items=items, total=total)

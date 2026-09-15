from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from uuid import UUID
from datetime import datetime, date
from typing import Generic, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic paginated response
# ---------------------------------------------------------------------------

class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int


# ===========================================================================
# Company
# ===========================================================================

class CompanyCreate(BaseModel):
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    ceo_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[UUID] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    ceo_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[UUID] = None


class CompanyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    domain: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    ceo_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    # SPEC detail-v3: company KPI counts（backend subquery 填）
    active_projects_count: Optional[int] = None
    contacts_count: Optional[int] = None
    overdue_tasks_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# Contact
# ===========================================================================

class ContactCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company_id: Optional[UUID] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    linkedin_url: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    avatar_url: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    chinese_name: Optional[str] = None
    nick_name: Optional[str] = None
    contact_type: Optional[str] = None
    grade: Optional[str] = None
    numbers: list[str] = []
    office_phone: Optional[str] = None
    namecard_path: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[UUID] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company_id: Optional[UUID] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    linkedin_url: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    avatar_url: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    chinese_name: Optional[str] = None
    nick_name: Optional[str] = None
    contact_type: Optional[str] = None
    grade: Optional[str] = None
    numbers: Optional[list[str]] = None
    office_phone: Optional[str] = None
    namecard_path: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[UUID] = None


class ContactResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company_id: Optional[UUID] = None
    company: Any = None
    job_title: Optional[str] = None
    chinese_name: Optional[str] = None
    nick_name: Optional[str] = None
    contact_type: Optional[str] = None
    grade: Optional[str] = None
    numbers: Optional[list[str]] = None
    office_phone: Optional[str] = None
    namecard_path: Optional[str] = None
    department: Optional[str] = None
    linkedin_url: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    avatar_url: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    status: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    # SPEC detail-v3: KPI counts（backend subquery 填）
    open_tasks_count: Optional[int] = None
    touchpoints_count: Optional[int] = None
    projects_count: Optional[int] = None
    next_follow_up: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Touchpoint
# ===========================================================================

class TouchpointCreate(BaseModel):
    type: str
    title: str
    description: Optional[str] = None
    date: Optional[datetime] = None  # will be set server-side if omitted
    contact_ids: list[UUID] = []
    participants: Optional[list[UUID]] = None  # alias for contact_ids (UI 2026-09-09)
    company_id: Optional[UUID] = None
    companies: Optional[list[UUID]] = None  # multi-company (011): 全列；company_id = 第一個（主要）
    duration_minutes: Optional[int] = None


class TouchpointUpdate(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[datetime] = None
    contact_ids: Optional[list[UUID]] = None
    participants: Optional[list[UUID]] = None  # alias for contact_ids (UI 2026-09-09)
    company_id: Optional[UUID] = None
    companies: Optional[list[UUID]] = None  # multi-company (011): 全列；company_id = 第一個（主要）
    duration_minutes: Optional[int] = None


class TouchpointResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    type: str
    title: str
    description: Optional[str] = None
    date: datetime
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    company: Any = None
    participants: list[dict] = []
    companies: list[dict] = []  # multi-company (011)
    duration_minutes: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# Task
# ===========================================================================

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: str = "medium"
    status: str = "pending"
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    recurring: Optional[bool] = None
    area: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    recurring: Optional[bool] = None
    area: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None


class TaskResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    recurring: Optional[bool] = None
    area: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
    company: Any = None
    contact: Any = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# NameCard
# ===========================================================================

class NameCardCreate(BaseModel):
    image_url: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None
    status: str = "pending"
    contact_id: Optional[UUID] = None


class NameCardUpdate(BaseModel):
    image_url: Optional[str] = None
    original_image_url: Optional[str] = None
    cropped_image_url: Optional[str] = None
    display_image: Optional[str] = None  # 'original' | 'cropped'
    raw_ocr_text: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None
    status: Optional[str] = None
    contact_id: Optional[UUID] = None


class NameCardResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    image_url: Optional[str] = None
    original_image_url: Optional[str] = None
    cropped_image_url: Optional[str] = None
    display_image: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None
    review_candidates: Optional[list[dict[str, Any]]] = None
    tags: Optional[list[str]] = None  # V2: label list
    field_confidence: Optional[dict[str, Any]] = None  # V2: per-field confidence 0..1
    duplicate_candidate: Optional[dict[str, Any]] = None  # V2: { contact_id, reason }
    status: Optional[str] = None
    contact_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NameCardResolveRequest(BaseModel):
    action: str  # 'overwrite' | 'keep_both'
    contact_id: Optional[UUID] = None  # required for overwrite (existing contact)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# Note
# ===========================================================================

class NoteCreate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    pinned: bool = False
    tags: list[str] = []
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    # Notes v2 (T1.3) — home notebook. None = 未分類 (uncategorised).
    notebook_id: Optional[UUID] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    pinned: Optional[bool] = None
    tags: Optional[list[str]] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    # Notes v2 (T1.3) — move a note between notebooks / back to 未分類.
    notebook_id: Optional[UUID] = None
    # Notes v2 Stage C (T-02) — 樂觀鎖。帶住你手上嗰個 version，如果 DB 已經係第二個
    # version（即另一個 tab／裝置改過）→ 409 Conflict，唔會靜默覆蓋。
    expected_version: Optional[int] = None


class NoteTagRef(BaseModel):
    """Notes V2 (T2.1) — tag attached to a note (id/name/color for chips)."""
    id: UUID
    name: str
    color: Optional[str] = None


class NoteTagAttach(BaseModel):
    """Attach payload: reuse an existing tag by id, or by name (find-or-create)."""
    tag_id: Optional[UUID] = None
    name: Optional[str] = None
    color: Optional[str] = None


class NoteLinkRef(BaseModel):
    """Notes V2 (T3.1) — record linked to a note (@mention / +Link record)."""
    id: UUID
    entity_type: str
    entity_id: Optional[UUID] = None
    label: Optional[str] = None
    url: Optional[str] = None


class NoteLinkCreate(BaseModel):
    """Create/upsert a note link (idempotent per note+type+id)."""
    entity_type: str
    entity_id: Optional[UUID] = None
    label: Optional[str] = None


class NoteResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: Optional[str] = None
    content: Optional[str] = None
    pinned: bool = False
    tags: Optional[list[str]] = None
    note_tags: Optional[list[NoteTagRef]] = None
    note_links: Optional[list[NoteLinkRef]] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    notebook_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    company: Any = None
    created_at: datetime
    updated_at: datetime
    # Notes v2 Stage C — 前端要用 version 做樂觀鎖（PATCH 回傳新 version）
    version: int = 1
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# ===========================================================================


# ===========================================================================
# ActivityLog  (CREATE only — no Update)
# ===========================================================================

class ActivityLogCreate(BaseModel):
    action: str
    entity_type: str
    entity_id: UUID
    summary: Optional[str] = None
    changes: Optional[dict[str, Any]] = None


class ActivityLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    action: str
    entity_type: str
    entity_id: UUID
    summary: Optional[str] = None
    changes: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Tag
# ===========================================================================

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None
    entity_type: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    entity_type: Optional[str] = None


class TagResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    color: Optional[str] = None
    entity_type: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# NameCard Tag (V2 module) — dedicated tag definitions for name cards
# ===========================================================================

class NameCardTagResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    label: str
    color: Optional[str] = None
    usage_count: int = 0  # number of name_cards carrying this tag label
    created_at: datetime


class NameCardTagCreate(BaseModel):
    label: str
    color: Optional[str] = None


class NameCardTagUpdate(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None


class NameCardTagMergeRequest(BaseModel):
    tag_ids: list[UUID]
    into_label: str


class NameCardTagCleanupGroup(BaseModel):
    tag_ids: list[UUID]
    group_label: str
    reason: str


class NameCardTagCleanupResponse(BaseModel):
    groups: list[NameCardTagCleanupGroup]


# ===========================================================================
# ContactProject (contact <-> deal junction)
# ===========================================================================

class ContactProjectCreate(BaseModel):
    contact_id: UUID
    project_id: UUID
    role: Optional[str] = None


class ContactProjectResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    contact_id: UUID
    project_id: UUID
    role: Optional[str] = None
    created_at: datetime
    project_name: Optional[str] = None
    amount: Optional[float] = None
    stage_name: Optional[str] = None
    probability: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Project
# ===========================================================================


class ProjectCreate(BaseModel):
    name: str
    project_code: Optional[str] = None
    # 2026-09-11 用戶指示：Project 唔需要綁公司 → optional
    # （projects.company_id 已由 migration 021 DROP NOT NULL）
    company_id: Optional[UUID] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    deal_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    budget_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    project_manager_id: Optional[UUID] = None
    sales_owner_id: Optional[UUID] = None
    incharge_client_id: Optional[UUID] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    project_code: Optional[str] = None
    company_id: Optional[UUID] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    deal_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    budget_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    project_manager_id: Optional[UUID] = None
    sales_owner_id: Optional[UUID] = None
    incharge_client_id: Optional[UUID] = None


class ProjectResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_code: str
    name: str
    company_id: Optional[UUID] = None
    company: Optional[dict] = None
    deal_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    stage_updated_at: Optional[datetime] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    description: Optional[str] = None
    budget_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    project_manager_id: Optional[UUID] = None
    sales_owner_id: Optional[UUID] = None
    incharge_client_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Project Calendar Event
# ===========================================================================


class ProjectCalendarEventCreate(BaseModel):
    project_id: Optional[UUID] = None  # None = standalone event (not tied to a project)
    title: str
    description: Optional[str] = None
    event_type: Optional[str] = "milestone"
    start: datetime
    end: datetime
    is_all_day: Optional[bool] = False
    color: Optional[str] = "#00693E"
    location: Optional[str] = None


class ProjectCalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    is_all_day: Optional[bool] = None
    color: Optional[str] = None
    location: Optional[str] = None


class ProjectCalendarEventResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    event_type: Optional[str] = None
    start: datetime
    end: datetime
    is_all_day: Optional[bool] = False
    color: Optional[str] = None
    location: Optional[str] = None
    owner_user_id: Optional[UUID] = None
    source: Optional[str] = None
    external_event_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# Task (MS To Do extension)
# ===========================================================================

class TaskCreateTodo(BaseModel):
    title: str
    list_id: Optional[UUID] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: str = "medium"
    status: str = "pending"
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    is_important: bool = False
    my_day_date: Optional[date] = None
    reminder_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    notes_html: Optional[str] = None


class TaskUpdateTodo(BaseModel):
    title: Optional[str] = None
    list_id: Optional[UUID] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    is_important: Optional[bool] = None
    my_day_date: Optional[date] = None
    reminder_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    notes_html: Optional[str] = None


class TaskResponseTodo(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assignee_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    list_id: Optional[UUID] = None
    is_important: bool = False
    my_day_date: Optional[date] = None
    reminder_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    notes_html: Optional[str] = None
    created_by: Optional[UUID] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    steps: list[Any] = []
    categories: list[Any] = []
    attachments: list[Any] = []

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# TaskList
# ===========================================================================

class TaskListCreate(BaseModel):
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0


class TaskListUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None


class TaskListResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    is_smart: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# TaskStep
# ===========================================================================

class TaskStepCreate(BaseModel):
    title: str


class TaskStepUpdate(BaseModel):
    title: Optional[str] = None
    is_completed: Optional[bool] = None


class TaskStepReorder(BaseModel):
    step_ids: list[UUID]


class TaskStepResponse(BaseModel):
    id: UUID
    task_id: UUID
    title: str
    is_completed: bool = False
    sort_order: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# TaskCategory
# ===========================================================================

class TaskCategoryCreate(BaseModel):
    name: str
    color: Optional[str] = None


class TaskCategoryResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    color: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskCategoryMapCreate(BaseModel):
    category_id: UUID


# ===========================================================================
# TaskAttachment
# ===========================================================================

class TaskAttachmentResponse(BaseModel):
    id: UUID
    task_id: UUID
    filename: str
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    storage_path: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# ListShare
# ===========================================================================

class ListShareCreate(BaseModel):
    user_id: UUID
    permission: str = "read"


class ListShareResponse(BaseModel):
    list_id: UUID
    user_id: UUID
    permission: str = "read"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===========================================================================
# FieldOption (v5: per-user custom option — industry/category/status combobox)
# ===========================================================================

class FieldOptionCreate(BaseModel):
    module: str
    field: str
    value: str


class FieldOptionResponse(BaseModel):
    id: UUID
    value: str
    label: str


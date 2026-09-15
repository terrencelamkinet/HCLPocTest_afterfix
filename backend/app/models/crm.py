import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Integer, Date, Numeric, JSON, ARRAY, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates
from app.db import Base


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(Text, nullable=False)
    domain = Column(Text)
    industry = Column(Text)
    size = Column(Text)  # 1-10, 11-50, 51-200, 201-1000, 1000+
    phone = Column(Text)
    address = Column(Text)
    website = Column(Text)
    notes = Column(Text)
    tags = Column(ARRAY(Text), default=lambda: [])
    owner_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    custom_fields = Column(JSON, default=lambda: {})
    category = Column(String(50))
    ceo_name = Column(String(255))
    linkedin_url = Column(String(255))
    status = Column(String(50), default='ACTIVE')
    # --- AI governance (006) ---
    enriched_by_ai = Column(Boolean, default=False)
    enrichment_source_url = Column(Text)
    data_completeness_pct = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    contacts = relationship("Contact", back_populates="company")
    touchpoints = relationship("Touchpoint", back_populates="company")
    tasks = relationship("Task", back_populates="company")
    notes_rel = relationship("Note", back_populates="company")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="SET NULL"))
    name = Column(Text, nullable=False)
    chinese_name = Column(Text)
    nick_name = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    office_phone = Column(Text)
    numbers = Column(ARRAY(Text), default=lambda: [])
    job_title = Column(Text)
    department = Column(Text)
    linkedin_url = Column(Text)
    avatar_url = Column(Text)
    address = Column(Text)
    notes = Column(Text)
    tags = Column(ARRAY(Text), default=lambda: [])
    contact_type = Column(Text)
    grade = Column(Text)
    source = Column(Text)  # referral, linkedin, event, cold_outbound, namecard, other
    status = Column(Text, default="lead")  # lead, prospect, customer, churned, other
    owner_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    custom_fields = Column(JSON, default=lambda: {})
    namecard_path = Column(Text)
    # --- AI governance (006) ---
    source_signal_id = Column(UUID(as_uuid=True))  # triggering signal (name_card.id / email.id / meeting.id)
    confidence_score = Column(Numeric(4, 3))
    dedup_status = Column(Text, default="none")  # none | auto_matched | llm_review | unresolved | user_override
    last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="contacts")
    touchpoints = relationship("Touchpoint", back_populates="contact")
    touchpoints_as_participant = relationship("Touchpoint", secondary="nexus_crm.touchpoint_participants", back_populates="participants", lazy="selectin", viewonly=True)
    tasks = relationship("Task", back_populates="contact")
    notes_rel = relationship("Note", back_populates="contact")
    name_cards = relationship("NameCard", back_populates="contact")
    contact_projects = relationship("ContactProject", back_populates="contact", cascade="all, delete-orphan")


class TouchpointParticipant(Base):
    __tablename__ = "touchpoint_participants"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    touchpoint_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.touchpoints.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="CASCADE"), nullable=False)


class TouchpointCompany(Base):
    """Touchpoint ↔ Company many-to-many (011, 2026-09-09)."""
    __tablename__ = "touchpoint_companies"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    touchpoint_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.touchpoints.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), nullable=False)


class Touchpoint(Base):
    __tablename__ = "touchpoints"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="SET NULL"))
    type = Column(Text, nullable=False)  # meeting, call, email, note, social, lunch, other
    title = Column(Text, nullable=False)
    description = Column(Text)
    date = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    duration_minutes = Column(Integer)
    location = Column(Text)
    # --- AI governance (006) ---
    channel_type = Column(Text)      # meeting | call | email | social | other
    extracted_from = Column(Text)    # namecard | email | meeting | manual
    created_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    contact = relationship("Contact", back_populates="touchpoints")
    participants = relationship("Contact", secondary="nexus_crm.touchpoint_participants", back_populates="touchpoints", lazy="selectin")
    company = relationship("Company", back_populates="touchpoints")
    # Multi-company (011): 全部關聯公司 — company_id 係「主要公司」（company 關係）
    companies = relationship("Company", secondary="nexus_crm.touchpoint_companies", lazy="selectin", viewonly=True)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    due_date = Column(Date)
    priority = Column(Text, default="medium")  # low, medium, high, urgent
    status = Column(Text, default="pending")  # pending, in_progress, done, cancelled
    assignee_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="SET NULL"))
    deal_id = Column(UUID(as_uuid=True))  # NULL for Module A, filled by Module B
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tasks.id", ondelete="SET NULL"))
    recurring = Column(Boolean, default=False)
    area = Column(Text)
    # --- AI governance (006) ---
    auto_suggested = Column(Boolean, default=False)
    suggestion_confidence = Column(Numeric(4, 3))
    linked_via_signal = Column(UUID(as_uuid=True))
    created_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # --- MS To Do fields ---
    list_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.task_lists.id", ondelete="SET NULL"))
    is_important = Column(Boolean, default=False)
    my_day_date = Column(Date)
    reminder_at = Column(DateTime(timezone=True))
    recurrence_rule = Column(Text)  # RRULE string
    notes_html = Column(Text)

    parent = relationship("Task", remote_side="Task.id", backref="subtasks")
    contact = relationship("Contact", back_populates="tasks")
    company = relationship("Company", back_populates="tasks")
    task_list = relationship("TaskList", back_populates="tasks")
    steps = relationship("TaskStep", back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.sort_order")
    categories = relationship("TaskCategory", secondary="nexus_crm.task_category_map", back_populates="tasks", lazy="selectin")
    attachments = relationship("TaskAttachment", back_populates="task", cascade="all, delete-orphan")


class TaskList(Base):
    __tablename__ = "task_lists"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    color = Column(Text)
    icon = Column(Text)
    sort_order = Column(Integer, default=0)
    is_smart = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tasks = relationship("Task", back_populates="task_list")
    shares = relationship("ListShare", back_populates="task_list", cascade="all, delete-orphan")


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tasks.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    is_completed = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task = relationship("Task", back_populates="steps")


class TaskCategory(Base):
    __tablename__ = "task_categories"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    color = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tasks = relationship("Task", secondary="nexus_crm.task_category_map", back_populates="categories", lazy="selectin")


class TaskCategoryMap(Base):
    __tablename__ = "task_category_map"
    __table_args__ = {"schema": "nexus_crm"}

    task_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tasks.id", ondelete="CASCADE"), primary_key=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.task_categories.id", ondelete="CASCADE"), primary_key=True)


class TaskAttachment(Base):
    __tablename__ = "task_attachments"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tasks.id", ondelete="CASCADE"), nullable=False)
    filename = Column(Text, nullable=False)
    file_size = Column(Integer)
    content_type = Column(Text)
    storage_path = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task = relationship("Task", back_populates="attachments")


class ListShare(Base):
    __tablename__ = "list_shares"
    __table_args__ = {"schema": "nexus_crm"}

    list_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.task_lists.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="CASCADE"), primary_key=True)
    permission = Column(Text, default="read")  # read, write
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    task_list = relationship("TaskList", back_populates="shares")


class NameCard(Base):
    __tablename__ = "name_cards"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    image_url = Column(Text)  # legacy: display image (kept for backward compat)
    original_image_url = Column(Text)  # as-photographed original
    cropped_image_url = Column(Text)   # perspective-corrected crop (NULL = crop failed/not verified)
    display_image = Column(Text, default="cropped")  # 'original' | 'cropped' — which one UI shows
    raw_ocr_text = Column(Text)
    parsed_data = Column(JSON, default=lambda: {})
    review_candidates = Column(JSON, default=lambda: [])  # potential duplicates for user resolution
    tags = Column(JSON, default=lambda: [])  # V2: label list (e.g. ['物流', '供應商'])
    field_confidence = Column(JSON, default=lambda: {})  # V2: per-field AI confidence 0..1 (e.g. {'name': 0.97})
    duplicate_candidate = Column(JSON)  # V2: { contact_id, reason } when AI suspects a duplicate match
    dedup_status = Column(Text)  # none | auto_matched | llm_review | unresolved | user_override
    status = Column(Text, default="pending")  # pending, matched, created, review, ignored
    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    matched_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    contact = relationship("Contact", back_populates="name_cards")


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(Text)
    content = Column(Text)
    pinned = Column(Boolean, default=False)
    tags = Column(ARRAY(Text), default=lambda: [])
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="SET NULL"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.projects.id", ondelete="SET NULL"))
    task_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tasks.id", ondelete="SET NULL"))
    notebook_id = Column(UUID(as_uuid=True))  # FK exists in DB (017); no ORM model for notebooks (raw-SQL API) → plain column
    template_id = Column(UUID(as_uuid=True))
    created_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Notes V2 — Stage B/C（migration 019）
    # deleted_at：soft delete（T-04 撤銷）。NULL = 未刪；所有正常 query 都要 filter。
    # version：樂觀鎖（T-02）。每次更新 +1；PATCH 帶 expected_version 唔匹配 → 409。
    deleted_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, default=1, server_default="1")

    contact = relationship("Contact", back_populates="notes_rel")
    company = relationship("Company", back_populates="notes_rel")

    # ── 2026-09-15 SAST（AppScan HCLPoCTest：stored XSS）──────────────────
    # Note.content 係用戶／AI 提供嘅 HTML，前端用 dangerouslySetInnerHTML render。
    # 清洗放喺 ORM 層 = 所有寫入路徑（create / update / restore revision /
    # template / AI write flow / 將來新增）一次過覆蓋，唔需要逐個 endpoint 加 guard。
    # 清洗邏輯（allowlist）見 app/services/html_sanitize.py。
    @validates("content")
    def _sanitize_content(self, _key, value):
        from app.services.html_sanitize import sanitize_note_html
        return sanitize_note_html(value)


class NoteRevision(Base):
    """Notes V2 Stage C (T-03) — 筆記版本快照（migration 019）。

    每次更新（throttle 5 分鐘）寫入「被取代嘅舊狀態」。version = 當時 note.version。
    用於 History drawer 睇舊版 + 還原。
    """
    __tablename__ = "note_revisions"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    note_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.notes.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(Text)
    content = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserPreference(Base):
    """Notes V2 Stage D (T-14) — per-user key/value 偏好（migration 020）。

    用於 highlight 自訂色等設定跨裝置同步（原本只存 localStorage）。
    RLS 係 tenant 級；per-user 隔離由 composite PK + app 層 user_id filter 保證。
    """
    __tablename__ = "user_preferences"
    __table_args__ = {"schema": "nexus_crm"}

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="CASCADE"), primary_key=True)
    key = Column(Text, primary_key=True)
    value = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    action = Column(Text, nullable=False)  # created, updated, deleted, restored
    entity_type = Column(Text, nullable=False)  # contact, company, touchpoint, task, name_card, note, deal, quote
    entity_id = Column(UUID(as_uuid=True))
    summary = Column(Text)
    changes = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    color = Column(Text)
    entity_type = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NoteTag(Base):
    """Notes V2 (T2.1) — junction linking notes to reusable tenant tags.

    Additive module: reuses nexus_crm.tags (name/color) and never mutates the
    legacy notes.tags text[] column, so disabling the module cannot delete
    historical data. tenant_id is carried on the junction for strict tenant
    isolation / RLS.
    """
    __tablename__ = "note_tags"
    __table_args__ = (
        UniqueConstraint("note_id", "tag_id", name="uq_note_tags_note_tag"),
        {"schema": "nexus_crm"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    note_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.notes.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.tags.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NoteLink(Base):
    """Notes V2 (T3.1) — link a note to any CRM record (@mention / +Link record).

    Additive module (SPEC Q2): the legacy single-FK columns on notes
    (contact_id/company_id/project_id/task_id) stay but are no longer written.
    tenant_id is carried for strict tenant isolation / RLS.
    """
    __tablename__ = "note_links"
    __table_args__ = (
        UniqueConstraint("note_id", "entity_type", "entity_id", name="uq_note_links_note_entity"),
        {"schema": "nexus_crm"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    note_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.notes.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=True))
    label = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NoteLinkDismissal(Base):
    """Notes V2 (T3.3) — dismissed rule-based link suggestions.

    Additive: keeps 「略過」 sticky so the same suggestion never pops up again
    for the same note + record (SPEC acceptance #11). tenant-scoped + RLS.
    """
    __tablename__ = "note_link_dismissals"
    __table_args__ = (
        UniqueConstraint("note_id", "entity_type", "entity_id", name="uq_note_link_dismissals_note_entity"),
        {"schema": "nexus_crm"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    note_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.notes.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class NameCardTag(Base):
    __tablename__ = "namecard_tags"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    label = Column(Text, nullable=False)
    color = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ContactProject(Base):
    __tablename__ = "contact_projects"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    contact = relationship("Contact", back_populates="contact_projects")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    project_code = Column(String(100), nullable=False, default=lambda: f"PRJ-{uuid.uuid4().hex[:8].upper()}")
    name = Column(Text, nullable=False)
    # 2026-09-11 用戶指示：Project 唔需要綁公司 → nullable（migration 021 DROP NOT NULL）
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="SET NULL"), nullable=True)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deals.id", ondelete="SET NULL"))
    stage_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.project_stages.id", ondelete="SET NULL"))
    stage_updated_at = Column(DateTime(timezone=True))
    status = Column(String(50), default="planning")
    priority = Column(String(50), default="medium")
    description = Column(Text)
    budget_amount = Column(Numeric)
    start_date = Column(DateTime(timezone=True))
    deadline = Column(DateTime(timezone=True))
    end_date = Column(DateTime(timezone=True))
    project_manager_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    sales_owner_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="SET NULL"))
    incharge_client_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    company = relationship("Company", foreign_keys=[company_id])


class ProjectCalendarEvent(Base):
    __tablename__ = "project_calendar_events"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.projects.id", ondelete="CASCADE"), nullable=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    event_type = Column(String(50), default="milestone")  # milestone, task, meeting, reminder
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)
    is_all_day = Column(Boolean, default=False)
    color = Column(String(20), default="#00693E")
    location = Column(Text)
    owner_user_id = Column(UUID(as_uuid=True), nullable=True)
    visibility_scope = Column(Text, default="workspace")  # workspace | private | team | tenant_admin
    team_id = Column(UUID(as_uuid=True), nullable=True)
    source = Column(String(20), nullable=False, default="manual")  # manual | google_oauth | ics
    external_event_id = Column(String(500), nullable=True)
    external_updated = Column(DateTime(timezone=True), nullable=True)
    # ── Calendar lifecycle state machine（migration 010 — P1/P2/P3）──
    reminder_t60_sent_at = Column(DateTime(timezone=True), nullable=True)   # T-60 提醒已發
    reminder_t15_sent_at = Column(DateTime(timezone=True), nullable=True)   # T-15 AI briefing 已發
    followup_status = Column(String(20), nullable=False, default="pending") # T+30 touchpoint follow-up
    followup_asked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project")


class AiAgentLog(Base):
    """AI agent execution audit trail — full reasoning chain per decision (migration 006).

    One row per agent step in the pipeline (ingestion → extraction →
    entity_resolution → enrichment → inference). Input/output snapshots keep
    the evidence; user_decision records the human's final call for
    calibration of confidence thresholds.
    """
    __tablename__ = "ai_agent_log"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False)
    signal_type = Column(Text, nullable=False)   # namecard | email | meeting | manual
    signal_id = Column(UUID(as_uuid=True))        # triggering signal id (name_card.id …)
    agent_name = Column(Text, nullable=False)     # ingestion | extraction | entity_resolution | enrichment | inference
    agent_version = Column(Text)                  # prompt/model version tag
    provider = Column(Text)                       # deepseek | perplexity | heuristic
    model = Column(Text)                          # actual model name
    input_snapshot = Column(JSON, default=lambda: {})
    output_snapshot = Column(JSON, default=lambda: {})
    confidence = Column(Numeric(4, 3))
    decision = Column(Text)                       # auto_link | review | create | enrich | suggest
    user_decision = Column(Text)                  # accept | reject | override | none
    latency_ms = Column(Integer)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserFieldOption(Base):
    """v5: per-user custom option（industry/category/status combobox 嘅 custom value）。

    Tenant DISTINCT values 之外嘅額外 layer — 用戶自己打字 + Create 自訂嘅 option，
    tenant-wide persistence（多 user 共用 tenant）但 per-user 管轄（自己 delete 自己嘅）。
    """
    __tablename__ = "user_field_options"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "module", "field", "value", name="uq_user_field_option"),
        {"schema": "nexus_crm"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("nexus_auth.nexus_auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    module = Column(String(50), nullable=False)
    field = Column(String(50), nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

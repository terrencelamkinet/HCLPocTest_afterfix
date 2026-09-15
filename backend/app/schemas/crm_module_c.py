from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from uuid import UUID


class ModuleRegistryOut(BaseModel):
    id: UUID
    module_key: str
    module_name: str
    module_group: Optional[str] = None
    description: Optional[str] = None
    depends_on_module_key: Optional[str] = None
    is_core: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantModuleSettingOut(BaseModel):
    id: UUID
    tenant_id: UUID
    module_key: str
    is_enabled: bool = True
    enabled_at: Optional[datetime] = None
    disabled_at: Optional[datetime] = None
    updated_by: Optional[UUID] = None

    model_config = {"from_attributes": True}


class TenantModuleSettingUpsert(BaseModel):
    module_key: str
    is_enabled: bool


class FileOut(BaseModel):
    id: UUID
    storage_key: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_by: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleOut(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    role_key: str
    role_name: str
    is_system: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    role_key: str
    role_name: str


class PermissionOut(BaseModel):
    id: UUID
    permission_key: str
    permission_name: str
    module_key: Optional[str] = None

    model_config = {"from_attributes": True}


class DepartmentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    parent_department_id: Optional[UUID] = None
    name: str
    code: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str
    code: Optional[str] = None
    parent_department_id: Optional[UUID] = None


class TeamOut(BaseModel):
    id: UUID
    tenant_id: UUID
    department_id: Optional[UUID] = None
    name: str
    team_type: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamCreate(BaseModel):
    name: str
    department_id: Optional[UUID] = None
    team_type: Optional[str] = None


class TeamMemberOut(BaseModel):
    team_id: UUID
    user_id: UUID
    role_in_team: str = "MEMBER"
    joined_at: datetime

    model_config = {"from_attributes": True}


# ── Phase 2: Team & Org remaining ──

class DepartmentTargetOut(BaseModel):
    id: UUID
    tenant_id: UUID
    department_id: Optional[UUID] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_metric: Optional[str] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DepartmentTargetCreate(BaseModel):
    department_id: UUID
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_metric: Optional[str] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None


class UserTargetOut(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_metric: Optional[str] = None
    target_value: Optional[float] = None
    actual_value: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserTargetCreate(BaseModel):
    user_id: UUID
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_metric: Optional[str] = None
    target_value: Optional[float] = None


class DispatchRuleOut(BaseModel):
    id: UUID
    tenant_id: UUID
    team_id: Optional[UUID] = None
    rule_name: Optional[str] = None
    criteria_json: Optional[dict] = None
    priority_order: Optional[int] = None
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class DispatchRuleCreate(BaseModel):
    team_id: Optional[UUID] = None
    rule_name: Optional[str] = None
    criteria_json: Optional[dict] = None
    priority_order: Optional[int] = None


# ── Phase 2: Activities ──

class ActivityOut(BaseModel):
    id: UUID
    tenant_id: UUID
    activity_type: str
    reference_title: Optional[str] = None
    activity_time: datetime
    summary: Optional[str] = None
    content: Optional[str] = None
    ai_summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    owner_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActivityCreate(BaseModel):
    activity_type: str
    reference_title: Optional[str] = None
    activity_time: Optional[datetime] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    sentiment_score: Optional[float] = None
    owner_user_id: Optional[UUID] = None
    contact_ids: Optional[list[UUID]] = None
    company_ids: Optional[list[UUID]] = None


# ── Phase 2: Projects ──

class ProjectStageOut(BaseModel):
    id: UUID
    tenant_id: UUID
    stage_key: str
    stage_name: str
    stage_order: int

    model_config = {"from_attributes": True}


class ProjectStageCreate(BaseModel):
    stage_key: str
    stage_name: str
    stage_order: int


class ProjectOut(BaseModel):
    id: UUID
    tenant_id: UUID
    project_code: str
    name: str
    company_id: UUID
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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    project_code: str
    name: str
    # 2026-09-11 用戶指示：Project 唔需要綁公司 → optional（migration 021 DROP NOT NULL）
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    description: Optional[str] = None
    budget_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    project_manager_id: Optional[UUID] = None
    contact_ids: Optional[list[UUID]] = None
    product_ids: Optional[list[UUID]] = None


# ── Phase 2: Company linking ──

class CompanyIndustryOut(BaseModel):
    company_id: UUID
    industry_name: str

    model_config = {"from_attributes": True}


class CompanyCountryOut(BaseModel):
    company_id: UUID
    country_code: str

    model_config = {"from_attributes": True}


class CompanyProductInUseOut(BaseModel):
    company_id: UUID
    product_id: UUID
    since_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CompanyPartnerOut(BaseModel):
    company_id: UUID
    partner_company_id: UUID
    relation_type: str

    model_config = {"from_attributes": True}


class DealContactOut(BaseModel):
    deal_id: UUID
    contact_id: UUID
    role_type: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Phase 3: AI Layer ──

class StakeholderMapOut(BaseModel):
    id: UUID
    tenant_id: UUID
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    generated_by_agent_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StakeholderMapCreate(BaseModel):
    company_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None


class StakeholderRelationOut(BaseModel):
    id: UUID
    map_id: UUID
    contact_id: Optional[UUID] = None
    reports_to_contact_id: Optional[UUID] = None
    influence_level: Optional[str] = None
    decision_role: Optional[str] = None
    sentiment: Optional[str] = None

    model_config = {"from_attributes": True}


class StakeholderRelationCreate(BaseModel):
    contact_id: UUID
    reports_to_contact_id: Optional[UUID] = None
    influence_level: Optional[str] = None
    decision_role: Optional[str] = None
    sentiment: Optional[str] = None


class AIRelationshipScoreOut(BaseModel):
    id: UUID
    tenant_id: UUID
    target_type: str
    target_id: UUID
    score: float
    trend: Optional[str] = None
    computed_at: datetime

    model_config = {"from_attributes": True}


class AIRelationshipScoreCreate(BaseModel):
    target_type: str
    target_id: UUID
    score: float
    trend: Optional[str] = None


class AIEnrichmentJobOut(BaseModel):
    id: UUID
    tenant_id: UUID
    target_type: str
    target_id: UUID
    source_channel: Optional[str] = None
    status: str = "PENDING"
    enriched_fields_json: Optional[dict] = None
    run_at: datetime

    model_config = {"from_attributes": True}


class AIEnrichmentJobCreate(BaseModel):
    target_type: str
    target_id: UUID
    source_channel: Optional[str] = None


class AIMeetingBriefOut(BaseModel):
    id: UUID
    tenant_id: UUID
    activity_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    brief_text: Optional[str] = None
    generated_at: datetime

    model_config = {"from_attributes": True}


class AIMeetingBriefCreate(BaseModel):
    activity_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    brief_text: str


class AIRecommendationOut(BaseModel):
    id: UUID
    tenant_id: UUID
    target_module: str
    target_record_id: UUID
    recommendation_type: str
    title: str
    rationale: Optional[str] = None
    confidence_score: Optional[float] = None
    priority_score: Optional[float] = None
    status: str = "OPEN"
    generated_by_agent_id: Optional[UUID] = None
    created_at: datetime
    acted_at: Optional[datetime] = None
    acted_by: Optional[UUID] = None

    model_config = {"from_attributes": True}


class AIRecommendationCreate(BaseModel):
    target_module: str
    target_record_id: UUID
    recommendation_type: str
    title: str
    rationale: Optional[str] = None
    confidence_score: Optional[float] = None
    priority_score: Optional[float] = None
    generated_by_agent_id: Optional[UUID] = None


class AIForecastOut(BaseModel):
    id: UUID
    tenant_id: UUID
    forecast_scope: str
    scope_record_id: Optional[UUID] = None
    forecast_type: str
    forecast_period_start: Optional[datetime] = None
    forecast_period_end: Optional[datetime] = None
    forecast_value: Optional[float] = None
    confidence_low: Optional[float] = None
    confidence_high: Optional[float] = None
    explanation: Optional[str] = None
    generated_by_agent_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AIForecastCreate(BaseModel):
    forecast_scope: str
    scope_record_id: Optional[UUID] = None
    forecast_type: str
    forecast_period_start: Optional[datetime] = None
    forecast_period_end: Optional[datetime] = None
    forecast_value: Optional[float] = None
    confidence_low: Optional[float] = None
    confidence_high: Optional[float] = None
    explanation: Optional[str] = None
    generated_by_agent_id: Optional[UUID] = None


# ── Phase 4: Custom Field Engine ──

class CustomFieldDefinitionOut(BaseModel):
    id: UUID
    tenant_id: UUID
    module_name: str
    field_key: str
    field_label: str
    field_type: str
    is_required: bool = False
    options_json: Optional[dict] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class CustomFieldDefinitionCreate(BaseModel):
    module_name: str
    field_key: str
    field_label: str
    field_type: str
    is_required: bool = False
    options_json: Optional[dict] = None

class CustomFieldValueOut(BaseModel):
    id: UUID
    tenant_id: UUID
    definition_id: UUID
    record_id: UUID
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_date: Optional[datetime] = None
    value_json: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class CustomFieldValueUpsert(BaseModel):
    record_id: UUID
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_date: Optional[datetime] = None
    value_json: Optional[dict] = None

# ── Phase 5: Workflow Apps ──

class WorkflowAppOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    target_module: Optional[str] = None
    created_by: Optional[UUID] = None
    status: str = "DRAFT"
    created_at: datetime
    model_config = {"from_attributes": True}

class WorkflowAppCreate(BaseModel):
    name: str
    description: Optional[str] = None
    target_module: Optional[str] = None

class WorkflowAppStepOut(BaseModel):
    id: UUID
    app_id: UUID
    step_order: int
    step_type: str
    config_json: Optional[dict] = None
    agent_id: Optional[UUID] = None
    model_config = {"from_attributes": True}

class WorkflowAppStepCreate(BaseModel):
    step_order: int
    step_type: str
    config_json: Optional[dict] = None
    agent_id: Optional[UUID] = None

class WorkflowAppRunOut(BaseModel):
    id: UUID
    app_id: Optional[UUID] = None
    triggered_by: Optional[UUID] = None
    input_data: Optional[dict] = None
    output_data: Optional[dict] = None
    status: str = "RUNNING"
    started_at: datetime
    completed_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

# ── Phase 6: Shipping / Logistics ──

class TradeLaneOut(BaseModel):
    id: UUID
    tenant_id: UUID
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    transport_mode: Optional[str] = None
    base_rate: Optional[float] = None
    currency: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    model_config = {"from_attributes": True}

class TradeLaneCreate(BaseModel):
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    transport_mode: Optional[str] = None
    base_rate: Optional[float] = None
    currency: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

class RateRequestOut(BaseModel):
    id: UUID
    tenant_id: UUID
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    trade_lane_id: Optional[UUID] = None
    cargo_description: Optional[str] = None
    requested_at: datetime
    status: str = "OPEN"
    owner_user_id: Optional[UUID] = None
    model_config = {"from_attributes": True}

class RateRequestCreate(BaseModel):
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    trade_lane_id: Optional[UUID] = None
    cargo_description: Optional[str] = None
    owner_user_id: Optional[UUID] = None

class QuotationOut(BaseModel):
    id: UUID
    tenant_id: UUID
    rate_request_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    quote_number: Optional[str] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    status: str = "DRAFT"
    valid_until: Optional[datetime] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class QuotationCreate(BaseModel):
    rate_request_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    quote_number: Optional[str] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None

class ShipmentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    quotation_id: Optional[UUID] = None
    shipment_number: Optional[str] = None
    transport_mode: Optional[str] = None
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    etd: Optional[datetime] = None
    eta: Optional[datetime] = None
    status: str = "BOOKED"
    created_at: datetime
    model_config = {"from_attributes": True}

class ShipmentCreate(BaseModel):
    project_id: Optional[UUID] = None
    quotation_id: Optional[UUID] = None
    shipment_number: Optional[str] = None
    transport_mode: Optional[str] = None
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    etd: Optional[datetime] = None
    eta: Optional[datetime] = None

class ShipmentPartyOut(BaseModel):
    id: UUID
    shipment_id: UUID
    party_role: str
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    notes: Optional[str] = None
    model_config = {"from_attributes": True}

class ShipmentPartyCreate(BaseModel):
    party_role: str
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    notes: Optional[str] = None

class DispatchQueueOut(BaseModel):
    id: UUID
    tenant_id: UUID
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    source_channel: Optional[str] = None
    status: str = "PENDING"
    created_at: datetime
    model_config = {"from_attributes": True}

class DispatchQueueCreate(BaseModel):
    company_id: Optional[UUID] = None
    contact_id: Optional[UUID] = None
    source_channel: Optional[str] = None

class CreditControlRuleOut(BaseModel):
    id: UUID
    tenant_id: UUID
    company_id: Optional[UUID] = None
    credit_limit: Optional[float] = None
    overdue_days_threshold: int = 30
    is_active: bool = True
    model_config = {"from_attributes": True}

class CreditControlRuleCreate(BaseModel):
    company_id: Optional[UUID] = None
    credit_limit: Optional[float] = None
    overdue_days_threshold: int = 30

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Integer, BigInteger, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db import Base


class ModuleRegistry(Base):
    __tablename__ = "module_registry"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_key = Column(String(100), unique=True, nullable=False)
    module_name = Column(String(255), nullable=False)
    module_group = Column(String(50))
    description = Column(Text)
    depends_on_module_key = Column(String(100), ForeignKey("nexus_crm.module_registry.module_key"))
    is_core = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TenantModuleSetting(Base):
    __tablename__ = "tenant_module_settings"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    module_key = Column(String(100), ForeignKey("nexus_crm.module_registry.module_key"), nullable=False)
    is_enabled = Column(Boolean, default=True)
    enabled_at = Column(DateTime(timezone=True))
    disabled_at = Column(DateTime(timezone=True))
    updated_by = Column(UUID(as_uuid=True))


class File(Base):
    __tablename__ = "files"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    storage_key = Column(Text, nullable=False)
    original_filename = Column(String(255))
    mime_type = Column(String(100))
    file_size = Column(BigInteger)
    uploaded_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True))
    role_key = Column(String(100), nullable=False)
    role_name = Column(String(255), nullable=False)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    permission_key = Column(String(150), unique=True, nullable=False)
    permission_name = Column(String(255), nullable=False)
    module_key = Column(String(100))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "nexus_crm"}

    role_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.permissions.id", ondelete="CASCADE"), primary_key=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "nexus_crm"}

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.roles.id", ondelete="CASCADE"), primary_key=True)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    parent_department_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.departments.id"))
    name = Column(String(255), nullable=False)
    code = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    children = relationship("Department", backref="parent", remote_side=[id])


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.departments.id"))
    name = Column(String(255), nullable=False)
    team_type = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = {"schema": "nexus_crm"}

    team_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.teams.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), primary_key=True)
    role_in_team = Column(String(50), default="MEMBER")
    joined_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserDepartmentAssignment(Base):
    __tablename__ = "user_department_assignments"
    __table_args__ = {"schema": "nexus_crm"}

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.departments.id", ondelete="CASCADE"), primary_key=True)
    is_primary = Column(Boolean, default=True)
    assigned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Phase 2: Team & Org remaining ──────────────────────────────

class DepartmentTarget(Base):
    __tablename__ = "department_targets"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    department_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.departments.id", ondelete="CASCADE"))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    target_metric = Column(String(50))
    target_value = Column(Numeric(18, 2))
    actual_value = Column(Numeric(18, 2))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserTarget(Base):
    __tablename__ = "user_targets"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    target_metric = Column(String(50))
    target_value = Column(Numeric(18, 2))
    actual_value = Column(Numeric(18, 2))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DispatchRule(Base):
    __tablename__ = "dispatch_rules"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    team_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.teams.id"))
    rule_name = Column(String(255))
    criteria_json = Column(JSONB)
    priority_order = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Phase 2: Company linking tables ────────────────────────────

class CompanyIndustry(Base):
    __tablename__ = "company_industries"
    __table_args__ = {"schema": "nexus_crm"}

    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    industry_name = Column(String(100), primary_key=True)


class CompanyCountry(Base):
    __tablename__ = "company_countries"
    __table_args__ = {"schema": "nexus_crm"}

    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    country_code = Column(String(10), primary_key=True)


class CompanyProductInUse(Base):
    __tablename__ = "company_products_in_use"
    __table_args__ = {"schema": "nexus_crm"}

    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.products.id", ondelete="CASCADE"), primary_key=True)
    since_date = Column(DateTime)


class CompanyProductProposal(Base):
    __tablename__ = "company_product_proposals"
    __table_args__ = {"schema": "nexus_crm"}

    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.products.id", ondelete="CASCADE"), primary_key=True)
    proposed_at = Column(DateTime(timezone=True))


class CompanyPartner(Base):
    __tablename__ = "company_partners"
    __table_args__ = {"schema": "nexus_crm"}

    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    partner_company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)
    relation_type = Column(String(50), primary_key=True)


# ── Phase 2: Activities ────────────────────────────────────────

class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    activity_type = Column(String(50), nullable=False)
    reference_title = Column(String(255))
    activity_time = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    summary = Column(Text)
    content = Column(Text)
    ai_summary = Column(Text)
    sentiment_score = Column(Numeric(5, 2))
    owner_user_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ActivityContact(Base):
    __tablename__ = "activity_contacts"
    __table_args__ = {"schema": "nexus_crm"}

    activity_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.activities.id", ondelete="CASCADE"), primary_key=True)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="CASCADE"), primary_key=True)


class ActivityCompany(Base):
    __tablename__ = "activity_companies"
    __table_args__ = {"schema": "nexus_crm"}

    activity_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.activities.id", ondelete="CASCADE"), primary_key=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.companies.id", ondelete="CASCADE"), primary_key=True)


# ── Phase 2: Deal linking ──────────────────────────────────────

class DealContact(Base):
    __tablename__ = "deal_contacts"
    __table_args__ = {"schema": "nexus_crm"}

    deal_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.deals.id", ondelete="CASCADE"), primary_key=True)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="CASCADE"), primary_key=True)
    role_type = Column(String(50))


# ── Phase 2: Projects module ───────────────────────────────────

class ProjectStage(Base):
    __tablename__ = "project_stages"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    stage_key = Column(String(100), nullable=False)
    stage_name = Column(String(255), nullable=False)
    stage_order = Column(Integer, nullable=False)


class ProjectContact(Base):
    __tablename__ = "project_contacts"
    __table_args__ = {"schema": "nexus_crm"}

    project_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.projects.id", ondelete="CASCADE"), primary_key=True)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.contacts.id", ondelete="CASCADE"), primary_key=True)
    relation_role = Column(String(50))


class ProjectProduct(Base):
    __tablename__ = "project_products"
    __table_args__ = {"schema": "nexus_crm"}

    project_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.projects.id", ondelete="CASCADE"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.products.id", ondelete="CASCADE"), primary_key=True)
    relation_type = Column(String(50))


# ── Phase 3: AI Layer ──────────────────────────────────────────

class StakeholderMap(Base):
    __tablename__ = "stakeholder_maps"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True))
    deal_id = Column(UUID(as_uuid=True))
    generated_by_agent_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StakeholderRelation(Base):
    __tablename__ = "stakeholder_relations"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.stakeholder_maps.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(UUID(as_uuid=True))
    reports_to_contact_id = Column(UUID(as_uuid=True))
    influence_level = Column(String(20))
    decision_role = Column(String(50))
    sentiment = Column(String(20))


class AIRelationshipScore(Base):
    __tablename__ = "ai_relationship_scores"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    target_type = Column(String(20), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    score = Column(Numeric(5, 2), nullable=False)
    trend = Column(String(20))
    computed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AIEnrichmentJob(Base):
    __tablename__ = "ai_enrichment_jobs"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    target_type = Column(String(20), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    source_channel = Column(String(50))
    status = Column(String(20), default="PENDING")
    enriched_fields_json = Column(JSONB)
    run_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AIMeetingBrief(Base):
    __tablename__ = "ai_meeting_briefs"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    activity_id = Column(UUID(as_uuid=True))
    contact_id = Column(UUID(as_uuid=True))
    company_id = Column(UUID(as_uuid=True))
    brief_text = Column(Text)
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    target_module = Column(String(50), nullable=False)
    target_record_id = Column(UUID(as_uuid=True), nullable=False)
    recommendation_type = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    rationale = Column(Text)
    confidence_score = Column(Numeric(5, 2))
    priority_score = Column(Numeric(5, 2))
    status = Column(String(50), default="OPEN")
    generated_by_agent_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    acted_at = Column(DateTime(timezone=True))
    acted_by = Column(UUID(as_uuid=True))


class AIForecast(Base):
    __tablename__ = "ai_forecasts"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    forecast_scope = Column(String(50), nullable=False)
    scope_record_id = Column(UUID(as_uuid=True))
    forecast_type = Column(String(100), nullable=False)
    forecast_period_start = Column(DateTime)
    forecast_period_end = Column(DateTime)
    forecast_value = Column(Numeric(18, 2))
    confidence_low = Column(Numeric(18, 2))
    confidence_high = Column(Numeric(18, 2))
    explanation = Column(Text)
    generated_by_agent_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Phase 4: Custom Field Engine ────────────────────────────────

class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    module_name = Column(String(50), nullable=False)
    field_key = Column(String(100), nullable=False)
    field_label = Column(String(255), nullable=False)
    field_type = Column(String(50), nullable=False)
    is_required = Column(Boolean, default=False)
    options_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    definition_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.custom_field_definitions.id", ondelete="CASCADE"), nullable=False)
    record_id = Column(UUID(as_uuid=True), nullable=False)
    value_text = Column(Text)
    value_number = Column(Numeric(18, 4))
    value_boolean = Column(Boolean)
    value_date = Column(DateTime)
    value_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ── Phase 5: Workflow Apps ──────────────────────────────────────

class WorkflowApp(Base):
    __tablename__ = "workflow_apps"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    target_module = Column(String(50))
    created_by = Column(UUID(as_uuid=True))
    status = Column(String(20), default="DRAFT")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WorkflowAppStep(Base):
    __tablename__ = "workflow_app_steps"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.workflow_apps.id", ondelete="CASCADE"), nullable=False)
    step_order = Column(Integer, nullable=False)
    step_type = Column(String(50), nullable=False)
    config_json = Column(JSONB)
    agent_id = Column(UUID(as_uuid=True))


class WorkflowAppRun(Base):
    __tablename__ = "workflow_app_runs"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.workflow_apps.id"))
    triggered_by = Column(UUID(as_uuid=True))
    input_data = Column(JSONB)
    output_data = Column(JSONB)
    status = Column(String(20), default="RUNNING")
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True))


# ── Phase 6: Shipping / Logistics ────────────────────────────

class TradeLane(Base):
    __tablename__ = "trade_lanes"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    origin_port = Column(String(100))
    destination_port = Column(String(100))
    transport_mode = Column(String(20))
    base_rate = Column(Numeric(18, 2))
    currency = Column(String(10))
    valid_from = Column(DateTime)
    valid_to = Column(DateTime)


class RateRequest(Base):
    __tablename__ = "rate_requests"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True))
    contact_id = Column(UUID(as_uuid=True))
    trade_lane_id = Column(UUID(as_uuid=True))
    cargo_description = Column(Text)
    requested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(String(50), default="OPEN")
    owner_user_id = Column(UUID(as_uuid=True))


class Quotation(Base):
    __tablename__ = "quotations"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    rate_request_id = Column(UUID(as_uuid=True))
    deal_id = Column(UUID(as_uuid=True))
    quote_number = Column(String(100))
    total_amount = Column(Numeric(18, 2))
    currency = Column(String(10))
    status = Column(String(50), default="DRAFT")
    valid_until = Column(DateTime)
    created_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class QuotationLineItem(Base):
    __tablename__ = "quotation_line_items"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quotation_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.quotations.id", ondelete="CASCADE"), nullable=False)
    charge_type = Column(String(100))
    description = Column(Text)
    unit_price = Column(Numeric(18, 2))
    quantity = Column(Numeric(18, 2))
    amount = Column(Numeric(18, 2))


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    project_id = Column(UUID(as_uuid=True))
    quotation_id = Column(UUID(as_uuid=True))
    shipment_number = Column(String(100))
    transport_mode = Column(String(20))
    origin_port = Column(String(100))
    destination_port = Column(String(100))
    etd = Column(DateTime)
    eta = Column(DateTime)
    status = Column(String(50), default="BOOKED")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ShipmentParty(Base):
    __tablename__ = "shipment_parties"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.shipments.id", ondelete="CASCADE"), nullable=False)
    party_role = Column(String(30), nullable=False)
    company_id = Column(UUID(as_uuid=True))
    contact_id = Column(UUID(as_uuid=True))
    notes = Column(Text)


class ShipmentDocument(Base):
    __tablename__ = "shipment_documents"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.shipments.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String(50))
    file_id = Column(UUID(as_uuid=True))
    uploaded_by = Column(UUID(as_uuid=True))
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CreditControlRule(Base):
    __tablename__ = "credit_control_rules"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True))
    credit_limit = Column(Numeric(18, 2))
    overdue_days_threshold = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)


class ARAgingSnapshot(Base):
    __tablename__ = "ar_aging_snapshots"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True))
    snapshot_date = Column(DateTime)
    current_amount = Column(Numeric(18, 2))
    overdue_30 = Column(Numeric(18, 2))
    overdue_60 = Column(Numeric(18, 2))
    overdue_90_plus = Column(Numeric(18, 2))


class CreditHold(Base):
    __tablename__ = "credit_holds"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True))
    shipment_id = Column(UUID(as_uuid=True))
    reason = Column(Text)
    held_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    released_at = Column(DateTime(timezone=True))
    released_by = Column(UUID(as_uuid=True))


class DispatchQueue(Base):
    __tablename__ = "dispatch_queue"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    company_id = Column(UUID(as_uuid=True))
    contact_id = Column(UUID(as_uuid=True))
    source_channel = Column(String(50))
    status = Column(String(50), default="PENDING")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DispatchAssignment(Base):
    __tablename__ = "dispatch_assignments"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.dispatch_queue.id", ondelete="CASCADE"), nullable=False)
    assigned_to = Column(UUID(as_uuid=True))
    assigned_by_rule_id = Column(UUID(as_uuid=True))
    score = Column(Numeric(5, 2))
    assigned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DispatchScoringLog(Base):
    __tablename__ = "dispatch_scoring_log"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("nexus_crm.dispatch_queue.id", ondelete="CASCADE"), nullable=False)
    candidate_user_id = Column(UUID(as_uuid=True))
    score = Column(Numeric(5, 2))
    score_factors_json = Column(JSONB)
    computed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AiDraft(Base):
    """AI-generated content awaiting user review (email_draft_review module)."""
    __tablename__ = "ai_drafts"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True))
    title = Column(Text, default="")
    content = Column(Text, default="")
    entity_type = Column(String(50), default="email")
    entity_id = Column(UUID(as_uuid=True))
    status = Column(String(50), default="pending_review")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Expense(Base):
    """Expense record awaiting approval/reimbursement (expense_reminders module)."""
    __tablename__ = "expenses"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True))
    title = Column(Text, default="")
    amount = Column(Numeric(18, 2), default=0)
    currency = Column(String(10), default="HKD")
    category = Column(String(50), default="other")
    expense_date = Column(DateTime(timezone=True))
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class PersonalNote(Base):
    """Personal reminder / memo (personal_reminders module)."""
    __tablename__ = "personal_notes"
    __table_args__ = {"schema": "nexus_crm"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True))
    title = Column(Text, default="")
    content = Column(Text, default="")
    remind_at = Column(DateTime(timezone=True))
    done = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

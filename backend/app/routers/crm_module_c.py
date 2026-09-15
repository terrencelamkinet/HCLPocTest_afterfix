from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.crm import Project
from app.models.crm_module_c import (
    ModuleRegistry, TenantModuleSetting, File,
    Role, Permission, RolePermission, UserRole,
    Department, Team, TeamMember,
    DepartmentTarget, UserTarget, DispatchRule,
    Activity, ActivityContact, ActivityCompany,
    CompanyIndustry, CompanyCountry, CompanyProductInUse,
    CompanyProductProposal, CompanyPartner,
    DealContact,
    ProjectStage, ProjectContact, ProjectProduct,
    StakeholderMap, StakeholderRelation,
    AIRelationshipScore, AIEnrichmentJob,
    AIMeetingBrief, AIRecommendation, AIForecast,
    CustomFieldDefinition, CustomFieldValue,
    WorkflowApp, WorkflowAppStep, WorkflowAppRun,
    TradeLane, RateRequest, Quotation, QuotationLineItem,
    Shipment, ShipmentParty, ShipmentDocument,
    CreditControlRule, ARAgingSnapshot, CreditHold,
    DispatchQueue, DispatchAssignment, DispatchScoringLog,
)
from app.schemas.crm_module_c import (
    ModuleRegistryOut, TenantModuleSettingOut, TenantModuleSettingUpsert,
    FileOut, RoleOut, RoleCreate, PermissionOut,
    DepartmentOut, DepartmentCreate, TeamOut, TeamCreate, TeamMemberOut,
    DepartmentTargetOut, DepartmentTargetCreate,
    UserTargetOut, UserTargetCreate,
    DispatchRuleOut, DispatchRuleCreate,
    ActivityOut, ActivityCreate,
    CompanyIndustryOut, CompanyCountryOut,
    CompanyProductInUseOut, CompanyPartnerOut,
    DealContactOut,
    ProjectStageOut, ProjectStageCreate,
    StakeholderMapOut, StakeholderMapCreate,
    StakeholderRelationOut, StakeholderRelationCreate,
    AIRelationshipScoreOut, AIRelationshipScoreCreate,
    AIEnrichmentJobOut, AIEnrichmentJobCreate,
    AIMeetingBriefOut, AIMeetingBriefCreate,
    AIRecommendationOut, AIRecommendationCreate,
    AIForecastOut, AIForecastCreate,
    CustomFieldDefinitionOut, CustomFieldDefinitionCreate,
    CustomFieldValueOut, CustomFieldValueUpsert,
    WorkflowAppOut, WorkflowAppCreate,
    WorkflowAppStepOut, WorkflowAppStepCreate,
    WorkflowAppRunOut,
    TradeLaneOut, TradeLaneCreate,
    RateRequestOut, RateRequestCreate,
    QuotationOut, QuotationCreate,
    ShipmentOut, ShipmentCreate,
    ShipmentPartyOut, ShipmentPartyCreate,
    DispatchQueueOut, DispatchQueueCreate,
    CreditControlRuleOut, CreditControlRuleCreate,
)

router = APIRouter(prefix="/api/v1/crm", tags=["crm-core"])


def _get_tenant_id(request: Request) -> UUID:
    if getattr(request.state, "auth_status", "") == "expired":
        raise HTTPException(status_code=401, detail="Token expired")
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(status_code=403, detail="Tenant not identified")
    return tid


# ── Module Registry ──

@router.get("/module-registry", response_model=list[ModuleRegistryOut])
async def list_registry(db: AsyncSession = Depends(get_tenant_session)):
    result = await db.execute(select(ModuleRegistry).order_by(ModuleRegistry.module_key))
    return list(result.scalars().all())


# ── Tenant Module Settings ──

@router.get("/tenant-module-settings", response_model=list[TenantModuleSettingOut])
async def list_tenant_settings(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TenantModuleSetting).where(TenantModuleSetting.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.put("/tenant-module-settings/{module_key}", response_model=TenantModuleSettingOut)
async def upsert_tenant_setting(
    module_key: str,
    body: TenantModuleSettingUpsert,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TenantModuleSetting).where(
            TenantModuleSetting.tenant_id == tenant_id,
            TenantModuleSetting.module_key == module_key,
        )
    )
    setting = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if setting:
        setting.is_enabled = body.is_enabled
        if body.is_enabled:
            setting.enabled_at = setting.enabled_at or now
            setting.disabled_at = None
        else:
            setting.disabled_at = now
    else:
        setting = TenantModuleSetting(
            tenant_id=tenant_id, module_key=module_key,
            is_enabled=body.is_enabled,
            enabled_at=now if body.is_enabled else None,
        )
        db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting


# ── Roles ──

@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Role).where(
            (Role.tenant_id == tenant_id) | (Role.is_system == True)
        )
    )
    return list(result.scalars().all())


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    role = Role(tenant_id=tenant_id, role_key=body.role_key, role_name=body.role_name)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


# ── Departments ──

@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Department).where(Department.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    body: DepartmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    dept = Department(
        tenant_id=tenant_id, name=body.name,
        code=body.code, parent_department_id=body.parent_department_id,
    )
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return dept


# ── Teams ──

@router.get("/teams", response_model=list[TeamOut])
async def list_teams(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Team).where(Team.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    team = Team(
        tenant_id=tenant_id, name=body.name,
        department_id=body.department_id, team_type=body.team_type,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


# ── Phase 2: Department Targets ──

@router.get("/department-targets", response_model=list[DepartmentTargetOut])
async def list_department_targets(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DepartmentTarget).where(DepartmentTarget.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/department-targets", response_model=DepartmentTargetOut, status_code=201)
async def create_department_target(
    body: DepartmentTargetCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = DepartmentTarget(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 2: User Targets ──

@router.get("/user-targets", response_model=list[UserTargetOut])
async def list_user_targets(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(UserTarget).where(UserTarget.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/user-targets", response_model=UserTargetOut, status_code=201)
async def create_user_target(
    body: UserTargetCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = UserTarget(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 2: Dispatch Rules ──

@router.get("/dispatch-rules", response_model=list[DispatchRuleOut])
async def list_dispatch_rules(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DispatchRule).where(DispatchRule.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/dispatch-rules", response_model=DispatchRuleOut, status_code=201)
async def create_dispatch_rule(
    body: DispatchRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = DispatchRule(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 2: Activities ──

@router.get("/activities", response_model=list[ActivityOut])
async def list_activities(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Activity).where(Activity.tenant_id == tenant_id)
        .order_by(Activity.activity_time.desc())
    )
    return list(result.scalars().all())


@router.post("/activities", response_model=ActivityOut, status_code=201)
async def create_activity(
    body: ActivityCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = Activity(
        tenant_id=tenant_id,
        activity_type=body.activity_type,
        reference_title=body.reference_title,
        activity_time=body.activity_time or datetime.now(timezone.utc),
        summary=body.summary,
        content=body.content,
        sentiment_score=body.sentiment_score,
        owner_user_id=body.owner_user_id,
    )
    db.add(obj)
    await db.flush()

    # Link contacts
    if body.contact_ids:
        for cid in body.contact_ids:
            db.add(ActivityContact(activity_id=obj.id, contact_id=cid))

    # Link companies
    if body.company_ids:
        for coid in body.company_ids:
            db.add(ActivityCompany(activity_id=obj.id, company_id=coid))

    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 2: Projects ──

@router.get("/project-stages", response_model=list[ProjectStageOut])
async def list_project_stages(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(ProjectStage).where(ProjectStage.tenant_id == tenant_id)
        .order_by(ProjectStage.stage_order)
    )
    return list(result.scalars().all())


@router.post("/project-stages", response_model=ProjectStageOut, status_code=201)
async def create_project_stage(
    body: ProjectStageCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = ProjectStage(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 2: Company linking ──

@router.get("/companies/{company_id}/industries", response_model=list[CompanyIndustryOut])
async def list_company_industries(
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(CompanyIndustry).where(CompanyIndustry.company_id == company_id)
    )
    return list(result.scalars().all())


@router.post("/companies/{company_id}/industries", status_code=201)
async def add_company_industry(
    company_id: UUID,
    body: CompanyIndustryOut,
    db: AsyncSession = Depends(get_tenant_session),
):
    obj = CompanyIndustry(company_id=company_id, industry_name=body.industry_name)
    db.add(obj)
    await db.commit()
    return obj


@router.get("/companies/{company_id}/countries", response_model=list[CompanyCountryOut])
async def list_company_countries(
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(CompanyCountry).where(CompanyCountry.company_id == company_id)
    )
    return list(result.scalars().all())


@router.get("/companies/{company_id}/products-in-use", response_model=list[CompanyProductInUseOut])
async def list_company_products(
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(CompanyProductInUse).where(CompanyProductInUse.company_id == company_id)
    )
    return list(result.scalars().all())


@router.get("/companies/{company_id}/partners", response_model=list[CompanyPartnerOut])
async def list_company_partners(
    company_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(CompanyPartner).where(CompanyPartner.company_id == company_id)
    )
    return list(result.scalars().all())


# ── Phase 2: Deal linking ──

@router.get("/deals/{deal_id}/contacts", response_model=list[DealContactOut])
async def list_deal_contacts(
    deal_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(DealContact).where(DealContact.deal_id == deal_id)
    )
    return list(result.scalars().all())


# ── Phase 3: Stakeholder Maps ──

@router.get("/stakeholder-maps", response_model=list[StakeholderMapOut])
async def list_stakeholder_maps(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(StakeholderMap).where(StakeholderMap.tenant_id == tenant_id)
        .order_by(StakeholderMap.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/stakeholder-maps", response_model=StakeholderMapOut, status_code=201)
async def create_stakeholder_map(
    body: StakeholderMapCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = StakeholderMap(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/stakeholder-maps/{map_id}/relations", response_model=list[StakeholderRelationOut])
async def list_stakeholder_relations(
    map_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(StakeholderRelation).where(StakeholderRelation.map_id == map_id)
    )
    return list(result.scalars().all())


@router.post("/stakeholder-maps/{map_id}/relations", response_model=StakeholderRelationOut, status_code=201)
async def create_stakeholder_relation(
    map_id: UUID,
    body: StakeholderRelationCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    obj = StakeholderRelation(map_id=map_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 3: Relationship Scores ──

@router.get("/ai-relationship-scores", response_model=list[AIRelationshipScoreOut])
async def list_ai_relationship_scores(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(AIRelationshipScore).where(AIRelationshipScore.tenant_id == tenant_id)
        .order_by(AIRelationshipScore.computed_at.desc())
    )
    return list(result.scalars().all())


@router.post("/ai-relationship-scores", response_model=AIRelationshipScoreOut, status_code=201)
async def create_ai_relationship_score(
    body: AIRelationshipScoreCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = AIRelationshipScore(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 3: Enrichment Jobs ──

@router.get("/ai-enrichment-jobs", response_model=list[AIEnrichmentJobOut])
async def list_ai_enrichment_jobs(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(AIEnrichmentJob).where(AIEnrichmentJob.tenant_id == tenant_id)
        .order_by(AIEnrichmentJob.run_at.desc())
    )
    return list(result.scalars().all())


@router.post("/ai-enrichment-jobs", response_model=AIEnrichmentJobOut, status_code=201)
async def create_ai_enrichment_job(
    body: AIEnrichmentJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = AIEnrichmentJob(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 3: Meeting Briefs ──

@router.get("/ai-meeting-briefs", response_model=list[AIMeetingBriefOut])
async def list_ai_meeting_briefs(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(AIMeetingBrief).where(AIMeetingBrief.tenant_id == tenant_id)
        .order_by(AIMeetingBrief.generated_at.desc())
    )
    return list(result.scalars().all())


@router.post("/ai-meeting-briefs", response_model=AIMeetingBriefOut, status_code=201)
async def create_ai_meeting_brief(
    body: AIMeetingBriefCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = AIMeetingBrief(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 3: Recommendations ──

@router.get("/ai-recommendations", response_model=list[AIRecommendationOut])
async def list_ai_recommendations(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(AIRecommendation).where(AIRecommendation.tenant_id == tenant_id)
        .order_by(AIRecommendation.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/ai-recommendations", response_model=AIRecommendationOut, status_code=201)
async def create_ai_recommendation(
    body: AIRecommendationCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = AIRecommendation(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.patch("/ai-recommendations/{rec_id}/status", response_model=AIRecommendationOut)
async def update_ai_recommendation_status(
    rec_id: UUID,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    rec = await db.get(AIRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if "status" in body:
        rec.status = body["status"]
    if body.get("status") in ("COMPLETED", "ACTED"):
        rec.acted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rec)
    return rec


# ── Phase 3: Forecasts ──

@router.get("/ai-forecasts", response_model=list[AIForecastOut])
async def list_ai_forecasts(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(AIForecast).where(AIForecast.tenant_id == tenant_id)
        .order_by(AIForecast.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/ai-forecasts", response_model=AIForecastOut, status_code=201)
async def create_ai_forecast(
    body: AIForecastCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = AIForecast(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj



# ── Phase 4: Custom Field Engine ──

@router.get("/custom-field-definitions", response_model=list[CustomFieldDefinitionOut])
async def list_custom_field_definitions(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(CustomFieldDefinition).where(CustomFieldDefinition.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/custom-field-definitions", response_model=CustomFieldDefinitionOut, status_code=201)
async def create_custom_field_definition(
    body: CustomFieldDefinitionCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = CustomFieldDefinition(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/custom-field-values/{module_name}/{record_id}", response_model=list[CustomFieldValueOut])
async def get_custom_field_values(
    module_name: str,
    record_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(CustomFieldValue)
        .join(CustomFieldDefinition, CustomFieldValue.definition_id == CustomFieldDefinition.id)
        .where(
            CustomFieldValue.tenant_id == tenant_id,
            CustomFieldValue.record_id == record_id,
            CustomFieldDefinition.module_name == module_name,
        )
    )
    return list(result.scalars().all())


@router.put("/custom-field-values/{definition_id}", response_model=CustomFieldValueOut)
async def upsert_custom_field_value(
    definition_id: UUID,
    body: CustomFieldValueUpsert,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(CustomFieldValue).where(
            CustomFieldValue.tenant_id == tenant_id,
            CustomFieldValue.definition_id == definition_id,
            CustomFieldValue.record_id == body.record_id,
        )
    )
    val = result.scalar_one_or_none()
    if val:
        val.value_text = body.value_text
        val.value_number = body.value_number
        val.value_boolean = body.value_boolean
        val.value_date = body.value_date
        val.value_json = body.value_json
    else:
        val = CustomFieldValue(
            tenant_id=tenant_id, definition_id=definition_id, **body.model_dump()
        )
        db.add(val)
    await db.commit()
    await db.refresh(val)
    return val


# ── Phase 5: Workflow Apps ──

@router.get("/workflow-apps", response_model=list[WorkflowAppOut])
async def list_workflow_apps(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(WorkflowApp).where(WorkflowApp.tenant_id == tenant_id)
        .order_by(WorkflowApp.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/workflow-apps", response_model=WorkflowAppOut, status_code=201)
async def create_workflow_app(
    body: WorkflowAppCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = WorkflowApp(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/workflow-apps/{app_id}/steps", response_model=list[WorkflowAppStepOut])
async def list_workflow_steps(
    app_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(WorkflowAppStep).where(WorkflowAppStep.app_id == app_id)
        .order_by(WorkflowAppStep.step_order)
    )
    return list(result.scalars().all())


@router.post("/workflow-apps/{app_id}/steps", response_model=WorkflowAppStepOut, status_code=201)
async def create_workflow_step(
    app_id: UUID,
    body: WorkflowAppStepCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    obj = WorkflowAppStep(app_id=app_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/workflow-apps/{app_id}/runs", response_model=list[WorkflowAppRunOut])
async def list_workflow_runs(
    app_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(WorkflowAppRun).where(WorkflowAppRun.app_id == app_id)
        .order_by(WorkflowAppRun.started_at.desc())
    )
    return list(result.scalars().all())


# ── Phase 6a: Trade Lanes & Rate Requests ──

@router.get("/trade-lanes", response_model=list[TradeLaneOut])
async def list_trade_lanes(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(TradeLane).where(TradeLane.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/trade-lanes", response_model=TradeLaneOut, status_code=201)
async def create_trade_lane(
    body: TradeLaneCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = TradeLane(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/rate-requests", response_model=list[RateRequestOut])
async def list_rate_requests(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(RateRequest).where(RateRequest.tenant_id == tenant_id)
        .order_by(RateRequest.requested_at.desc())
    )
    return list(result.scalars().all())


@router.post("/rate-requests", response_model=RateRequestOut, status_code=201)
async def create_rate_request(
    body: RateRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = RateRequest(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/quotations", response_model=list[QuotationOut])
async def list_quotations(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Quotation).where(Quotation.tenant_id == tenant_id)
        .order_by(Quotation.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/quotations", response_model=QuotationOut, status_code=201)
async def create_quotation(
    body: QuotationCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = Quotation(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 6b: Shipments ──

@router.get("/shipments", response_model=list[ShipmentOut])
async def list_shipments(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(Shipment).where(Shipment.tenant_id == tenant_id)
        .order_by(Shipment.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/shipments", response_model=ShipmentOut, status_code=201)
async def create_shipment(
    body: ShipmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = Shipment(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/shipments/{shipment_id}/parties", response_model=list[ShipmentPartyOut])
async def list_shipment_parties(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    result = await db.execute(
        select(ShipmentParty).where(ShipmentParty.shipment_id == shipment_id)
    )
    return list(result.scalars().all())


@router.post("/shipments/{shipment_id}/parties", response_model=ShipmentPartyOut, status_code=201)
async def create_shipment_party(
    shipment_id: UUID,
    body: ShipmentPartyCreate,
    db: AsyncSession = Depends(get_tenant_session),
):
    obj = ShipmentParty(shipment_id=shipment_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── Phase 6c: Dispatch & Credit Control ──

@router.get("/dispatch-queue", response_model=list[DispatchQueueOut])
async def list_dispatch_queue(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(DispatchQueue).where(DispatchQueue.tenant_id == tenant_id)
        .order_by(DispatchQueue.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/dispatch-queue", response_model=DispatchQueueOut, status_code=201)
async def create_dispatch_queue_item(
    body: DispatchQueueCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = DispatchQueue(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/credit-control-rules", response_model=list[CreditControlRuleOut])
async def list_credit_control_rules(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    result = await db.execute(
        select(CreditControlRule).where(CreditControlRule.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.post("/credit-control-rules", response_model=CreditControlRuleOut, status_code=201)
async def create_credit_control_rule(
    body: CreditControlRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _get_tenant_id(request)
    obj = CreditControlRule(tenant_id=tenant_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

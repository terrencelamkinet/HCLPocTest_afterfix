-- ============================================================================
-- 011_touchpoint_companies.sql — Touchpoint ↔ Company many-to-many (2026-09-09)
-- 用戶要求：一個 Touchpoint 可以 link 多間公司（e.g. 一個會有多個 vendor）
-- company_id（touchpoints 單一 FK）保留 = 主要公司（legacy + list/detail 主顯示）
-- ============================================================================

CREATE TABLE IF NOT EXISTS nexus_crm.touchpoint_companies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    touchpoint_id uuid NOT NULL REFERENCES nexus_crm.touchpoints(id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES nexus_crm.companies(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (touchpoint_id, company_id)
);

ALTER TABLE nexus_crm.touchpoint_companies ENABLE ROW LEVEL SECURITY;
CREATE POLICY touchpoint_companies_isolation ON nexus_crm.touchpoint_companies
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

CREATE INDEX idx_tpc_company ON nexus_crm.touchpoint_companies (company_id);
CREATE INDEX idx_tpc_touchpoint ON nexus_crm.touchpoint_companies (touchpoint_id);

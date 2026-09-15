-- ============================================================================
-- 021_fix_workspace_bootstrap_and_project_company.sql
-- 2026-09-11（用戶回報兩件事一次過修）
--
-- 症狀 A：喺 Project 頁建立公司 → HTTP 500；建立任務 → HTTP 500
-- 症狀 B：Project 一定要綁公司，冇公司就建立唔到
--
-- 根因（A）：tenant 冇任何 nexus_auth.workspaces row 時
--   → app/db.py 嘅 workspace 解析撈唔到 → request.state.workspace_id 冇 set
--   → 所有 workspace_id NOT NULL 嘅表（companies / contacts / tasks / projects /
--     notes / touchpoints / deals）嘅寫入全部撞 NotNullViolationError → 500。
--   GET 唔需要 workspace_id，所以 app 表面完全正常，只有「建立」死。
--   實測 36+ 個 tenant（Terrence Test / RAG Test / Marketplace Tester …）中招。
--
-- 根因（B）：nexus_crm.projects.company_id 係 NOT NULL。
--
-- 另外：nexus_admin（app DB user）對 nexus_auth.workspaces 只有 SELECT 冇 INSERT
--   → app/db.py 新加嘅「自動補 Default Workspace」需要 INSERT 權限。
-- ============================================================================

BEGIN;

-- 1) 為每個缺 workspace 嘅 tenant 補一個 system-generated default workspace
INSERT INTO nexus_auth.workspaces (tenant_id, name, is_system_generated)
SELECT t.id, 'Default Workspace', true
FROM nexus_auth.nexus_auth_tenants t
WHERE NOT EXISTS (
    SELECT 1 FROM nexus_auth.workspaces w WHERE w.tenant_id = t.id
);

-- 2) app DB user 需要 INSERT 權先可以自我補救（新 tenant / 賽跑情況）
GRANT INSERT ON nexus_auth.workspaces TO nexus_admin;

-- 3) Project 唔應該一定要綁公司
ALTER TABLE nexus_crm.projects ALTER COLUMN company_id DROP NOT NULL;

COMMIT;

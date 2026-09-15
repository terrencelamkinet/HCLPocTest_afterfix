-- 003_backfill_workspace.sql
-- Create default workspace for each tenant + backfill all existing records

BEGIN;

-- Step 1: Create default workspace for tenants that don't have one
INSERT INTO nexus_auth.workspaces (tenant_id, name, workspace_type, is_system_generated)
SELECT id, 'Default Workspace', 'default', true
FROM nexus_auth.nexus_auth_tenants t
WHERE NOT EXISTS (
  SELECT 1 FROM nexus_auth.workspaces w
  WHERE w.tenant_id = t.id AND w.workspace_type = 'default'
);

-- Step 2: Backfill workspace_id for all core tables
DO $$
DECLARE
    ws_record RECORD;
BEGIN
    FOR ws_record IN
        SELECT w.id AS ws_id, w.tenant_id
        FROM nexus_auth.workspaces w
        WHERE w.workspace_type = 'default'
    LOOP
        UPDATE nexus_crm.companies SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.contacts SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.projects SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.tasks SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.touchpoints SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.notes SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.deals SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
        
        UPDATE nexus_crm.activity_log SET workspace_id = ws_record.ws_id
        WHERE tenant_id = ws_record.tenant_id AND workspace_id IS NULL;
    END LOOP;
END $$;

-- Step 3: Now add NOT NULL constraints
ALTER TABLE nexus_crm.companies ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.contacts ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.projects ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.tasks ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.touchpoints ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.notes ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.deals ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE nexus_crm.activity_log ALTER COLUMN workspace_id SET NOT NULL;

COMMIT;

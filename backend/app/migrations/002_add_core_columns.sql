-- 002_add_core_columns.sql
-- Add workspace_id, team_id, visibility_scope, version to 8 core tables

BEGIN;

-- ====================================================================
-- Step 1: Add columns (nullable first, backfill later)
-- ====================================================================

ALTER TABLE nexus_crm.companies
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_companies_workspace ON nexus_crm.companies(workspace_id);

ALTER TABLE nexus_crm.contacts
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_contacts_workspace ON nexus_crm.contacts(workspace_id);

ALTER TABLE nexus_crm.projects
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_projects_workspace ON nexus_crm.projects(workspace_id);

ALTER TABLE nexus_crm.tasks
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON nexus_crm.tasks(workspace_id);

ALTER TABLE nexus_crm.touchpoints
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_touchpoints_workspace ON nexus_crm.touchpoints(workspace_id);

ALTER TABLE nexus_crm.notes
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_notes_workspace ON nexus_crm.notes(workspace_id);

ALTER TABLE nexus_crm.deals
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_deals_workspace ON nexus_crm.deals(workspace_id);

ALTER TABLE nexus_crm.activity_log
  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES nexus_auth.workspaces(id),
  ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES nexus_crm.teams(id),
  ADD COLUMN IF NOT EXISTS visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_activity_log_workspace ON nexus_crm.activity_log(workspace_id);

COMMIT;

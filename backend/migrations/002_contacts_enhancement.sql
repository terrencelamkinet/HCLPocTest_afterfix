-- ============================================================
-- NEXUS CRM — Contacts Enhancement Migration
-- Adds extended contact fields + contact<->project junction table
-- ============================================================

BEGIN;

-- ============================================================
-- 1. Add new columns to nexus_crm.contacts
-- ============================================================

ALTER TABLE nexus_crm.contacts
    ADD COLUMN IF NOT EXISTS chinese_name   TEXT,
    ADD COLUMN IF NOT EXISTS nick_name      TEXT,
    ADD COLUMN IF NOT EXISTS contact_type   TEXT,
    ADD COLUMN IF NOT EXISTS grade          TEXT,
    ADD COLUMN IF NOT EXISTS numbers        TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS office_phone   TEXT,
    ADD COLUMN IF NOT EXISTS namecard_path  TEXT;

-- ============================================================
-- 2. Create contact_projects junction table
-- ============================================================

CREATE TABLE nexus_crm.contact_projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    contact_id      UUID NOT NULL REFERENCES nexus_crm.contacts(id) ON DELETE CASCADE,
    project_id      UUID NOT NULL REFERENCES nexus_crm.deals(id) ON DELETE CASCADE,
    role            TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(contact_id, project_id)
);

-- ============================================================
-- 3. Indexes
-- ============================================================

CREATE INDEX idx_contacts_chinese_name ON nexus_crm.contacts(chinese_name);
CREATE INDEX idx_contacts_contact_type ON nexus_crm.contacts(contact_type);
CREATE INDEX idx_contacts_grade ON nexus_crm.contacts(grade);

CREATE INDEX idx_contact_projects_tenant ON nexus_crm.contact_projects(tenant_id);
CREATE INDEX idx_contact_projects_contact ON nexus_crm.contact_projects(contact_id);
CREATE INDEX idx_contact_projects_project ON nexus_crm.contact_projects(project_id);

-- ============================================================
-- 4. Row Level Security — contact_projects
-- ============================================================

ALTER TABLE nexus_crm.contact_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.contact_projects FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_contact_projects ON nexus_crm.contact_projects
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- ============================================================
-- 5. GRANTs for the new table
-- ============================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_crm.contact_projects TO nexus_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA nexus_crm TO nexus_app;

COMMIT;

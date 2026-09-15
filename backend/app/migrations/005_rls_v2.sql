-- ===========================================================================
-- §4-5 RLS V2 Rollout — Phase 1: 10 core tables
--
-- Prerequisites (already done in db.py / P0):
--   - get_tenant_session() sets app.tenant_id, app.user_id via set_config
--   - rls_audit_log table exists in nexus_crm
--
-- ⚠️ PG default: table owner bypasses RLS.
--    App uses gg_fighter (owner) as connection user.
--    FORCE ROW LEVEL SECURITY is MANDATORY to enforce RLS on owner.
--
-- Strategy:
--   1. Enable RLS on core tables
--   2. Create tenant_isolation policy (full enforcement via USING)
--   3. FORCE ROW LEVEL SECURITY — makes RLS apply to table owner too
--   4. Create BEFORE INSERT/UPDATE trigger for shadow logging
--      (catches cross-tenant writes that slip through RLS)
--   5. Drop old duplicate policies from previous shadow attempt
-- ===========================================================================

-- -----------------------------------------------------------------------
-- Helper: shadow-logging function
-- Invoked by BEFORE triggers on each table when a write crosses tenant
-- boundaries.  Logs to rls_audit_log for daily audit.
-- -----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nexus_crm.rls_check_violation()
RETURNS trigger AS $$
DECLARE
    _tid text;
    _uid text;
BEGIN
    _tid := current_setting('app.tenant_id', true);
    _uid := current_setting('app.user_id', true);

    IF NEW.tenant_id IS DISTINCT FROM NULLIF(_tid, '')::uuid THEN
        INSERT INTO nexus_crm.rls_audit_log(
            table_name, operation, tenant_id, user_id, record_id,
            v1_allowed, v2_blocked, detail
        ) VALUES (
            TG_TABLE_NAME, TG_OP,
            NEW.tenant_id,
            NULLIF(_uid, '')::uuid,
            NEW.id,
            true,   -- v1_allowed — the write reached PG
            false,  -- v2_blocked — RLS should have blocked but didn't
            jsonb_build_object(
                'expected_tenant', COALESCE(_tid, '(null)'),
                'actual_tenant',   NEW.tenant_id::text,
                'user_id',         COALESCE(_uid, '(null)'),
                'trigger_when',    TG_WHEN,
                'trigger_op',      TG_OP
            )
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------
-- Phase 1a — Core CRM tables (companies, contacts, deals, projects, tasks)
-- -----------------------------------------------------------------------

-- 1. companies
ALTER TABLE nexus_crm.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.companies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.companies;
DROP POLICY IF EXISTS tenant_isolation_companies ON nexus_crm.companies;
DROP POLICY IF EXISTS v2_shadow_companies ON nexus_crm.companies;
CREATE POLICY tenant_isolation ON nexus_crm.companies
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_companies
    BEFORE INSERT OR UPDATE ON nexus_crm.companies
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

COMMENT ON POLICY tenant_isolation ON nexus_crm.companies IS
    'RLS V2: tenant-scoped isolation via app.tenant_id — FORCE applied';

-- 2. contacts
ALTER TABLE nexus_crm.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.contacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.contacts;
DROP POLICY IF EXISTS tenant_isolation_contacts ON nexus_crm.contacts;
DROP POLICY IF EXISTS v2_shadow_contacts ON nexus_crm.contacts;
CREATE POLICY tenant_isolation ON nexus_crm.contacts
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_contacts
    BEFORE INSERT OR UPDATE ON nexus_crm.contacts
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 3. deals
ALTER TABLE nexus_crm.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.deals;
DROP POLICY IF EXISTS tenant_isolation_deals ON nexus_crm.deals;
DROP POLICY IF EXISTS v2_shadow_deals ON nexus_crm.deals;
CREATE POLICY tenant_isolation ON nexus_crm.deals
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_deals
    BEFORE INSERT OR UPDATE ON nexus_crm.deals
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 4. projects
ALTER TABLE nexus_crm.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.projects;
DROP POLICY IF EXISTS tenant_isolation_projects ON nexus_crm.projects;
DROP POLICY IF EXISTS v2_shadow_projects ON nexus_crm.projects;
CREATE POLICY tenant_isolation ON nexus_crm.projects
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_projects
    BEFORE INSERT OR UPDATE ON nexus_crm.projects
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 5. tasks
ALTER TABLE nexus_crm.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.tasks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.tasks;
DROP POLICY IF EXISTS tenant_isolation_tasks ON nexus_crm.tasks;
DROP POLICY IF EXISTS v2_shadow_tasks ON nexus_crm.tasks;
CREATE POLICY tenant_isolation ON nexus_crm.tasks
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_tasks
    BEFORE INSERT OR UPDATE ON nexus_crm.tasks
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- -----------------------------------------------------------------------
-- Phase 1b — Activity & Communication tables
-- -----------------------------------------------------------------------

-- 6. activities
ALTER TABLE nexus_crm.activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.activities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.activities;
DROP POLICY IF EXISTS tenant_isolation_activities ON nexus_crm.activities;
DROP POLICY IF EXISTS v2_shadow_activities ON nexus_crm.activities;
CREATE POLICY tenant_isolation ON nexus_crm.activities
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_activities
    BEFORE INSERT OR UPDATE ON nexus_crm.activities
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 7. touchpoints
ALTER TABLE nexus_crm.touchpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.touchpoints FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.touchpoints;
DROP POLICY IF EXISTS tenant_isolation_touchpoints ON nexus_crm.touchpoints;
DROP POLICY IF EXISTS v2_shadow_touchpoints ON nexus_crm.touchpoints;
CREATE POLICY tenant_isolation ON nexus_crm.touchpoints
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_touchpoints
    BEFORE INSERT OR UPDATE ON nexus_crm.touchpoints
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 8. notes
ALTER TABLE nexus_crm.notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.notes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.notes;
DROP POLICY IF EXISTS tenant_isolation_notes ON nexus_crm.notes;
DROP POLICY IF EXISTS v2_shadow_notes ON nexus_crm.notes;
CREATE POLICY tenant_isolation ON nexus_crm.notes
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_notes
    BEFORE INSERT OR UPDATE ON nexus_crm.notes
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 9. name_cards
ALTER TABLE nexus_crm.name_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.name_cards FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.name_cards;
DROP POLICY IF EXISTS tenant_isolation_name_cards ON nexus_crm.name_cards;
DROP POLICY IF EXISTS v2_shadow_name_cards ON nexus_crm.name_cards;
CREATE POLICY tenant_isolation ON nexus_crm.name_cards
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_name_cards
    BEFORE INSERT OR UPDATE ON nexus_crm.name_cards
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- 10. files
ALTER TABLE nexus_crm.files ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.files FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.files;
DROP POLICY IF EXISTS tenant_isolation_files ON nexus_crm.files;
DROP POLICY IF EXISTS v2_shadow_files ON nexus_crm.files;
CREATE POLICY tenant_isolation ON nexus_crm.files
    FOR ALL
    USING (tenant_id::text = current_setting('app.tenant_id'));
CREATE TRIGGER trg_rls_check_files
    BEFORE INSERT OR UPDATE ON nexus_crm.files
    FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();

-- ===========================================================================
-- Verify
-- ===========================================================================

-- Check all applied policies
SELECT schemaname, tablename, policyname, cmd, qual
FROM pg_policies
WHERE schemaname = 'nexus_crm'
  AND tablename IN ('companies','contacts','deals','projects','tasks',
                     'activities','touchpoints','notes','name_cards','files')
ORDER BY tablename, policyname;

-- ============================================================================
-- 018_note_link_dismissals.sql
-- Notes V2 (T3.3) — rule-based link suggestions: remember dismissed suggestions
-- so they never pop up again for the same note + record (SPEC acceptance #11).
--
-- Additive module: new tenant-scoped table with the same RLS / trigger / grants
-- pattern as nexus_crm.notes and the other Notes v2 tables (017).
-- ============================================================================

CREATE TABLE IF NOT EXISTS nexus_crm.note_link_dismissals (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    note_id     uuid NOT NULL REFERENCES nexus_crm.notes(id) ON DELETE CASCADE,
    entity_type text NOT NULL,
    entity_id   uuid,
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_note_link_dismissals_tenant ON nexus_crm.note_link_dismissals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_note_link_dismissals_note   ON nexus_crm.note_link_dismissals(note_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_note_link_dismissals
    ON nexus_crm.note_link_dismissals(note_id, entity_type, entity_id);

DO $$
BEGIN
    ALTER TABLE nexus_crm.note_link_dismissals ENABLE ROW LEVEL SECURITY;
    ALTER TABLE nexus_crm.note_link_dismissals FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.note_link_dismissals;
    CREATE POLICY tenant_isolation ON nexus_crm.note_link_dismissals
        USING ((tenant_id)::text = current_setting('app.tenant_id'::text, true))
        WITH CHECK ((tenant_id)::text = current_setting('app.tenant_id'::text, true));
    DROP TRIGGER IF EXISTS trg_rls_check_note_link_dismissals ON nexus_crm.note_link_dismissals;
    CREATE TRIGGER trg_rls_check_note_link_dismissals BEFORE INSERT OR UPDATE
        ON nexus_crm.note_link_dismissals
        FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
        ON nexus_crm.note_link_dismissals TO gg_fighter, nexus_app;
    GRANT SELECT ON nexus_crm.note_link_dismissals TO nexus_briefing, nexus_admin;
END $$;

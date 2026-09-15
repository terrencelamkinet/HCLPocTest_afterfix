-- ============================================================================
-- 019_notes_soft_delete_and_revisions.sql
-- Notes V2 — Stage B/C（2026-09-11）
--   B) T-04 soft delete：notes.deleted_at + 部分索引，支援撤銷（undo）
--   C) T-03 revision history：nexus_crm.note_revisions 快照表
--   （T-02 樂觀鎖唔需要 DDL — nexus_crm.notes.version 早已存在，default 1）
--
-- 全部 additive，跟返 017/018 嘅 RLS / trigger / grants pattern。
-- ============================================================================

-- ── B) Soft delete ──────────────────────────────────────────────────────────
ALTER TABLE nexus_crm.notes ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

-- 絕大部分 query 都係「未刪嘅我嘅筆記」→ 用部分索引，唔好 index 全表
CREATE INDEX IF NOT EXISTS idx_notes_owner_live
    ON nexus_crm.notes(tenant_id, created_by, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_notes_notebook_live
    ON nexus_crm.notes(notebook_id)
    WHERE deleted_at IS NULL;

-- 已刪嘅要搵返出嚟 restore / purge → 細索引
CREATE INDEX IF NOT EXISTS idx_notes_deleted
    ON nexus_crm.notes(tenant_id, created_by, deleted_at)
    WHERE deleted_at IS NOT NULL;

-- ── C) Revision history ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nexus_crm.note_revisions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    note_id     uuid NOT NULL REFERENCES nexus_crm.notes(id) ON DELETE CASCADE,
    version     integer NOT NULL,
    title       text,
    content     text,
    created_by  uuid,
    created_at  timestamptz DEFAULT now(),
    UNIQUE (note_id, version)
);

CREATE INDEX IF NOT EXISTS idx_note_revisions_tenant ON nexus_crm.note_revisions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_note_revisions_note
    ON nexus_crm.note_revisions(note_id, version DESC);

DO $$
BEGIN
    ALTER TABLE nexus_crm.note_revisions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE nexus_crm.note_revisions FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.note_revisions;
    CREATE POLICY tenant_isolation ON nexus_crm.note_revisions
        USING ((tenant_id)::text = current_setting('app.tenant_id'::text, true))
        WITH CHECK ((tenant_id)::text = current_setting('app.tenant_id'::text, true));
    DROP TRIGGER IF EXISTS trg_rls_check_note_revisions ON nexus_crm.note_revisions;
    CREATE TRIGGER trg_rls_check_note_revisions BEFORE INSERT OR UPDATE
        ON nexus_crm.note_revisions
        FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
        ON nexus_crm.note_revisions TO gg_fighter, nexus_app;
    GRANT SELECT ON nexus_crm.note_revisions TO nexus_briefing, nexus_admin;
END $$;

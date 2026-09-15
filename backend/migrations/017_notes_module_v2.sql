-- 017_notes_module_v2.sql — Notes module v2 資料層（2026-09-11）
-- SPEC: docs/notes-module-v2-SPEC.md（Q1A 分 3 期 / Q2A note_links / Q4A 重用 tags / Q6B 私人筆記）
--
-- 全部新表跟 nexus_crm.notes 現有 pattern：tenant_id + FORCE RLS tenant_isolation
-- + rls_check_violation trigger + 同款 grants（唔自創隔離方式）。
-- 一個 note 只屬一個 notebook；刪 notebook 唔會刪 note（ON DELETE SET NULL）。

CREATE TABLE IF NOT EXISTS nexus_crm.notebooks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    owner_user_id uuid REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    name text NOT NULL,
    color text NOT NULL DEFAULT 'blue',
    visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'private',
    team_id uuid,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notebooks_tenant ON nexus_crm.notebooks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notebooks_owner ON nexus_crm.notebooks(owner_user_id);

ALTER TABLE nexus_crm.notes
    ADD COLUMN IF NOT EXISTS notebook_id uuid REFERENCES nexus_crm.notebooks(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS template_id uuid;
CREATE INDEX IF NOT EXISTS idx_notes_notebook ON nexus_crm.notes(notebook_id);

-- Note ↔ 任何 CRM record（contact/company/project/task/touchpoint）— 可多對多
CREATE TABLE IF NOT EXISTS nexus_crm.note_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    note_id uuid NOT NULL REFERENCES nexus_crm.notes(id) ON DELETE CASCADE,
    entity_type text NOT NULL,
    entity_id uuid,
    label text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_note_links_tenant ON nexus_crm.note_links(tenant_id);
CREATE INDEX IF NOT EXISTS idx_note_links_note ON nexus_crm.note_links(note_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_note_links ON nexus_crm.note_links(note_id, entity_type, entity_id);

-- Note ↔ Tag（重用現有 nexus_crm.tags，唔另起 tag 系統）
CREATE TABLE IF NOT EXISTS nexus_crm.note_tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    note_id uuid NOT NULL REFERENCES nexus_crm.notes(id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES nexus_crm.tags(id) ON DELETE CASCADE,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_note_tags_tenant ON nexus_crm.note_tags(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_note_tags ON nexus_crm.note_tags(note_id, tag_id);

-- 範本：is_system = true 為內建 12 款（全 tenant 共用），false = team 自訂
CREATE TABLE IF NOT EXISTS nexus_crm.note_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name text NOT NULL,
    category text,
    team_id uuid,
    is_system boolean NOT NULL DEFAULT false,
    blocks_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    suggested_link_types text[],
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_note_templates_tenant ON nexus_crm.note_templates(tenant_id);

-- RLS + trigger + grants：一次過套落 4 張新表（跟 nexus_crm.notes 同款）
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['notebooks', 'note_links', 'note_tags', 'note_templates'] LOOP
        EXECUTE format('ALTER TABLE nexus_crm.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE nexus_crm.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON nexus_crm.%I '
            'USING ((tenant_id)::text = current_setting(''app.tenant_id''::text, true)) '
            'WITH CHECK ((tenant_id)::text = current_setting(''app.tenant_id''::text, true))', t);
        EXECUTE format('DROP TRIGGER IF EXISTS trg_rls_check_%I ON nexus_crm.%I', t, t);
        EXECUTE format(
            'CREATE TRIGGER trg_rls_check_%I BEFORE INSERT OR UPDATE ON nexus_crm.%I '
            'FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation()', t, t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON nexus_crm.%I TO gg_fighter, nexus_app', t);
        EXECUTE format('GRANT SELECT ON nexus_crm.%I TO nexus_briefing, nexus_admin', t);
    END LOOP;
END $$;

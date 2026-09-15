-- ============================================================================
-- 020_user_preferences.sql
-- Notes V2 Stage D (T-14) — per-user preferences（highlight 自訂色等跨裝置同步）
--
-- Review T-14 指 highlight 自訂色只存 localStorage（換機／清 cache 就冇）。
-- 呢個表做一個 key/value 使用者偏好 store；RLS 跟 017/018/019 pattern。
-- 注意：RLS 係 tenant 級，per-user 隔離由 PK(tenant_id,user_id,key) + app 層
-- `user_id = :u` filter 保證（同 notes 一樣，app 層做 author-only）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS nexus_crm.user_preferences (
    tenant_id  uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE CASCADE,
    key        text NOT NULL,
    value      jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_user
    ON nexus_crm.user_preferences(tenant_id, user_id);

DO $$
BEGIN
    ALTER TABLE nexus_crm.user_preferences ENABLE ROW LEVEL SECURITY;
    ALTER TABLE nexus_crm.user_preferences FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.user_preferences;
    CREATE POLICY tenant_isolation ON nexus_crm.user_preferences
        USING ((tenant_id)::text = current_setting('app.tenant_id'::text, true))
        WITH CHECK ((tenant_id)::text = current_setting('app.tenant_id'::text, true));
    DROP TRIGGER IF EXISTS trg_rls_check_user_preferences ON nexus_crm.user_preferences;
    CREATE TRIGGER trg_rls_check_user_preferences BEFORE INSERT OR UPDATE
        ON nexus_crm.user_preferences
        FOR EACH ROW EXECUTE FUNCTION nexus_crm.rls_check_violation();
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
        ON nexus_crm.user_preferences TO gg_fighter, nexus_app;
    GRANT SELECT ON nexus_crm.user_preferences TO nexus_briefing, nexus_admin;
END $$;

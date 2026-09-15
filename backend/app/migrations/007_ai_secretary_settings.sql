-- ============================================================================
-- Migration 007: AI Secretary Settings + Channel Credentials
--
-- Per-user AI assistant settings (1 user = 1 row, UNIQUE user_id).
-- Replaces the frontend localStorage keys:
--   nexus-secretary-settings / nexus-working-hours / nexus-greeting-slots
--
-- RLS strategy (50k concurrent users):
--   - Policy checks BOTH app.user_id AND app.tenant_id (set by
--     get_tenant_session() via set_config, transaction-scoped).
--   - FORCE ROW LEVEL SECURITY — app connects as table owner (gg_fighter),
--     so FORCE is MANDATORY or RLS would be bypassed for the owner.
--   - user_id UNIQUE index gives O(1) lookup per user.
-- ============================================================================

-- ── ai_secretary_settings ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nexus_ai.ai_secretary_settings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL UNIQUE
                    REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL
                    REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,

    -- nexus-secretary-settings
    modules         JSONB NOT NULL DEFAULT '["weather","today_tasks","meetings","project_status","hot_leads","stale_deals"]',
    workdays        JSONB NOT NULL DEFAULT '["mon","tue","wed","thu","fri"]',
    weekend_mute    BOOLEAN NOT NULL DEFAULT true,
    strict_silence  BOOLEAN NOT NULL DEFAULT true,
    tone            VARCHAR(20) NOT NULL DEFAULT 'professional'
                    CHECK (tone IN ('professional','friendly','direct','encouraging','formal')),
    instructions    TEXT NOT NULL DEFAULT '',
    lang_pref       VARCHAR(10) NOT NULL DEFAULT 'zh-HK'
                    CHECK (lang_pref IN ('zh-HK','zh-TW','en')),
    detail_level    SMALLINT NOT NULL DEFAULT 2 CHECK (detail_level BETWEEN 1 AND 3),
    channels        JSONB NOT NULL DEFAULT '{
                        "whatsapp": {"connected": false, "enabled": false},
                        "telegram": {"connected": false, "enabled": false},
                        "email":    {"connected": false, "enabled": false},
                        "sms":      {"connected": false, "enabled": false}
                    }',

    -- nexus-working-hours
    work_start      TIME NOT NULL DEFAULT '09:00',
    work_end        TIME NOT NULL DEFAULT '18:00',

    -- nexus-greeting-slots (user-overridable)
    greeting_slots  JSONB NOT NULL DEFAULT '[
                        {"key":"morning","emoji":"🌅","start":"05:00"},
                        {"key":"afternoon","emoji":"☀️","start":"12:00"},
                        {"key":"evening","emoji":"🌆","start":"18:00"},
                        {"key":"lateNight","emoji":"🌙","start":"23:00"}
                    ]',

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_settings_tenant ON nexus_ai.ai_secretary_settings(tenant_id);

-- ── ai_channel_credentials (reserved for future OAuth flows) ─────────────────
CREATE TABLE IF NOT EXISTS nexus_ai.ai_channel_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL
                    REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL
                    REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    channel         VARCHAR(20) NOT NULL
                    CHECK (channel IN ('whatsapp','telegram','email','sms')),
    access_token    TEXT,               -- encrypted at application level
    refresh_token   TEXT,
    external_id     VARCHAR(255),       -- telegram chat_id / whatsapp phone_number_id
    connected_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_user_channel UNIQUE (user_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_channel_creds_tenant ON nexus_ai.ai_channel_credentials(tenant_id);

-- ── updated_at trigger ───────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION nexus_ai.trg_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at ON nexus_ai.ai_secretary_settings;
CREATE TRIGGER set_updated_at
BEFORE UPDATE ON nexus_ai.ai_secretary_settings
FOR EACH ROW EXECUTE FUNCTION nexus_ai.trg_set_updated_at();

-- ── RLS ──────────────────────────────────────────────────────────────────────
ALTER TABLE nexus_ai.ai_secretary_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_ai.ai_secretary_settings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_isolation_settings ON nexus_ai.ai_secretary_settings;
CREATE POLICY user_isolation_settings ON nexus_ai.ai_secretary_settings
    FOR ALL
    USING (
        user_id = (current_setting('app.user_id', true))::uuid
        AND tenant_id = (current_setting('app.tenant_id', true))::uuid
    )
    WITH CHECK (
        user_id = (current_setting('app.user_id', true))::uuid
        AND tenant_id = (current_setting('app.tenant_id', true))::uuid
    );

ALTER TABLE nexus_ai.ai_channel_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_ai.ai_channel_credentials FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_isolation_channels ON nexus_ai.ai_channel_credentials;
CREATE POLICY user_isolation_channels ON nexus_ai.ai_channel_credentials
    FOR ALL
    USING (
        user_id = (current_setting('app.user_id', true))::uuid
        AND tenant_id = (current_setting('app.tenant_id', true))::uuid
    )
    WITH CHECK (
        user_id = (current_setting('app.user_id', true))::uuid
        AND tenant_id = (current_setting('app.tenant_id', true))::uuid
    );

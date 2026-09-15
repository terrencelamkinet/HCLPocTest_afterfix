-- ============================================================================
-- 009_namecard_v2.sql
-- NameCard Module V2: adds tags, AI field-confidence, duplicate-candidate
-- columns to name_cards, and a dedicated namecard_tags table so the
-- Gallery / Bulk Upload / Tag Management pages can be integrated.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) NameCard new columns (idempotent)
-- ---------------------------------------------------------------------------
ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb;

ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS field_confidence JSONB DEFAULT '{}'::jsonb;

ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS duplicate_candidate JSONB;

-- Index for tag containment lookups (Gallery tag filter).
CREATE INDEX IF NOT EXISTS idx_name_cards_tags
    ON nexus_crm.name_cards USING gin (tags);

-- ---------------------------------------------------------------------------
-- 2) namecard_tags table — dedicated NameCard tag definitions
--    (label + color + usage tracking)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nexus_crm.namecard_tags (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    color       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_namecard_tags_tenant
    ON nexus_crm.namecard_tags (tenant_id);

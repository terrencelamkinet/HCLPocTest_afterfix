-- ============================================================
-- NEXUS CRM — Migration 003: Task Enhancements + Custom Field Engine
-- 
-- 1. Add native fields to tasks (parent_task_id, recurring, area)
-- 2. Upgrade custom_field_definitions (add display_order, section, etc.)
-- 3. Fix ownership + RLS on custom field tables
-- 4. Seed Terrence's custom field definitions
-- ============================================================

BEGIN;

-- ============================================================
-- 1. TASKS — New Native Columns
-- ============================================================

ALTER TABLE nexus_crm.tasks
    ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES nexus_crm.tasks(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS recurring      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS area           TEXT;

-- Indexes for new columns
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON nexus_crm.tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_area   ON nexus_crm.tasks(area);


-- ============================================================
-- 2. CUSTOM FIELD DEFINITIONS — Upgrade (add missing columns)
-- ============================================================

ALTER TABLE nexus_crm.custom_field_definitions
    ADD COLUMN IF NOT EXISTS display_order   INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS section         VARCHAR(100),
    ADD COLUMN IF NOT EXISTS is_searchable   BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS default_value   TEXT,
    ADD COLUMN IF NOT EXISTS description     TEXT,
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_custom_field_defs_order 
    ON nexus_crm.custom_field_definitions(tenant_id, module_name, display_order);


-- ============================================================
-- 3. CUSTOM FIELD VALUES — Better indexes + type fix
-- ============================================================

-- value_date should support full timestamptz for datetime fields
ALTER TABLE nexus_crm.custom_field_values 
    ALTER COLUMN value_date TYPE TIMESTAMPTZ USING value_date::TIMESTAMPTZ;

-- Composite index for "fetch all custom fields for this record"
CREATE INDEX IF NOT EXISTS idx_custom_field_vals_record_lookup 
    ON nexus_crm.custom_field_values(tenant_id, module_name, record_id);

-- Index for searchable text fields
CREATE INDEX IF NOT EXISTS idx_custom_field_vals_text_search
    ON nexus_crm.custom_field_values USING gin(to_tsvector('simple', coalesce(value_text, '')))
    WHERE value_text IS NOT NULL;


-- ============================================================
-- 4. Fix Ownership — ensure gg_fighter owns all nexus_crm tables
-- ============================================================

DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN 
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'nexus_crm' 
          AND tableowner = 'postgres'
    LOOP
        EXECUTE format('ALTER TABLE nexus_crm.%I OWNER TO gg_fighter;', tbl);
    END LOOP;
END $$;


-- ============================================================
-- 5. RLS — custom_field_definitions + custom_field_values
-- ============================================================

ALTER TABLE nexus_crm.custom_field_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.custom_field_definitions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_custom_field_defs ON nexus_crm.custom_field_definitions;
CREATE POLICY tenant_isolation_custom_field_defs ON nexus_crm.custom_field_definitions
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.custom_field_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.custom_field_values FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_custom_field_vals ON nexus_crm.custom_field_values;
CREATE POLICY tenant_isolation_custom_field_vals ON nexus_crm.custom_field_values
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);


-- ============================================================
-- 6. GRANTs
-- ============================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_crm.custom_field_definitions TO nexus_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_crm.custom_field_values TO nexus_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA nexus_crm TO nexus_app;


-- ============================================================
-- 7. API — Custom Fields CRUD Functions (for backend use)
-- ============================================================

-- Bulk fetch all custom fields for a set of records in one query
CREATE OR REPLACE FUNCTION nexus_crm.get_custom_fields(
    p_tenant_id UUID,
    p_module    TEXT,
    p_record_ids UUID[]
) RETURNS TABLE(
    record_id   UUID,
    field_key   TEXT,
    field_label TEXT,
    field_type  TEXT,
    value_text  TEXT,
    value_number NUMERIC,
    value_boolean BOOLEAN,
    value_date  TIMESTAMPTZ,
    value_json  JSONB
) LANGUAGE SQL STABLE AS $$
    SELECT 
        v.record_id,
        d.field_key,
        d.field_label,
        d.field_type,
        v.value_text,
        v.value_number,
        v.value_boolean,
        v.value_date,
        v.value_json
    FROM nexus_crm.custom_field_values v
    JOIN nexus_crm.custom_field_definitions d ON d.id = v.definition_id
    WHERE v.tenant_id = p_tenant_id
      AND d.module_name = p_module
      AND v.record_id = ANY(p_record_ids)
    ORDER BY d.display_order, d.field_key;
$$;

-- Upsert a custom field value (insert or update)
CREATE OR REPLACE FUNCTION nexus_crm.upsert_custom_field_value(
    p_tenant_id     UUID,
    p_definition_id UUID,
    p_record_id     UUID,
    p_value_text    TEXT DEFAULT NULL,
    p_value_number  NUMERIC DEFAULT NULL,
    p_value_boolean BOOLEAN DEFAULT NULL,
    p_value_date    TIMESTAMPTZ DEFAULT NULL,
    p_value_json    JSONB DEFAULT NULL
) RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO nexus_crm.custom_field_values 
        (tenant_id, definition_id, record_id, value_text, value_number, value_boolean, value_date, value_json)
    VALUES 
        (p_tenant_id, p_definition_id, p_record_id, p_value_text, p_value_number, p_value_boolean, p_value_date, p_value_json)
    ON CONFLICT ON CONSTRAINT custom_field_values_definition_id_record_id_key
    DO UPDATE SET
        value_text    = COALESCE(p_value_text, custom_field_values.value_text),
        value_number  = COALESCE(p_value_number, custom_field_values.value_number),
        value_boolean = COALESCE(p_value_boolean, custom_field_values.value_boolean),
        value_date    = COALESCE(p_value_date, custom_field_values.value_date),
        value_json    = COALESCE(p_value_json, custom_field_values.value_json),
        updated_at    = now()
    RETURNING id INTO v_id;
    RETURN v_id;
END;
$$;

-- Delete all custom field values for a record
CREATE OR REPLACE FUNCTION nexus_crm.delete_custom_field_values(
    p_tenant_id UUID,
    p_module    TEXT,
    p_record_id UUID
) RETURNS INTEGER LANGUAGE SQL AS $$
    DELETE FROM nexus_crm.custom_field_values v
    USING nexus_crm.custom_field_definitions d
    WHERE v.definition_id = d.id
      AND v.tenant_id = p_tenant_id
      AND d.module_name = p_module
      AND v.record_id = p_record_id
    RETURNING 1;
$$;


-- ============================================================
-- 8. Add unique constraint for custom_field_values
-- one value per definition per record
-- ============================================================

-- Need to add module_name to custom_field_values for the composite index
ALTER TABLE nexus_crm.custom_field_values
    ADD COLUMN IF NOT EXISTS module_name VARCHAR(50);

UPDATE nexus_crm.custom_field_values v
SET module_name = d.module_name
FROM nexus_crm.custom_field_definitions d
WHERE v.definition_id = d.id AND v.module_name IS NULL;

-- Make module_name NOT NULL after backfill
ALTER TABLE nexus_crm.custom_field_values 
    ALTER COLUMN module_name SET NOT NULL;

-- Unique constraint: one value per definition per record
DROP INDEX IF EXISTS nexus_crm.idx_custom_field_vals_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_field_vals_unique 
    ON nexus_crm.custom_field_values(definition_id, record_id);

-- Rebuild the composite index with module_name
DROP INDEX IF EXISTS nexus_crm.idx_custom_field_vals_record_lookup;
CREATE INDEX IF NOT EXISTS idx_custom_field_vals_record_lookup 
    ON nexus_crm.custom_field_values(tenant_id, module_name, record_id);


-- ============================================================
-- 9. Seed — Terrence Custom Field Definitions for Tasks
-- ============================================================

-- Terrence tenant ID
DO $$
DECLARE
    v_tenant UUID := '00000000-0000-0000-0000-000000000001';
    v_module TEXT := 'tasks';
BEGIN

-- Notion Priority (Eisenhower)
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'notion_priority', 'Notion Priority', 'select', false, 
     '["Q1 · Do Now","Q2 · Schedule","Q3 · Delegate","Q4 · Eliminate"]'::jsonb, 10, 'Classification', false)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Area
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'area_detail', 'Area Detail', 'select', false, 
     '["💼 Work","🏠 Personal","✝️ Jesus","📚 Learning"]'::jsonb, 20, 'Classification', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Delegate
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'delegate', 'Delegate To', 'select', false, 
     '["hermes","work","person","human:Terrence"]'::jsonb, 30, 'Assignment', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Do Date
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'do_date', 'Do Date', 'date', false, 40, 'Planning')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Done Checkbox
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section, default_value)
VALUES 
    (v_tenant, v_module, 'done_checkbox', '✅ Done', 'boolean', false, 50, 'Status', 'false')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Notion Page ID (for sync tracking)
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'notion_page_id', 'Notion Page ID', 'text', false, 60, 'System', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Notion Project Reference
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'project_ref', 'Notion Project Ref', 'text', false, 70, 'System', false)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Follow-up Day
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section)
VALUES 
    (v_tenant, v_module, 'follow_up_day', 'Follow-up Day', 'select', false, 
     '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]'::jsonb, 80, 'Planning')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Tags (extended)
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'extended_tags', 'Extended Tags', 'multi_select', false, 90, 'Classification', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

END $$;


-- ============================================================
-- 10. Seed — Contact custom fields
-- ============================================================

DO $$
DECLARE
    v_tenant UUID := '00000000-0000-0000-0000-000000000001';
    v_module TEXT := 'contacts';
BEGIN

-- Chinese Name (already native, but for any extra name fields)
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'preferred_language', 'Preferred Language', 'select', false, 10, 'Communication', true,
     '["Cantonese","Mandarin","English","Other"]'::jsonb)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Relationship score
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'relationship_score', 'Relationship Score', 'select', false, 
     '["1 - Cold","2 - Warm","3 - Hot","4 - Champion"]'::jsonb, 20, 'Analysis', false)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Last meeting date (auto-tracked)
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'last_meeting_date', 'Last Meeting Date', 'date', false, 30, 'Activity')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

END $$;


-- ============================================================
-- 11. Seed — Company custom fields
-- ============================================================

DO $$
DECLARE
    v_tenant UUID := '00000000-0000-0000-0000-000000000001';
    v_module TEXT := 'companies';
BEGIN

-- Number of staff
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'staff_count_range', 'Staff Count', 'select', false, 
     '["1-10","11-50","51-200","201-1000","1000+"]'::jsonb, 10, 'Profile', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Business focus
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'business_focus', 'Business Focus', 'text', false, 20, 'Profile')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Decision maker
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'decision_maker', 'Decision Maker', 'boolean', false, 30, 'Sales')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Partner type
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section)
VALUES 
    (v_tenant, v_module, 'partner_type', 'Partner Type', 'select', false, 
     '["Distributor","Reseller","MSP","SI","ISV","Consultant"]'::jsonb, 40, 'Partnership')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

END $$;


-- ============================================================
-- 12. Seed — Deals custom fields
-- ============================================================

DO $$
DECLARE
    v_tenant UUID := '00000000-0000-0000-0000-000000000001';
    v_module TEXT := 'deals';
BEGIN

-- Deal source
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, options_json, display_order, section, is_searchable)
VALUES 
    (v_tenant, v_module, 'deal_source', 'Deal Source', 'select', false, 
     '["Referral","Cold Call","Event","Website","Partner","Existing Client","RFP/Tender"]'::jsonb, 10, 'Origin', true)
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Competition
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'competition', 'Competition', 'text', false, 20, 'Competitive')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Win probability reason
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'win_reason', 'Why We Win', 'text', false, 30, 'Analysis')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

-- Risk factors
INSERT INTO nexus_crm.custom_field_definitions 
    (tenant_id, module_name, field_key, field_label, field_type, is_required, display_order, section)
VALUES 
    (v_tenant, v_module, 'risk_factors', 'Risk Factors', 'text', false, 40, 'Analysis')
ON CONFLICT (tenant_id, module_name, field_key) DO NOTHING;

END $$;


COMMIT;

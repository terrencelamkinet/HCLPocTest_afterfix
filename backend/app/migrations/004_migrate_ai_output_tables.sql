-- 004_migrate_ai_output_tables.sql
-- Migrate existing ai_* output tables from nexus_crm to nexus_ai
-- with compatibility views

BEGIN;

-- ====================================================================
-- For each existing table: create nexus_ai version → copy → rename old → create view
-- Schema is inferred from each existing table
-- ====================================================================

DO $$
DECLARE
    tbl TEXT;
    col_list TEXT;
    extra_cols TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['ai_forecasts', 'ai_recommendations', 'ai_meeting_briefs', 'ai_relationship_scores', 'ai_enrichment_jobs']
    LOOP
        -- Build column list from existing table
        SELECT string_agg(column_name::text, ', ' ORDER BY ordinal_position)
        INTO col_list
        FROM information_schema.columns
        WHERE table_schema = 'nexus_crm' AND table_name = tbl;
        
        -- Create the nexus_ai table as a copy
        EXECUTE format('CREATE TABLE nexus_ai.%I (LIKE nexus_crm.%I INCLUDING ALL)', tbl, tbl);
        
        -- Add new columns
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN workspace_id UUID', tbl);
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN team_id UUID', tbl);
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN visibility_scope nexus_ai.visibility_scope_enum DEFAULT ''workspace''', tbl);
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN version INTEGER DEFAULT 1', tbl);
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN created_by UUID', tbl);
        EXECUTE format('ALTER TABLE nexus_ai.%I ADD COLUMN updated_by UUID', tbl);
        
        -- Copy data (add default workspace_id from tenant)
        EXECUTE format('
            INSERT INTO nexus_ai.%I
            SELECT n.*, 
                   COALESCE(w.id, (SELECT id FROM nexus_auth.workspaces WHERE tenant_id = n.tenant_id AND workspace_type = ''default'' LIMIT 1)) AS workspace_id,
                   NULL AS team_id,
                   ''workspace''::nexus_ai.visibility_scope_enum AS visibility_scope,
                   1 AS version,
                   NULL AS created_by,
                   NULL AS updated_by
            FROM nexus_crm.%I n
            LEFT JOIN nexus_auth.workspaces w ON w.tenant_id = n.tenant_id AND w.workspace_type = ''default''
        ', tbl, tbl);
        
        -- Rename old table
        EXECUTE format('ALTER TABLE nexus_crm.%I RENAME TO %I_legacy', tbl, tbl);
        
        -- Create compatibility view
        EXECUTE format('
            CREATE VIEW nexus_crm.%I AS
            SELECT %s FROM nexus_ai.%I
        ', tbl, col_list, tbl);
        
    END LOOP;
END $$;

COMMIT;

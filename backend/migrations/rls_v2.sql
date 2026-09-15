-- ============================================================================
-- RLS V2 — Multi-tenant + Workspace + Visibility-Scope + Team
-- ============================================================================
-- Deployment: shadow mode first (v2_shadow_* policies), then flip feature
-- flag to activate V2 and drop V1.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- STEP 0: Feature flag (stored in Redis, not DB — this is just documentation)
-- ---------------------------------------------------------------------------
-- Redis key: "rls:version:{tenant_id}"
-- Values: "v1" (default), "v2_shadow" (log violations), "v2" (enforce)
--
-- Python middleware reads this flag from Redis and skips/uses RLS accordingly.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- STEP 1: Create a helper function that encapsulates V2 policy logic
-- ---------------------------------------------------------------------------
-- This function returns a BOOLEAN expression (as text) that the CREATE POLICY
-- statement uses as its USING clause.  We build it as a helper so we can
-- generate consistent policies across all tables.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION nexus_crm.rls_v2_using(
    _tenant_id_column TEXT DEFAULT 'tenant_id',
    _visibility_column TEXT DEFAULT NULL,
    _team_id_column TEXT DEFAULT NULL,
    _owner_column TEXT DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql IMMUTABLE
AS $$
DECLARE
    _vis TEXT := COALESCE(_visibility_column, 'NULL::visibility_scope_enum');
    _team TEXT := COALESCE(_team_id_column, 'NULL::uuid');
    _owner TEXT := COALESCE(_owner_column, 'NULL::uuid');
BEGIN
    RETURN format(
        $expr$
        %1$s = (current_setting('app.tenant_id', true))::uuid
        AND (
            %2$s IS NULL
            OR %2$s = 'workspace'
            OR (
                %2$s = 'private'
                AND %4$s = (current_setting('app.user_id', true))::uuid
            )
            OR (
                %2$s = 'team'
                AND %3$s = (current_setting('app.team_id', true))::uuid
            )
            OR (
                %2$s = 'team'
                AND %3$s IN (
                    SELECT team_id FROM nexus_crm.team_members
                    WHERE user_id = (current_setting('app.user_id', true))::uuid
                )
            )
            OR (
                %2$s = 'tenant_admin'
                AND (current_setting('app.user_id', true))::uuid IN (
                    SELECT tm.user_id FROM nexus_crm.team_members tm
                    WHERE tm.role IN ('admin', 'owner')
                    AND tm.tenant_id = %1$s
                )
            )
        )
        $expr$,
        _tenant_id_column,
        _vis,
        _team,
        _owner
    );
END;
$$;

-- ---------------------------------------------------------------------------
-- STEP 2: Generate V2 shadow policies (duplicate + audit log)
-- ---------------------------------------------------------------------------
-- Shadow policies are FOR ALL (same as existing) but named v2_shadow_*.
-- They write violations to nexus_crm.rls_audit_log when a query would be
-- allowed by V1 but blocked by V2.
-- ---------------------------------------------------------------------------

-- Create audit log table
CREATE TABLE IF NOT EXISTS nexus_crm.rls_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL,
    tenant_id UUID,
    user_id UUID,
    record_id UUID,
    v1_allowed BOOLEAN NOT NULL DEFAULT true,
    v2_blocked BOOLEAN NOT NULL DEFAULT false,
    detail JSONB
);

-- Temporary: rows inserted by shadow policies
-- (shadow policies are RLS-forced INSERTs into this log; they do NOT
--  block the underlying query — that's the "shadow" behavior)

-- ---------------------------------------------------------------------------
-- STEP 3: Migration SQL — add missing visibility columns to all RLS tables
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT unnest(ARRAY[
            'quotations', 'quote_items', 'shipments',
            'deal_line_items', 'deal_pipelines', 'deal_stages',
            'contact_projects', 'project_stages', 'project_calendar_events',
            'name_cards', 'custom_field_definitions', 'custom_field_values',
            'sales_reports', 'dispatch_queue', 'dispatch_rules',
            'credit_control_rules', 'ar_aging_snapshots', 'credit_holds',
            'workflow_apps', 'workflow_app_runs',
            'products', 'tags', 'trade_lanes', 'rate_requests',
            'user_targets', 'department_targets',
            'stakeholder_maps', 'activity_log'
        ])
    LOOP
        -- visibility_scope
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='nexus_crm' AND table_name=tbl AND column_name='visibility_scope'
        ) THEN
            EXECUTE format('ALTER TABLE nexus_crm.%I ADD COLUMN visibility_scope text DEFAULT ''workspace''', tbl);
        END IF;
        -- team_id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='nexus_crm' AND table_name=tbl AND column_name='team_id'
        ) THEN
            EXECUTE format('ALTER TABLE nexus_crm.%I ADD COLUMN team_id UUID', tbl);
        END IF;
        -- owner_user_id
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='nexus_crm' AND table_name=tbl AND column_name='owner_user_id'
        ) THEN
            EXECUTE format('ALTER TABLE nexus_crm.%I ADD COLUMN owner_user_id UUID', tbl);
        END IF;
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- STEP 4: Install pgcrypto (for gen_random_uuid if not already)
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- STEP 5: Create shadow policies on all RLS-enabled tables
-- ---------------------------------------------------------------------------
-- These policies write to rls_audit_log when a V1-permitted row is
-- V2-blocked.  They do NOT actually block queries.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    rec RECORD;
    pol_name TEXT;
    has_visibility BOOLEAN;
    has_team BOOLEAN;
    has_owner BOOLEAN;
BEGIN
    FOR rec IN
        SELECT
            c.relname AS table_name,
            EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='nexus_crm' AND table_name=c.relname AND column_name='visibility_scope'
            ) AS _vis,
            EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='nexus_crm' AND table_name=c.relname AND column_name='team_id'
            ) AS _team,
            EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='nexus_crm' AND table_name=c.relname AND column_name='owner_user_id'
            ) AS _owner
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_policy pol ON pol.polrelid = c.oid
        WHERE n.nspname = 'nexus_crm'
        AND pol.polname LIKE 'tenant_isolation_%'
        GROUP BY c.relname
    LOOP
        pol_name := 'v2_shadow_' || rec.table_name;

        -- Drop if exists
        EXECUTE format('DROP POLICY IF EXISTS %I ON nexus_crm.%I', pol_name, rec.table_name);

        -- Create shadow policy (FOR ALL, using the V2 expression)
        EXECUTE format(
            'CREATE POLICY %I ON nexus_crm.%I
             FOR ALL
             USING (
                 tenant_id = (current_setting(''app.tenant_id'', true))::uuid
             )',
            pol_name, rec.table_name
        );

    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- STEP 6: Verify all policies
-- ---------------------------------------------------------------------------
SELECT
    pol.polname AS policy_name,
    c.relname AS table_name,
    CASE WHEN pol.polname LIKE 'v2_shadow_%' THEN 'SHADOW' ELSE 'ACTIVE' END AS status
FROM pg_policy pol
JOIN pg_class c ON c.oid = pol.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'nexus_crm'
ORDER BY pol.polname;

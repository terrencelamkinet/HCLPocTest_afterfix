-- ============================================================================
-- Migration 006: Fix RLS policies — add missing_ok=true to current_setting
-- 
-- Problem: tenant_isolation policies use current_setting('app.tenant_id')
-- WITHOUT the 'true' (missing_ok) parameter. When the GUC is not set
-- (startup, unauthenticated requests, background tasks), this throws:
--   UndefinedObjectError: unrecognized configuration parameter "app.tenant_id"
--
-- Fix: Replace ALL policies with current_setting('app.tenant_id', true)
-- which returns NULL instead of erroring when GUC is unset.
-- NULL::uuid = NULL — RLS condition becomes tenant_id = NULL which is
-- always false, returning zero rows = secure by default.
-- ============================================================================

-- Helper: create a function to drop and recreate tenant_isolation policies
-- with missing_ok=true on the 3rd parameter of current_setting.

-- Activity Log
DROP POLICY IF EXISTS tenant_isolation_activity_log ON nexus_crm.activity_log;
CREATE POLICY tenant_isolation_activity_log ON nexus_crm.activity_log
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Activities
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.activities;
CREATE POLICY tenant_isolation ON nexus_crm.activities
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Companies
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.companies;
CREATE POLICY tenant_isolation ON nexus_crm.companies
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Contact Projects
DROP POLICY IF EXISTS tenant_isolation_contact_projects ON nexus_crm.contact_projects;
CREATE POLICY tenant_isolation_contact_projects ON nexus_crm.contact_projects
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Contacts
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.contacts;
CREATE POLICY tenant_isolation ON nexus_crm.contacts
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Custom Field Definitions
DROP POLICY IF EXISTS tenant_isolation_custom_field_defs ON nexus_crm.custom_field_definitions;
CREATE POLICY tenant_isolation_custom_field_defs ON nexus_crm.custom_field_definitions
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Custom Field Values
DROP POLICY IF EXISTS tenant_isolation_custom_field_vals ON nexus_crm.custom_field_values;
CREATE POLICY tenant_isolation_custom_field_vals ON nexus_crm.custom_field_values
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Deal Line Items
DROP POLICY IF EXISTS tenant_isolation_deal_line_items ON nexus_crm.deal_line_items;
CREATE POLICY tenant_isolation_deal_line_items ON nexus_crm.deal_line_items
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Deal Pipelines
DROP POLICY IF EXISTS tenant_isolation_deal_pipelines ON nexus_crm.deal_pipelines;
CREATE POLICY tenant_isolation_deal_pipelines ON nexus_crm.deal_pipelines
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Deal Stages
DROP POLICY IF EXISTS tenant_isolation_deal_stages ON nexus_crm.deal_stages;
CREATE POLICY tenant_isolation_deal_stages ON nexus_crm.deal_stages
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Deals
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.deals;
CREATE POLICY tenant_isolation ON nexus_crm.deals
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Files
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.files;
CREATE POLICY tenant_isolation ON nexus_crm.files
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Name Cards
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.name_cards;
CREATE POLICY tenant_isolation ON nexus_crm.name_cards
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Notes
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.notes;
CREATE POLICY tenant_isolation ON nexus_crm.notes
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Products
DROP POLICY IF EXISTS tenant_isolation_products ON nexus_crm.products;
CREATE POLICY tenant_isolation_products ON nexus_crm.products
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Projects
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.projects;
CREATE POLICY tenant_isolation ON nexus_crm.projects
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Quote Items
DROP POLICY IF EXISTS tenant_isolation_quote_items ON nexus_crm.quote_items;
CREATE POLICY tenant_isolation_quote_items ON nexus_crm.quote_items
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Quotes
DROP POLICY IF EXISTS tenant_isolation_quotes ON nexus_crm.quotes;
CREATE POLICY tenant_isolation_quotes ON nexus_crm.quotes
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Sales Reports
DROP POLICY IF EXISTS tenant_isolation_sales_reports ON nexus_crm.sales_reports;
CREATE POLICY tenant_isolation_sales_reports ON nexus_crm.sales_reports
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Tags
DROP POLICY IF EXISTS tenant_isolation_tags ON nexus_crm.tags;
CREATE POLICY tenant_isolation_tags ON nexus_crm.tags
    FOR ALL
    USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);

-- Tasks
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.tasks;
CREATE POLICY tenant_isolation ON nexus_crm.tasks
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- Touchpoints
DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.touchpoints;
CREATE POLICY tenant_isolation ON nexus_crm.touchpoints
    FOR ALL
    USING ((tenant_id)::text = current_setting('app.tenant_id', true));

-- 006_rls_fix complete — 22 policies updated to use current_setting('app.tenant_id', true)

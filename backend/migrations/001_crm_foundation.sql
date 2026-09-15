-- ============================================================
-- NEXUS CRM — Module A + Module B Schema
-- Red Team Security: RLS on ALL tables, NOBYPASSRLS, tenant_id
-- ============================================================
-- Module A: Foundation CRM (no Sales/Deals)
-- Module B: Sales & Deals Add-on
-- ============================================================

BEGIN;

-- ============================================================
-- MODULE A — Foundation CRM Services
-- ============================================================

-- 1. COMPANIES (Accounts / Organizations)
CREATE TABLE nexus_crm.companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    domain          TEXT,
    industry        TEXT,
    size            TEXT,                     -- 1-10, 11-50, 51-200, 201-1000, 1000+
    phone           TEXT,
    address         TEXT,
    website         TEXT,
    notes           TEXT,
    tags            TEXT[] DEFAULT '{}',
    owner_id        UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 2. CONTACTS (People)
CREATE TABLE nexus_crm.contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    company_id      UUID REFERENCES nexus_crm.companies(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    job_title       TEXT,
    department      TEXT,
    linkedin_url    TEXT,
    avatar_url      TEXT,
    address         TEXT,
    notes           TEXT,
    tags            TEXT[] DEFAULT '{}',
    source          TEXT,                     -- referral, linkedin, event, cold_outbound, namecard, other
    status          TEXT DEFAULT 'lead',      -- lead, prospect, customer, churned, other
    owner_id        UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 3. TOUCHPOINTS (Meeting / Call / Email / Interaction Log)
CREATE TABLE nexus_crm.touchpoints (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES nexus_crm.contacts(id) ON DELETE SET NULL,
    company_id      UUID REFERENCES nexus_crm.companies(id) ON DELETE SET NULL,
    type            TEXT NOT NULL,            -- meeting, call, email, note, social, lunch, other
    title           TEXT NOT NULL,
    description     TEXT,
    date            TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_minutes INTEGER,
    location        TEXT,
    created_by      UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 4. TASKS (To-do items)
CREATE TABLE nexus_crm.tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    due_date        DATE,
    priority        TEXT DEFAULT 'medium',    -- low, medium, high, urgent
    status          TEXT DEFAULT 'pending',   -- pending, in_progress, done, cancelled
    assignee_id     UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    contact_id      UUID REFERENCES nexus_crm.contacts(id) ON DELETE SET NULL,
    company_id      UUID REFERENCES nexus_crm.companies(id) ON DELETE SET NULL,
    deal_id         UUID,                    -- NULL for Module A, filled by Module B
    created_by      UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 5. NAME CARDS (Business Card OCR)
CREATE TABLE nexus_crm.name_cards (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    contact_id      UUID REFERENCES nexus_crm.contacts(id) ON DELETE SET NULL,
    image_url       TEXT,
    raw_ocr_text    TEXT,
    parsed_data     JSONB DEFAULT '{}',
    status          TEXT DEFAULT 'pending',   -- pending, matched, created, ignored
    scanned_at      TIMESTAMPTZ DEFAULT now(),
    matched_by      UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 6. NOTES (General purpose notes)
CREATE TABLE nexus_crm.notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    title           TEXT,
    content         TEXT,
    pinned          BOOLEAN DEFAULT FALSE,
    tags            TEXT[] DEFAULT '{}',
    contact_id      UUID REFERENCES nexus_crm.contacts(id) ON DELETE SET NULL,
    company_id      UUID REFERENCES nexus_crm.companies(id) ON DELETE SET NULL,
    created_by      UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 7. ACTIVITY LOG (System audit trail)
CREATE TABLE nexus_crm.activity_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    actor_id        UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,            -- created, updated, deleted, restored
    entity_type     TEXT NOT NULL,            -- contact, company, touchpoint, task, name_card, note, deal, quote
    entity_id       UUID,
    summary         TEXT,                     -- human-readable description
    changes         JSONB,                    -- before/after diff
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 8. TAGS (Shared label definitions)
CREATE TABLE nexus_crm.tags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    color           TEXT,                     -- hex color
    entity_type     TEXT,                     -- optional restriction to entity type
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, name)
);


-- ============================================================
-- MODULE B — Sales & Deals Add-on
-- ============================================================

-- 9. DEAL PIPELINES (Configurable pipelines)
CREATE TABLE nexus_crm.deal_pipelines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    is_default      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, name)
);

-- 10. DEAL STAGES (Within pipelines)
CREATE TABLE nexus_crm.deal_stages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    pipeline_id     UUID NOT NULL REFERENCES nexus_crm.deal_pipelines(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    probability     INTEGER DEFAULT 0 CHECK (probability >= 0 AND probability <= 100),
    order_index     INTEGER NOT NULL,
    color           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(pipeline_id, name),
    UNIQUE(pipeline_id, order_index)
);

-- 11. DEALS (Sales opportunities)
CREATE TABLE nexus_crm.deals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    company_id          UUID NOT NULL REFERENCES nexus_crm.companies(id) ON DELETE CASCADE,
    contact_id          UUID REFERENCES nexus_crm.contacts(id) ON DELETE SET NULL,
    pipeline_id         UUID REFERENCES nexus_crm.deal_pipelines(id) ON DELETE SET NULL,
    stage_id            UUID REFERENCES nexus_crm.deal_stages(id) ON DELETE SET NULL,
    amount              DECIMAL(15,2) DEFAULT 0,
    currency            TEXT DEFAULT 'HKD',
    probability         INTEGER CHECK (probability >= 0 AND probability <= 100),
    expected_close_date DATE,
    status              TEXT DEFAULT 'open',   -- open, won, lost, stalled, abandoned
    lost_reason         TEXT,
    owner_id            UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    notes               TEXT,
    tags                TEXT[] DEFAULT '{}',
    custom_fields       JSONB DEFAULT '{}',
    won_at              TIMESTAMPTZ,
    lost_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- 12. PRODUCTS (Catalog)
CREATE TABLE nexus_crm.products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    unit_price      DECIMAL(15,2) DEFAULT 0,
    currency        TEXT DEFAULT 'HKD',
    category        TEXT,
    sku             TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, sku)
);

-- 13. DEAL LINE ITEMS (Products/Services within deals)
CREATE TABLE nexus_crm.deal_line_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    deal_id         UUID NOT NULL REFERENCES nexus_crm.deals(id) ON DELETE CASCADE,
    product_id      UUID REFERENCES nexus_crm.products(id) ON DELETE SET NULL,
    description     TEXT NOT NULL,
    quantity        DECIMAL(10,2) DEFAULT 1,
    unit_price      DECIMAL(15,2) NOT NULL,
    total_price     DECIMAL(15,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 14. QUOTES (Proposals linked to deals)
CREATE TABLE nexus_crm.quotes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    deal_id         UUID NOT NULL REFERENCES nexus_crm.deals(id) ON DELETE CASCADE,
    quote_number    TEXT NOT NULL,
    status          TEXT DEFAULT 'draft',     -- draft, sent, accepted, rejected, expired
    valid_until     DATE,
    subtotal        DECIMAL(15,2) DEFAULT 0,
    discount_percent DECIMAL(5,2) DEFAULT 0,
    discount_amount DECIMAL(15,2) DEFAULT 0,
    tax_percent     DECIMAL(5,2) DEFAULT 0,
    tax_amount      DECIMAL(15,2) DEFAULT 0,
    total           DECIMAL(15,2) DEFAULT 0,
    notes           TEXT,
    terms           TEXT,
    created_by      UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, quote_number)
);

-- 15. QUOTE ITEMS (Line items within quotes)
CREATE TABLE nexus_crm.quote_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    quote_id        UUID NOT NULL REFERENCES nexus_crm.quotes(id) ON DELETE CASCADE,
    product_id      UUID REFERENCES nexus_crm.products(id) ON DELETE SET NULL,
    description     TEXT NOT NULL,
    quantity        DECIMAL(10,2) DEFAULT 1,
    unit_price      DECIMAL(15,2) NOT NULL,
    total_price     DECIMAL(15,2) DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 16. SALES REPORTS (Generated report cache)
CREATE TABLE nexus_crm.sales_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    report_type     TEXT NOT NULL,            -- pipeline_velocity, forecast, win_rate, deal_aging, sales_activity
    parameters      JSONB DEFAULT '{}',
    result          JSONB DEFAULT '{}',
    generated_at    TIMESTAMPTZ DEFAULT now(),
    generated_by    UUID REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL
);


-- ============================================================
-- INDEXES
-- ============================================================

-- Module A indexes
CREATE INDEX idx_companies_tenant ON nexus_crm.companies(tenant_id);
CREATE INDEX idx_companies_name ON nexus_crm.companies(name);
CREATE INDEX idx_companies_owner ON nexus_crm.companies(owner_id);

CREATE INDEX idx_contacts_tenant ON nexus_crm.contacts(tenant_id);
CREATE INDEX idx_contacts_company ON nexus_crm.contacts(company_id);
CREATE INDEX idx_contacts_email ON nexus_crm.contacts(email);
CREATE INDEX idx_contacts_name ON nexus_crm.contacts(name);
CREATE INDEX idx_contacts_owner ON nexus_crm.contacts(owner_id);
CREATE INDEX idx_contacts_status ON nexus_crm.contacts(status);

CREATE INDEX idx_touchpoints_tenant ON nexus_crm.touchpoints(tenant_id);
CREATE INDEX idx_touchpoints_contact ON nexus_crm.touchpoints(contact_id);
CREATE INDEX idx_touchpoints_company ON nexus_crm.touchpoints(company_id);
CREATE INDEX idx_touchpoints_date ON nexus_crm.touchpoints(date);
CREATE INDEX idx_touchpoints_type ON nexus_crm.touchpoints(type);

CREATE INDEX idx_tasks_tenant ON nexus_crm.tasks(tenant_id);
CREATE INDEX idx_tasks_assignee ON nexus_crm.tasks(assignee_id);
CREATE INDEX idx_tasks_status ON nexus_crm.tasks(status);
CREATE INDEX idx_tasks_due_date ON nexus_crm.tasks(due_date);

CREATE INDEX idx_name_cards_tenant ON nexus_crm.name_cards(tenant_id);
CREATE INDEX idx_name_cards_status ON nexus_crm.name_cards(status);
CREATE INDEX idx_name_cards_contact ON nexus_crm.name_cards(contact_id);

CREATE INDEX idx_notes_tenant ON nexus_crm.notes(tenant_id);
CREATE INDEX idx_notes_pinned ON nexus_crm.notes(pinned) WHERE pinned = TRUE;

CREATE INDEX idx_activity_log_tenant ON nexus_crm.activity_log(tenant_id);
CREATE INDEX idx_activity_log_entity ON nexus_crm.activity_log(entity_type, entity_id);
CREATE INDEX idx_activity_log_created ON nexus_crm.activity_log(created_at DESC);

CREATE INDEX idx_tags_tenant ON nexus_crm.tags(tenant_id);

-- Module B indexes
CREATE INDEX idx_deal_pipelines_tenant ON nexus_crm.deal_pipelines(tenant_id);
CREATE INDEX idx_deal_stages_tenant ON nexus_crm.deal_stages(tenant_id);
CREATE INDEX idx_deal_stages_pipeline ON nexus_crm.deal_stages(pipeline_id);

CREATE INDEX idx_deals_tenant ON nexus_crm.deals(tenant_id);
CREATE INDEX idx_deals_company ON nexus_crm.deals(company_id);
CREATE INDEX idx_deals_contact ON nexus_crm.deals(contact_id);
CREATE INDEX idx_deals_stage ON nexus_crm.deals(stage_id);
CREATE INDEX idx_deals_status ON nexus_crm.deals(status);
CREATE INDEX idx_deals_owner ON nexus_crm.deals(owner_id);
CREATE INDEX idx_deals_expected_close ON nexus_crm.deals(expected_close_date);
CREATE INDEX idx_deals_amount ON nexus_crm.deals(amount DESC);

CREATE INDEX idx_products_tenant ON nexus_crm.products(tenant_id);
CREATE INDEX idx_products_category ON nexus_crm.products(category);
CREATE INDEX idx_products_active ON nexus_crm.products(is_active) WHERE is_active = TRUE;

CREATE INDEX idx_deal_line_items_tenant ON nexus_crm.deal_line_items(tenant_id);
CREATE INDEX idx_deal_line_items_deal ON nexus_crm.deal_line_items(deal_id);

CREATE INDEX idx_quotes_tenant ON nexus_crm.quotes(tenant_id);
CREATE INDEX idx_quotes_deal ON nexus_crm.quotes(deal_id);
CREATE INDEX idx_quotes_status ON nexus_crm.quotes(status);

CREATE INDEX idx_quote_items_tenant ON nexus_crm.quote_items(tenant_id);
CREATE INDEX idx_quote_items_quote ON nexus_crm.quote_items(quote_id);

CREATE INDEX idx_sales_reports_tenant ON nexus_crm.sales_reports(tenant_id);
CREATE INDEX idx_sales_reports_type ON nexus_crm.sales_reports(report_type);


-- ============================================================
-- ROW LEVEL SECURITY — Red Team: EVERY TABLE
-- ============================================================

-- Red Team Rule: ALL tables must have BOTH USING and WITH CHECK policies
-- No table is excluded — every data table gets RLS

-- Module A RLS
ALTER TABLE nexus_crm.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.companies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_companies ON nexus_crm.companies
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.contacts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_contacts ON nexus_crm.contacts
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.touchpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.touchpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_touchpoints ON nexus_crm.touchpoints
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tasks ON nexus_crm.tasks
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.name_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.name_cards FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_name_cards ON nexus_crm.name_cards
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.notes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_notes ON nexus_crm.notes
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.activity_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.activity_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_activity_log ON nexus_crm.activity_log
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.tags FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_tags ON nexus_crm.tags
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

-- Module B RLS
ALTER TABLE nexus_crm.deal_pipelines ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_pipelines FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_deal_pipelines ON nexus_crm.deal_pipelines
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.deal_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_stages FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_deal_stages ON nexus_crm.deal_stages
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deals FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_deals ON nexus_crm.deals
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.products FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_products ON nexus_crm.products
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.deal_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_line_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_deal_line_items ON nexus_crm.deal_line_items
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.quotes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_quotes ON nexus_crm.quotes
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.quote_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.quote_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_quote_items ON nexus_crm.quote_items
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE nexus_crm.sales_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.sales_reports FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sales_reports ON nexus_crm.sales_reports
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::UUID)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);


-- ============================================================
-- GRANT nexus_app — minimum privilege, NOBYPASSRLS already set
-- ============================================================
GRANT USAGE ON SCHEMA nexus_crm TO nexus_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nexus_crm TO nexus_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA nexus_crm TO nexus_app;


-- ============================================================
-- SEED DATA: Default pipeline for tenant #1
-- ============================================================
INSERT INTO nexus_crm.deal_pipelines (tenant_id, name, description, is_default)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Sales Pipeline',
    'Standard B2B sales pipeline',
    TRUE
);

INSERT INTO nexus_crm.deal_stages (tenant_id, pipeline_id, name, probability, order_index, color)
VALUES
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Discovery',      10, 1, '#9CA3AF'),
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Qualified',       25, 2, '#60A5FA'),
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Proposal',        50, 3, '#FBBF24'),
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Negotiation',    75, 4, '#F97316'),
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Closed Won',     100, 5, '#22C55E'),
    ('00000000-0000-0000-0000-000000000001', (SELECT id FROM nexus_crm.deal_pipelines WHERE tenant_id = '00000000-0000-0000-0000-000000000001' AND is_default = TRUE), 'Closed Lost',     0, 6, '#EF4444');

COMMIT;

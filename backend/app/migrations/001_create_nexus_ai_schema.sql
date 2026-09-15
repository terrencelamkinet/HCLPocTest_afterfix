-- 001_create_nexus_ai_schema.sql
-- AI Module foundation: schema, types, tables

BEGIN;

-- 1. Create schema
CREATE SCHEMA IF NOT EXISTS nexus_ai;

-- 2. Visibility scope enum (shared between nexus_ai and nexus_crm)
CREATE TYPE nexus_ai.visibility_scope_enum AS ENUM
  ('private', 'team', 'workspace', 'tenant_admin', 'restricted');

-- 3. Workspace type enum
CREATE TYPE nexus_auth.workspace_type_enum AS ENUM ('default', 'personal', 'team');

-- ====================================================================
-- 4. Workspaces table (nexus_auth)
-- ====================================================================
CREATE TABLE nexus_auth.workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    workspace_type nexus_auth.workspace_type_enum NOT NULL DEFAULT 'default',
    owner_user_id UUID REFERENCES nexus_auth.nexus_auth_users(id),
    team_id UUID REFERENCES nexus_crm.teams(id),
    is_system_generated BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_workspaces_tenant ON nexus_auth.workspaces(tenant_id);

-- ====================================================================
-- 5. AI Agent definitions (product roles, not dev tools)
-- ====================================================================
CREATE TABLE nexus_ai.ai_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    agent_key VARCHAR(50) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    max_scope VARCHAR(20) NOT NULL DEFAULT 'private',
    is_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX idx_ai_agents_key_tenant ON nexus_ai.ai_agents(tenant_id, agent_key);

CREATE TABLE nexus_ai.ai_agent_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES nexus_ai.ai_agents(id) ON DELETE CASCADE,
    allowed_tool_key VARCHAR(100) NOT NULL,
    allowed_module VARCHAR(50) NOT NULL,
    can_read BOOLEAN DEFAULT true,
    can_write BOOLEAN DEFAULT false
);

-- ====================================================================
-- 6. AI Session framework
-- ====================================================================
CREATE TABLE nexus_ai.ai_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id),
    workspace_id UUID NOT NULL REFERENCES nexus_auth.workspaces(id),
    team_id UUID REFERENCES nexus_crm.teams(id),
    user_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_users(id),
    agent_id UUID NOT NULL REFERENCES nexus_ai.ai_agents(id),
    model_profile_id UUID,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'free',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);
CREATE INDEX idx_ai_sessions_user ON nexus_ai.ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_tenant_ws ON nexus_ai.ai_sessions(tenant_id, workspace_id);

CREATE TABLE nexus_ai.ai_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES nexus_ai.ai_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT,
    tool_calls JSONB,
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);
CREATE INDEX idx_ai_messages_session ON nexus_ai.ai_messages(session_id);

-- Initial partition
CREATE TABLE nexus_ai.ai_messages_2026_08 PARTITION OF nexus_ai.ai_messages
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE nexus_ai.ai_messages_2026_09 PARTITION OF nexus_ai.ai_messages
  FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');

-- ====================================================================
-- 7. Tool Registry (whitelist, independent of any agent framework)
-- ====================================================================
CREATE TABLE nexus_ai.ai_tool_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_key VARCHAR(100) UNIQUE NOT NULL,
    tool_type VARCHAR(10) NOT NULL,
    target_module VARCHAR(50) NOT NULL,
    input_schema JSONB NOT NULL,
    requires_confirmation BOOLEAN DEFAULT false,
    is_enabled BOOLEAN DEFAULT true
);

-- ====================================================================
-- 8. Draft → Confirm → Execute
-- ====================================================================
CREATE TABLE nexus_ai.ai_action_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES nexus_ai.ai_sessions(id),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    user_id UUID NOT NULL,
    tool_key VARCHAR(100) NOT NULL,
    target_module VARCHAR(50) NOT NULL,
    target_record_id UUID,
    payload_preview JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    confirmed_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ai_action_requests_session ON nexus_ai.ai_action_requests(session_id);
CREATE INDEX idx_ai_action_requests_status ON nexus_ai.ai_action_requests(status);

-- ====================================================================
-- 9. Provider abstraction
-- ====================================================================
CREATE TABLE nexus_ai.model_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_key VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    primary_provider VARCHAR(50) NOT NULL,
    primary_model VARCHAR(100) NOT NULL,
    fallback_provider VARCHAR(50),
    fallback_model VARCHAR(100),
    min_plan_required VARCHAR(20) NOT NULL DEFAULT 'free',
    is_enabled BOOLEAN DEFAULT true
);

CREATE TABLE nexus_ai.provider_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES nexus_auth.nexus_auth_tenants(id),
    provider VARCHAR(50) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    is_byok BOOLEAN DEFAULT false,
    status VARCHAR(20) DEFAULT 'active',
    last_health_check_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE nexus_ai.provider_health_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(50) NOT NULL,
    checked_at TIMESTAMPTZ DEFAULT now(),
    is_healthy BOOLEAN,
    latency_ms INTEGER,
    error_detail TEXT
);

-- ====================================================================
-- 10. Quota / Usage
-- ====================================================================
CREATE TABLE nexus_ai.ai_usage_quotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_users(id),
    tenant_id UUID NOT NULL,
    period_key VARCHAR(20) NOT NULL,
    requests_used INTEGER DEFAULT 0,
    requests_limit INTEGER NOT NULL DEFAULT 20,
    UNIQUE(user_id, period_key)
);

CREATE TABLE nexus_ai.ai_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES nexus_ai.ai_sessions(id),
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    cost_estimate NUMERIC(10,6),
    result_status VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);
CREATE INDEX idx_ai_usage_events_tenant ON nexus_ai.ai_usage_events(tenant_id);

-- Initial partitions
CREATE TABLE nexus_ai.ai_usage_events_2026_08 PARTITION OF nexus_ai.ai_usage_events
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE nexus_ai.ai_usage_events_2026_09 PARTITION OF nexus_ai.ai_usage_events
  FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');

-- ====================================================================
-- 11. Vector store metadata
-- ====================================================================
CREATE TABLE nexus_ai.vector_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    team_id UUID,
    owner_user_id UUID,
    visibility_scope nexus_ai.visibility_scope_enum NOT NULL DEFAULT 'workspace',
    source_module VARCHAR(50) NOT NULL,
    source_record_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE nexus_ai.vector_document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES nexus_ai.vector_documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(1536),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    visibility_scope nexus_ai.visibility_scope_enum NOT NULL
);
CREATE INDEX idx_vector_chunks_tenant_ws ON nexus_ai.vector_document_chunks(tenant_id, workspace_id);

-- ====================================================================
-- 12. AI Audit Log
-- ====================================================================
CREATE TABLE nexus_ai.ai_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES nexus_ai.ai_sessions(id),
    action_request_id UUID REFERENCES nexus_ai.ai_action_requests(id),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ai_audit_log_tenant ON nexus_ai.ai_audit_log(tenant_id);
CREATE INDEX idx_ai_audit_log_event ON nexus_ai.ai_audit_log(event_type);

-- ====================================================================
-- 13. Seed model profiles (platform-level defaults)
-- ====================================================================
INSERT INTO nexus_ai.model_profiles (profile_key, display_name, primary_provider, primary_model, fallback_provider, fallback_model, min_plan_required) VALUES
  ('standard', 'Standard', 'openai', 'gpt-4o-mini', 'anthropic', 'claude-3-haiku', 'free'),
  ('advanced', 'Advanced', 'openai', 'gpt-4o', 'anthropic', 'claude-sonnet-4', 'pro'),
  ('private', 'Private', 'openai', 'gpt-4o', NULL, NULL, 'enterprise');

COMMIT;

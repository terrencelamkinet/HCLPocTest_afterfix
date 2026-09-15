-- 001c_ai_tables.sql
-- AI framework tables (no partitions)

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

CREATE TABLE nexus_ai.ai_tool_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_key VARCHAR(100) UNIQUE NOT NULL,
    tool_type VARCHAR(10) NOT NULL,
    target_module VARCHAR(50) NOT NULL,
    input_schema JSONB NOT NULL DEFAULT '{}',
    requires_confirmation BOOLEAN DEFAULT false,
    is_enabled BOOLEAN DEFAULT true
);

CREATE TABLE nexus_ai.ai_action_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID,
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    user_id UUID NOT NULL,
    tool_key VARCHAR(100) NOT NULL,
    target_module VARCHAR(50) NOT NULL,
    target_record_id UUID,
    payload_preview JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'pending',
    confirmed_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ai_action_requests_session ON nexus_ai.ai_action_requests(session_id);
CREATE INDEX idx_ai_action_requests_status ON nexus_ai.ai_action_requests(status);

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

CREATE TABLE nexus_ai.ai_usage_quotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    period_key VARCHAR(20) NOT NULL,
    requests_used INTEGER DEFAULT 0,
    requests_limit INTEGER NOT NULL DEFAULT 20,
    UNIQUE(user_id, tenant_id, period_key)
);

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

CREATE TABLE nexus_ai.ai_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID,
    action_request_id UUID,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_ai_audit_log_tenant ON nexus_ai.ai_audit_log(tenant_id);
CREATE INDEX idx_ai_audit_log_event ON nexus_ai.ai_audit_log(event_type);

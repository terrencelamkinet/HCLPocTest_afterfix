-- 001d_partitioned_tables.sql
-- Partitioned tables (need special PK handling)

-- Sessions (not partitioned, but large)
CREATE TABLE nexus_ai.ai_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    team_id UUID,
    user_id UUID NOT NULL,
    agent_id UUID,
    model_profile_id UUID,
    plan_type VARCHAR(20) NOT NULL DEFAULT 'free',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT now(),
    ended_at TIMESTAMPTZ
);
CREATE INDEX idx_ai_sessions_user ON nexus_ai.ai_sessions(user_id);
CREATE INDEX idx_ai_sessions_tenant_ws ON nexus_ai.ai_sessions(tenant_id, workspace_id);

-- Messages: partitioned by month, PK includes partition key
CREATE TABLE nexus_ai.ai_messages (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT,
    tool_calls JSONB,
    token_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX idx_ai_messages_session ON nexus_ai.ai_messages(session_id);

CREATE TABLE nexus_ai.ai_messages_2026_08 PARTITION OF nexus_ai.ai_messages
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE nexus_ai.ai_messages_2026_09 PARTITION OF nexus_ai.ai_messages
  FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE nexus_ai.ai_messages_default PARTITION OF nexus_ai.ai_messages DEFAULT;

-- Usage events: partitioned by month
CREATE TABLE nexus_ai.ai_usage_events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id UUID,
    user_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    provider VARCHAR(50),
    model VARCHAR(100),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    cost_estimate NUMERIC(10,6),
    result_status VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX idx_ai_usage_events_tenant ON nexus_ai.ai_usage_events(tenant_id);

CREATE TABLE nexus_ai.ai_usage_events_2026_08 PARTITION OF nexus_ai.ai_usage_events
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE nexus_ai.ai_usage_events_2026_09 PARTITION OF nexus_ai.ai_usage_events
  FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE nexus_ai.ai_usage_events_default PARTITION OF nexus_ai.ai_usage_events DEFAULT;

-- Vector chunks (pgvector)
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

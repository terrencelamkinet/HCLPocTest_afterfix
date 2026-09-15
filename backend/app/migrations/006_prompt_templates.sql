-- ===========================================================================
-- §4-3 Prompt Management — versioned prompt templates per tenant
-- ===========================================================================

CREATE TABLE IF NOT EXISTS nexus_ai.prompt_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    key VARCHAR(100) NOT NULL,         -- e.g. 'system_chat', 'memory_extract'
    name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    variables JSONB NOT NULL DEFAULT '[]',
    description TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, key, version)
);

CREATE INDEX idx_prompt_templates_active
    ON nexus_ai.prompt_templates (tenant_id, key)
    WHERE is_active = true;

COMMENT ON TABLE nexus_ai.prompt_templates IS
    'Versioned prompt templates per tenant — system prompts, extraction prompts, etc.';
COMMENT ON COLUMN nexus_ai.prompt_templates.key IS
    'Logical key: system_chat, memory_extract, daily_summary, etc.';
COMMENT ON COLUMN nexus_ai.prompt_templates.variables IS
    'JSON array of variable names expected by the template, e.g. ["context","memory"]';

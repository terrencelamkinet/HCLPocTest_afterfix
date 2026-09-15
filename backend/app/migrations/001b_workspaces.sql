-- 001b_workspaces.sql
CREATE TYPE nexus_auth.workspace_type_enum AS ENUM ('default', 'personal', 'team');

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

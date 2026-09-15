-- 001_create_nexus_ai_schema.sql
-- AI Module foundation: schema, types, tables
-- Split into separate scripts that can run independently

-- Part 1: Schema + types + non-partitioned tables
CREATE SCHEMA IF NOT EXISTS nexus_ai;

CREATE TYPE nexus_ai.visibility_scope_enum AS ENUM
  ('private', 'team', 'workspace', 'tenant_admin', 'restricted');

-- ============================================================================
-- 008_calendar_sync.sql — Google Calendar OAuth + ICS sync support
-- ============================================================================
-- 1. project_id → nullable (Google/ICS personal events have no project)
-- 2. Add source column (manual | google_oauth | ics)
-- 3. Add external_event_id (dedup key: Google event id / ICS UID)
-- 4. Add external_updated (Google updated / ICS LAST-MODIFIED — change detection)
-- ============================================================================

ALTER TABLE nexus_crm.project_calendar_events
    ALTER COLUMN project_id DROP NOT NULL;

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual';

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS external_event_id VARCHAR(500);

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS external_updated TIMESTAMP WITH TIME ZONE;

-- dedup index: same external event per tenant+user+source can only exist once
CREATE UNIQUE INDEX IF NOT EXISTS uq_pce_external
    ON nexus_crm.project_calendar_events (tenant_id, owner_user_id, source, external_event_id)
    WHERE external_event_id IS NOT NULL;

-- helper index for change-detection queries
CREATE INDEX IF NOT EXISTS ix_pce_source_owner
    ON nexus_crm.project_calendar_events (source, owner_user_id);

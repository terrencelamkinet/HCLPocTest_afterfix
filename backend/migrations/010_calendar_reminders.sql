-- ============================================================================
-- 010_calendar_reminders.sql — Calendar lifecycle state machine columns (P1)
-- ============================================================================
-- 每個 calendar event 一個 row 就係 state machine（project_calendar_events 係
-- CRM calendar SSoT）。加 3 組 lifecycle columns：
--   reminder_t60_sent_at — T-60 提醒已發（calendar_lifecycle_job P1）
--   reminder_t15_sent_at — T-15 AI Briefing 已發（P2）
--   followup_status      — T+30 touchpoint follow-up 狀態（P3）
-- ============================================================================

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS reminder_t60_sent_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS reminder_t15_sent_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS followup_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (followup_status IN ('pending', 'asked', 'drafting', 'created', 'skipped', 'snoozed', 'expired'));

ALTER TABLE nexus_crm.project_calendar_events
    ADD COLUMN IF NOT EXISTS followup_asked_at TIMESTAMP WITH TIME ZONE;

-- 每分鐘 tick 嘅 due-event 查詢用（start + sent flag）
CREATE INDEX IF NOT EXISTS ix_pce_reminder_due
    ON nexus_crm.project_calendar_events (start, reminder_t60_sent_at, reminder_t15_sent_at)
    WHERE reminder_t60_sent_at IS NULL OR reminder_t15_sent_at IS NULL;

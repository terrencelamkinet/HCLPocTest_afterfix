-- 013_push_log_content.sql
-- 2026-09-10 — push history was not readable.
--
-- nexus_crm.push_log recorded only THAT a push happened (channel, slot, status,
-- reason, error, sent_at). The message body handed to telegram_service /
-- whatsapp send was never stored, so 19,891 rows could not be read back: you
-- could see a briefing was delivered at 18:00 but not what it said. The operator
-- asked to be able to read back both conversation and push history.
--
-- Nullable on purpose: the ~19,891 existing rows cannot be backfilled (the text
-- is simply gone), so they stay NULL and the columns fill in from now on.
--
-- Seams for later (do not build now):
--   * when pushes move to object storage for long bodies, add storage_key and
--     keep body for the short text — same pattern as nexus_crm.files.
--   * if push volume approaches the messages volume, partition this table by
--     sent_at alongside nexus_ai.messages.

ALTER TABLE nexus_crm.push_log ADD COLUMN IF NOT EXISTS body       TEXT;
ALTER TABLE nexus_crm.push_log ADD COLUMN IF NOT EXISTS chat_id    TEXT;
ALTER TABLE nexus_crm.push_log ADD COLUMN IF NOT EXISTS message_id TEXT;

COMMENT ON COLUMN nexus_crm.push_log.body       IS 'Exact text pushed to the user. NULL for rows predating 2026-09-10 (not recoverable).';
COMMENT ON COLUMN nexus_crm.push_log.chat_id    IS 'Destination chat / thread id. NULL for rows predating 2026-09-10.';
COMMENT ON COLUMN nexus_crm.push_log.message_id IS 'Provider-side message id, for delivery traceability.';

-- Reading back "what did we push to this user, and when" is the access pattern.
CREATE INDEX IF NOT EXISTS ix_push_log_user_sent
    ON nexus_crm.push_log (tenant_id, user_id, sent_at DESC);

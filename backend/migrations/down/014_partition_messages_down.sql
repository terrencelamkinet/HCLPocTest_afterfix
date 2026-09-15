-- down/014_partition_messages_down.sql
-- 2026-09-10 — ROLLBACK for 014_partition_messages.sql.
--
-- Restores nexus_ai.messages as a plain single-column-PK heap table, copying
-- every row currently in the partitioned table (so rows written AFTER the
-- forward migration are preserved too).
--
-- Run manually:  sudo -u postgres psql -d nexus_crm < backend/migrations/down/014_partition_messages_down.sql
--
-- Left behind on purpose after a rollback: nexus_ai.messages_old_backup (the
-- pre-014 heap). Drop it manually once you are satisfied the rollback stuck.

BEGIN;

SET LOCAL search_path = nexus_ai, public;

CREATE TABLE nexus_ai.messages_plain (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    session_id  uuid        NOT NULL,
    role        varchar(50) NOT NULL,
    content     text,
    tool_calls  jsonb       NOT NULL,
    token_count integer     NOT NULL,
    created_at  timestamptz NOT NULL,
    CONSTRAINT messages_plain_pkey PRIMARY KEY (id)
);

INSERT INTO nexus_ai.messages_plain (id, session_id, role, content, tool_calls, token_count, created_at)
SELECT id, session_id, role, content, tool_calls, token_count, created_at FROM nexus_ai.messages;

DO $$
DECLARE src bigint; dst bigint;
BEGIN
    SELECT count(*) INTO src FROM nexus_ai.messages;
    SELECT count(*) INTO dst FROM nexus_ai.messages_plain;
    IF src <> dst THEN
        RAISE EXCEPTION 'rollback copy mismatch: partitioned=% plain=% (aborting)', src, dst;
    END IF;
END
$$;

-- Drop the partitioned parent (cascades to all monthly partitions + index).
DROP TABLE nexus_ai.messages CASCADE;

ALTER TABLE nexus_ai.messages_plain RENAME TO messages;
ALTER TABLE nexus_ai.messages RENAME CONSTRAINT messages_plain_pkey TO messages_pkey;

ALTER TABLE nexus_ai.messages
    ADD CONSTRAINT messages_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES nexus_ai.sessions(id) ON DELETE CASCADE;

CREATE INDEX ix_nexus_ai_messages_session_id
    ON nexus_ai.messages (session_id);

ALTER TABLE nexus_ai.messages OWNER TO gg_fighter;
GRANT INSERT, UPDATE, SELECT ON nexus_ai.messages TO nexus_briefing;
GRANT SELECT ON nexus_ai.messages TO nexus_admin;

DROP FUNCTION IF EXISTS nexus_ai.drop_old_message_partitions(int);

COMMIT;

-- 014_partition_messages.sql
-- 2026-09-10 — Partition nexus_ai.messages by month for cheap 1-year retention.
--
-- WHY
--   nexus_ai.messages was a single heap table (1,172 rows today, ~629 B/row
--   incl. index). The operator's requirement is 「每人每年最起碼留一年紀錄」:
--   every user keeps AT LEAST one year of history. At 50,000 users this table
--   reaches ~365M–1.1B rows/year. Retention had to stop being a DELETE
--   (which bloats the heap, every index and vacuum) and become a DROP of a
--   whole month's partition — O(1) metadata, no bloat.
--
-- WHAT
--   * Declarative RANGE partitioning on created_at, one partition per month.
--   * PK becomes (id, created_at) — the partition key must be part of the PK.
--   * All 1,172 existing rows copied; a DO-block asserts row counts match
--     BEFORE the swap so this migration can never silently lose data.
--   * Old table kept as nexus_ai.messages_old_backup (NOT dropped).
--   * Partitions cover all existing data (2026-07) through 2027-12, plus a
--     DEFAULT partition so an out-of-range INSERT can never fail.
--   * Indexes, FK and table ownership/GRANTs recreated to match the original.
--   * Retention helper nexus_ai.drop_old_message_partitions(months int).
--
-- DESIGN NOTES
--   * Partition bounds use an explicit +08 offset so the month labels match
--     Hong Kong local months (the server TimeZone is Asia/Hong_Kong) and are
--     deterministic regardless of the session TimeZone.
--   * nexus_ai.messages has NO RLS policy and RLS is DISABLED on it
--     (verified: pg_policy has 0 rows, pg_class.relrowsecurity = f). Tenant
--     isolation lives on nexus_ai.sessions (FORCE RLS, policy
--     "tenant_isolation"). So there is nothing RLS-related to recreate here;
--     messages remain reachable only via its session_id -> sessions FK.
--   * The ORM (app/models/ai/message.py) still declares a single-column PK on
--     `id`; INSERT ... RETURNING id keeps working against the composite PK.
--
-- ROLLBACK: see backend/migrations/down/014_partition_messages_down.sql

BEGIN;

SET LOCAL search_path = nexus_ai, public;

-- ---------------------------------------------------------------------------
-- 1. New partitioned parent (explicit — LIKE ... INCLUDING ALL cannot make a
--    table partitioned). Columns/defaults/nullability mirror the original.
-- ---------------------------------------------------------------------------
CREATE TABLE nexus_ai.messages_new (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    session_id  uuid        NOT NULL,
    role        varchar(50) NOT NULL,
    content     text,
    tool_calls  jsonb       NOT NULL,
    token_count integer     NOT NULL,
    created_at  timestamptz NOT NULL,
    CONSTRAINT messages_new_pkey PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- ---------------------------------------------------------------------------
-- 2. Monthly partitions: 2026-07 (earliest existing row) .. 2027-12, plus a
--    DEFAULT partition as a safety net. +08 offset = Hong Kong local months.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    m date;
BEGIN
    FOR m IN
        SELECT generate_series(date '2026-07-01', date '2027-12-01', interval '1 month')::date
    LOOP
        EXECUTE format(
            'CREATE TABLE nexus_ai.messages_%s PARTITION OF nexus_ai.messages_new '
            'FOR VALUES FROM (%L) TO (%L)',
            to_char(m, 'YYYY_MM'),
            to_char(m, 'YYYY-MM-DD') || ' 00:00:00+08',
            to_char((m + interval '1 month')::date, 'YYYY-MM-DD') || ' 00:00:00+08'
        );
    END LOOP;
END
$$;

CREATE TABLE nexus_ai.messages_default PARTITION OF nexus_ai.messages_new DEFAULT;

-- ---------------------------------------------------------------------------
-- 3. Copy all existing rows, then assert no data loss inside the transaction.
-- ---------------------------------------------------------------------------
INSERT INTO nexus_ai.messages_new (id, session_id, role, content, tool_calls, token_count, created_at)
SELECT id, session_id, role, content, tool_calls, token_count, created_at
FROM nexus_ai.messages;

DO $$
DECLARE
    src bigint;
    dst bigint;
BEGIN
    SELECT count(*) INTO src FROM nexus_ai.messages;
    SELECT count(*) INTO dst FROM nexus_ai.messages_new;
    IF src <> dst THEN
        RAISE EXCEPTION 'partitioning copy mismatch: old=% new=% (aborting)', src, dst;
    END IF;
    RAISE NOTICE 'nexus_ai.messages copy verified: % rows', dst;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Swap names. Free the canonical constraint/index names first, keeping the
--    old table fully intact as a backup under *_old_backup names.
-- ---------------------------------------------------------------------------
ALTER TABLE nexus_ai.messages RENAME TO messages_old_backup;
ALTER TABLE nexus_ai.messages_old_backup RENAME CONSTRAINT messages_pkey TO messages_old_backup_pkey;
ALTER TABLE nexus_ai.messages_old_backup RENAME CONSTRAINT messages_session_id_fkey TO messages_old_backup_session_id_fkey;
ALTER INDEX nexus_ai.ix_nexus_ai_messages_session_id RENAME TO ix_messages_old_backup_session_id;

ALTER TABLE nexus_ai.messages_new RENAME TO messages;
ALTER TABLE nexus_ai.messages RENAME CONSTRAINT messages_new_pkey TO messages_pkey;

-- ---------------------------------------------------------------------------
-- 5. Foreign key (ON DELETE CASCADE) — the app relies on session deletes
--    cascading to messages.
-- ---------------------------------------------------------------------------
ALTER TABLE nexus_ai.messages
    ADD CONSTRAINT messages_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES nexus_ai.sessions(id) ON DELETE CASCADE;

-- ---------------------------------------------------------------------------
-- 6. Indexes. The history-replay query is
--        WHERE session_id = ? ORDER BY created_at DESC LIMIT 20
--    so the session_id index is (session_id, created_at DESC) to serve it
--    with an index scan, no sort.
-- ---------------------------------------------------------------------------
CREATE INDEX ix_nexus_ai_messages_session_id
    ON nexus_ai.messages (session_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 7. Preserve ownership + GRANTs exactly as the original table had them.
--    (Original owner: gg_fighter; grants: nexus_briefing arw, nexus_admin r.)
-- ---------------------------------------------------------------------------
ALTER TABLE nexus_ai.messages OWNER TO gg_fighter;
DO $$
DECLARE
    p record;
BEGIN
    FOR p IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits i ON i.inhrelid = c.oid
        WHERE n.nspname = 'nexus_ai' AND i.inhparent = 'nexus_ai.messages'::regclass
    LOOP
        EXECUTE format('ALTER TABLE nexus_ai.%I OWNER TO gg_fighter', p.relname);
    END LOOP;
END
$$;

GRANT INSERT, UPDATE, SELECT ON nexus_ai.messages TO nexus_briefing;
GRANT SELECT ON nexus_ai.messages TO nexus_admin;

COMMENT ON TABLE nexus_ai.messages IS
    'Monthly RANGE-partitioned on created_at (migration 014). Retention = DROP old partitions via nexus_ai.drop_old_message_partitions().';

-- ---------------------------------------------------------------------------
-- 8. Retention helper — DROP (never DELETE) partitions whose range ends on or
--    before now - `months` months. Keeps the last `months` full months.
--    NOT scheduled here; the operator/parent decides when to call it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION nexus_ai.drop_old_message_partitions(months int DEFAULT 12)
RETURNS TABLE(dropped_partition text)
LANGUAGE plpgsql
AS $$
DECLARE
    rec        record;
    cutoff     timestamptz;
BEGIN
    IF months < 1 THEN
        RAISE EXCEPTION 'months must be >= 1 (got %)', months;
    END IF;

    -- Start of the month `months` months ago, in Hong Kong local time.
    cutoff := (date_trunc('month', (now() AT TIME ZONE 'Asia/Hong_Kong'))
               - make_interval(months => months)) AT TIME ZONE 'Asia/Hong_Kong';

    FOR rec IN
        SELECT c.relname AS rel,
               (regexp_match(pg_get_expr(c.relpartbound, c.oid),
                             'TO \(''([^'']+)''\)'))[1]::timestamptz AS upper_bound
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_inherits  i ON i.inhrelid = c.oid
        JOIN pg_class     p ON p.oid = i.inhparent
        WHERE n.nspname = 'nexus_ai'
          AND p.relname = 'messages'
          AND c.relispartition
          AND c.relname LIKE 'messages\_%'
          AND c.relname <> 'messages_default'
        ORDER BY 2
    LOOP
        -- upper_bound is exclusive; drop when the whole partition is older
        -- than the cutoff. DEFAULT partition (NULL bound) is never dropped.
        IF rec.upper_bound IS NOT NULL AND rec.upper_bound <= cutoff THEN
            EXECUTE format('DROP TABLE nexus_ai.%I', rec.rel);
            dropped_partition := rec.rel;
            RETURN NEXT;
        END IF;
    END LOOP;
END
$$;

ALTER FUNCTION nexus_ai.drop_old_message_partitions(int) OWNER TO gg_fighter;
COMMENT ON FUNCTION nexus_ai.drop_old_message_partitions(int) IS
    'DROP (not DELETE) monthly message partitions whose range ends on/before now - months. Default 12 => keep >= 1 year. Returns dropped partition names.';

COMMIT;

-- 026: Error monitoring — 未處理錯誤 / 5xx 落地（Critical item）
--
-- 背景：admin 只有 /reports/error-rate（計 AI call 失敗率），冇全站錯誤記錄。
-- 目標：任何未處理 exception 或 5xx response 都留底（時間、路徑、類型、traceback 截斷），
--       可以按 tenant / 路徑 / 時間查 —— 出事唔需要靠 user 報告。
--
-- 安全：
--   - **唔記 request body / headers**（避免 secrets 落 log）
--   - message / traceback 各截斷 4000 字
--   - RLS FORCE：app role 只可以讀自己 tenant 嘅 row；INSERT 永遠允許
--     （middleware 之前爆嘅請求可能冇 tenant context → tenant_id = NULL）
--   - 跨 tenant 讀取只可以經 admin session（BYPASSRLS）

BEGIN;

CREATE TABLE IF NOT EXISTS nexus_ai.error_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    tenant_id    uuid,
    user_id      uuid,
    request_id   text,
    method       varchar(10),
    path         text,
    status_code  integer,
    error_type   varchar(200),
    message      text,
    traceback    text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_error_events_time
    ON nexus_ai.error_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_events_path
    ON nexus_ai.error_events (path, occurred_at DESC);

ALTER TABLE nexus_ai.error_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_ai.error_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON nexus_ai.error_events;
CREATE POLICY tenant_isolation ON nexus_ai.error_events
    FOR SELECT
    USING (tenant_id IS NOT NULL
           AND tenant_id::text = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS insert_any ON nexus_ai.error_events;
CREATE POLICY insert_any ON nexus_ai.error_events
    FOR INSERT
    WITH CHECK (true);

-- ⚠️ 一定要 GRANT（2026-09-12 踩過：淨係建表 → app role `permission denied`）
--   gg_fighter（app 連線角色）：只可以讀自己 tenant + 寫入（寫入係核心功能）
--   nexus_admin（BYPASSRLS，admin 報表／清理）：讀 + 刪（retention）
GRANT SELECT, INSERT ON nexus_ai.error_events TO gg_fighter;
GRANT SELECT, DELETE ON nexus_ai.error_events TO nexus_admin;

COMMIT;

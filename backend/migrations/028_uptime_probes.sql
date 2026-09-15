-- 028: Status page — uptime probes（uptime + incident）
--
-- 背景：完全冇任何 uptime 記錄。error_events 只記「有錯誤」，唔等於「服務 down」
--       （服務冧咗可能連 request 都入唔到 → 冇 row）。
-- 設計：一個 probe job 定時探幾個服務 → 寫呢張表；**incident 由連續失敗推導**
--       （唔另開 incident 表 → 冇 state 可以漂移）。
--
-- ⚠️ **冇 tenant_id、冇 RLS** —— uptime 係平台基建數據，唔屬任何 tenant。
--    （唔好為咗「同其他表一致」而硬加 tenant 欄。）
-- ⚠️ 建表一定要同時 GRANT（2026-09-12 踩過：淨係建表 → app role permission denied）

BEGIN;

CREATE TABLE IF NOT EXISTS nexus_ai.uptime_probes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    probe_name  varchar(60) NOT NULL,   -- main_api / admin_api / admin_web
    target      text NOT NULL,          -- 探嘅 URL
    ok          boolean NOT NULL,
    status_code int,
    latency_ms  int,
    error       text,                   -- 連唔到時記 exception（唔記 response body）
    checked_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uptime_probes_name_time
    ON nexus_ai.uptime_probes (probe_name, checked_at DESC);

-- retention 用（清舊 probe）
CREATE INDEX IF NOT EXISTS idx_uptime_probes_time
    ON nexus_ai.uptime_probes (checked_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_ai.uptime_probes TO gg_fighter;
GRANT SELECT, DELETE ON nexus_ai.uptime_probes TO nexus_admin;

COMMIT;

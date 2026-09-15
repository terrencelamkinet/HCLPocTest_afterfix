-- 027: Prompt eval — 跑 prompt 版本嘅 eval（回歸 / 比較用）
--
-- 背景：`nexus_ai.prompt_templates` 有 version + is_active/unique(tenant,key,version)（版本管理 ✅），
--       但完全冇 eval —— 改完 prompt 冇任何方法知道「改好咗定改壞咗」。
-- 設計：一次 run = 一組 case 對某個 (tenant, key, version) 跑；逐條 case 用確定性斷言評分。
--       落庫做歷史，可以比較兩個版本嘅分數（今次唔做 UI，AI/system 層見得到就夠）。
--
-- ⚠️ 建表一定要同時 GRANT（2026-09-12 踩過：淨係建表 → app role permission denied）

BEGIN;

CREATE TABLE IF NOT EXISTS nexus_ai.prompt_eval_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL,
    prompt_key      varchar(100) NOT NULL,
    prompt_version  int NOT NULL,
    model           varchar(100),
    total           int NOT NULL DEFAULT 0,
    passed          int NOT NULL DEFAULT 0,
    failed          int NOT NULL DEFAULT 0,
    duration_ms     int,
    created_by      uuid,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompt_eval_runs_tenant
    ON nexus_ai.prompt_eval_runs (tenant_id, prompt_key, created_at DESC);

CREATE TABLE IF NOT EXISTS nexus_ai.prompt_eval_cases (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          uuid NOT NULL REFERENCES nexus_ai.prompt_eval_runs(id) ON DELETE CASCADE,
    tenant_id       uuid NOT NULL,
    case_key        varchar(100) NOT NULL,
    passed          boolean NOT NULL,
    reason          text,
    output_excerpt  text,
    latency_ms      int,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompt_eval_cases_run
    ON nexus_ai.prompt_eval_cases (run_id);

-- ── RLS（同其他 nexus_ai 表一致：FORCE + tenant policy）──
ALTER TABLE nexus_ai.prompt_eval_runs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_ai.prompt_eval_runs  FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_ai.prompt_eval_runs;
CREATE POLICY tenant_isolation ON nexus_ai.prompt_eval_runs
    USING (tenant_id::text = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));

ALTER TABLE nexus_ai.prompt_eval_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_ai.prompt_eval_cases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON nexus_ai.prompt_eval_cases;
CREATE POLICY tenant_isolation ON nexus_ai.prompt_eval_cases
    USING (tenant_id::text = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));

-- ── GRANT ──
GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_ai.prompt_eval_runs  TO gg_fighter;
GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_ai.prompt_eval_cases TO gg_fighter;
GRANT SELECT, DELETE ON nexus_ai.prompt_eval_runs  TO nexus_admin;
GRANT SELECT, DELETE ON nexus_ai.prompt_eval_cases TO nexus_admin;

COMMIT;

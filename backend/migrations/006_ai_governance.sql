-- 006_ai_governance.sql
-- AI CRM Agent 治理層 (架構文檔 §Database Schema 擴充建議)
--  1) 各表加 AI 治理欄位：來源追蹤、信心度、去重狀態、完整度
--  2) 新建 ai_agent_log — 每次 Agent 執行嘅完整推理鏈審計

-- ── Contacts: 追蹤資料來源同可信度 ──────────────────────────
ALTER TABLE nexus_crm.contacts
    ADD COLUMN IF NOT EXISTS source_signal_id UUID,          -- 觸發訊號 (name_card.id / email.id / meeting.id)
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(4,3),  -- 0.000-1.000 提取信心
    ADD COLUMN IF NOT EXISTS dedup_status TEXT DEFAULT 'none', -- none | auto_matched | llm_review | unresolved | user_override
    ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ;   -- 上次 AI/人手驗證時間

-- ── Company: 標記 AI 補全欄位同完整度 ────────────────────────
ALTER TABLE nexus_crm.companies
    ADD COLUMN IF NOT EXISTS enriched_by_ai BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS enrichment_source_url TEXT,     -- 擴充來源 (官網/商業登記/新聞)
    ADD COLUMN IF NOT EXISTS data_completeness_pct SMALLINT DEFAULT 0;  -- 0-100 欄位完整率

-- ── Touchpoints: 多渠道聯絡方式溯源 ──────────────────────────
ALTER TABLE nexus_crm.touchpoints
    ADD COLUMN IF NOT EXISTS channel_type TEXT,              -- meeting | call | email | social | other
    ADD COLUMN IF NOT EXISTS extracted_from TEXT;            -- namecard | email | meeting | manual

-- ── Tasks: AI 推測關聯標記 ──────────────────────────────────
ALTER TABLE nexus_crm.tasks
    ADD COLUMN IF NOT EXISTS auto_suggested BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suggestion_confidence NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS linked_via_signal UUID;         -- 觸發呢個建議嘅訊號 ID

-- ── ai_agent_log: Agent 執行審計 (完整推理鏈) ────────────────
CREATE TABLE IF NOT EXISTS nexus_crm.ai_agent_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL,          -- namecard | email | meeting | manual
    signal_id UUID,                     -- 原始訊號 ID (name_card.id 等)
    agent_name TEXT NOT NULL,           -- ingestion | extraction | entity_resolution | enrichment | inference
    agent_version TEXT,                 -- prompt/model 版本標記
    provider TEXT,                      -- deepseek | perplexity | heuristic
    model TEXT,                         -- 實際 model 名
    input_snapshot JSONB,               -- 輸入快照 (觸發資料)
    output_snapshot JSONB,              -- 輸出快照 (判斷結果)
    confidence NUMERIC(4,3),            -- 信心分數 0-1
    decision TEXT,                      -- agent 建議決策 (auto_link | review | create | enrich | suggest)
    user_decision TEXT,                 -- 用戶最終決策 (accept | reject | override | none)
    latency_ms INTEGER,                 -- 執行時間
    success BOOLEAN DEFAULT TRUE,       -- 有冇 fail-safe fallback
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_agent_log_signal ON nexus_crm.ai_agent_log(signal_id);
CREATE INDEX IF NOT EXISTS idx_ai_agent_log_agent ON nexus_crm.ai_agent_log(agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_agent_log_tenant ON nexus_crm.ai_agent_log(tenant_id, created_at DESC);

-- 舊 name_cards 補 default（安全）
ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS dedup_status TEXT;  -- 同步 expose 去重狀態

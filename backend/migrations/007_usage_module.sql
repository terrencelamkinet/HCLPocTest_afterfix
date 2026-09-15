-- 007_usage_module.sql
-- Add module attribution + currency to LLM usage events so every LLM-calling
-- module can be cost/token-tracked centrally (core rule: every LLM call site
-- MUST record a UsageEvent row with its module name).
--
-- Cost currency: ALL provider cost cards are USD (per-1K-token prices in
-- base.py compute_cost / deepseek.py _DEEPSEEK_COST_CARDS). The currency
-- column makes this explicit at the data level.

ALTER TABLE nexus_ai.usage_events
    ADD COLUMN IF NOT EXISTS module VARCHAR(50) NOT NULL DEFAULT 'chat';

ALTER TABLE nexus_ai.usage_events
    ADD COLUMN IF NOT EXISTS currency VARCHAR(10) NOT NULL DEFAULT 'USD';

CREATE INDEX IF NOT EXISTS idx_usage_events_module
    ON nexus_ai.usage_events (module, created_at DESC);

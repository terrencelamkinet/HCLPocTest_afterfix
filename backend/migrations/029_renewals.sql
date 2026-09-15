-- 029: Renewal Radar — 合約／訂閱到期追蹤
--
-- 背景：完全冇任何 renewal 概念（DB 冇表、model 冇 field）→ 用戶會唔記得客戶合約／訂閱
--       ／licence 幾時到期 → 白白走失續約生意。亦冇任何「到期前提醒」機制。
-- 設計（Less is more）：唔砌一個完整「合約管理模組」，只做追蹤 + 到期前提醒所需嘅欄。
--
-- ⚠️ tenant 數據 → **FORCE RLS**（跟 migration 022 嘅 app-owned tenant 表慣例）
-- ⚠️ 建表一定要同時 GRANT（2026-09-12 踩過：淨係建表 → app role permission denied）

BEGIN;

CREATE TABLE IF NOT EXISTS nexus_crm.renewals (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
    workspace_id     uuid NOT NULL,
    name             text NOT NULL,                     -- 合約／訂閱／licence 名
    company_id       uuid REFERENCES nexus_crm.companies(id) ON DELETE SET NULL,  -- 對方
    amount           numeric(14,2),                     -- 續約金額（可空）
    currency         varchar(3) DEFAULT 'HKD',
    renewal_date     date NOT NULL,
    notice_days      int NOT NULL DEFAULT 30,           -- 提前幾多日提醒
    owner_id         uuid REFERENCES nexus_auth.nexus_auth_users(id) ON DELETE SET NULL,
    status           varchar(20) NOT NULL DEFAULT 'active',  -- active / renewed / cancelled
    notes            text,
    last_notified_at timestamptz,                       -- 提醒去重（唔好日日嘈）
    created_by       uuid,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_renewals_due
    ON nexus_crm.renewals (tenant_id, renewal_date) WHERE status = 'active';

ALTER TABLE nexus_crm.renewals ENABLE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.renewals FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON nexus_crm.renewals;
CREATE POLICY tenant_isolation ON nexus_crm.renewals
    USING (tenant_id::text = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON nexus_crm.renewals TO gg_fighter;
GRANT SELECT, DELETE ON nexus_crm.renewals TO nexus_admin;

COMMIT;

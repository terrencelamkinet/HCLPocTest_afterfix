-- 022_force_rls_app_owned_tenant_tables.sql
-- 2026-09-12  •  Notion: [Security] generated_briefings 補 FORCE RLS（範圍已擴大）
--
-- 問題
--   app 主連線 role = gg_fighter（app/config.py database_url default；pg_stat_activity 實證），
--   而以下 15 張表嘅 OWNER 亦係 gg_fighter，只 ENABLE 咗 RLS、冇 FORCE。
--   PostgreSQL 規則：relforcerowsecurity=false 時 table owner 豁免 RLS →
--   tenant_isolation policy 形同虛設。
--   實證（SET ROLE gg_fighter，未 set app.tenant_id）：
--     generated_briefings → 13,850 rows / 14 個 tenant 全部睇到
--     companies（已 FORCE）→ 0 rows
--
-- 修法
--   FORCE ROW LEVEL SECURITY：令 policy 對 owner（= app 條連線）一樣生效，
--   同其他 40+ 張已 FORCE 嘅表（companies / contacts / notes / projects / deals …）行為一致。
--
-- 安全前提（已逐項驗證）
--   1. app/db.py:79 每個 request 都 SELECT set_config('app.tenant_id', :tid, true)（＋ app.user_id）
--   2. 40+ 張表已 FORCE 且 owner 同為 gg_fighter，app 一直正常運作 → app session 本身已滿足 RLS 前提
--   3. briefing_scheduler.py 用 nexus_briefing（非 owner → RLS 一向已生效；L358/477/585 有 set GUC）
--   4. db_admin.py 用 nexus_admin（rolbypassrls=true，admin console 刻意繞過）
--   5. 每張表都已有 tenant policy（workflow_app_runs 除外 → 已剔出，見下）
--
-- 唔包括 workflow_app_runs：0 條 policy + 完全冇 tenant_id column → FORCE 落去會變全 deny。
--   該表 code 只有一個 model class（models/crm_module_c.py:475）、無任何 query 使用，疑似 legacy，
--   另案決定（drop / 補 policy / 唔郁）。
--
-- 副作用（已知）
--   ・讀取：冇 GUC 就靜默 0 rows（AGENTS.md pitfall #10）
--   ・寫入：冇 GUC 會 raise「new row violates row-level security policy」（ERROR，唔係靜默）
--
-- Rollback（即時、唔改資料）
--   ALTER TABLE nexus_crm.<tbl> NO FORCE ROW LEVEL SECURITY;

BEGIN;

ALTER TABLE nexus_crm.activity_log              FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.contact_projects          FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.custom_field_definitions  FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.custom_field_values       FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_line_items           FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_pipelines            FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.deal_stages               FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.generated_briefings       FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.products                  FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.project_calendar_events   FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.project_stages            FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.quote_items               FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.quotes                    FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.sales_reports             FORCE ROW LEVEL SECURITY;
ALTER TABLE nexus_crm.tags                      FORCE ROW LEVEL SECURITY;

-- 驗證：應該返 15（0 = 全部已 FORCE）
SELECT count(*) AS still_unforced_should_be_0
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'nexus_crm' AND c.relkind = 'r'
  AND pg_get_userbyid(c.relowner) = 'gg_fighter'
  AND c.relrowsecurity AND NOT c.relforcerowsecurity
  AND c.relname <> 'workflow_app_runs';

COMMIT;

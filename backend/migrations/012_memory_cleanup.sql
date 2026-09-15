-- 012_memory_cleanup.sql
-- One-time hygiene pass over nexus_ai.user_memory (CRM AI cross-session memory).
--
-- Audited state (2026-09-10): 32 rows, of which
--   * exact duplicates: '用戶使用eClass系統處理學校事務' x2,
--     '用戶子女就讀聖公會聖約瑟小學' x2 (plus near-dups)
--   * one parent-evening / eClass-notice event split into 8+ near-identical rows
--   * 5 stale August daily rollups (nothing expires them server-side)
--   * junk sources: 'Session aaaa…', 'Session Question: 我是誰？'
--   * low-value rows: '用戶可能為…學生的家長', 'Jerry at NETAPP … no detail'
--   * every non-daily row had confidence hardcoded to 0.7
--
-- Result: 8 durable rows — consolidated, Traditional-Chinese content,
-- honest per-row confidence (0.7–0.95), clean source labels.
--
-- RLS: nexus_ai.user_memory has FORCE ROW LEVEL SECURITY with policy
--     tenant_id::text = current_setting('app.tenant_id', true)
-- Every block below sets the tenant GUC exactly the way
-- app/db.py::get_tenant_session does (set_config(..., is_local => true),
-- i.e. transaction-scoped). A superuser run bypasses RLS; an owner
-- (gg_fighter) run relies on these GUCs — either way the same rows change.
--
-- Idempotent: DELETE-by-id and UPDATE-by-id are safe to re-run.

BEGIN;

-- ── junk / all-zero test tenant ───────────────────────────────────────
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);
-- test daily rollup of "確認NEXUS CRM運行正常" — pure noise
DELETE FROM nexus_ai.user_memory WHERE id IN (
    '0991f823-4a6b-402c-8c71-d9cce1f5bed4'
);

-- ── primary tenant (0000…0001) ────────────────────────────────────────
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000001', true);

-- junk sources + stale daily rollups + low-value + duplicates
DELETE FROM nexus_ai.user_memory WHERE id IN (
    '88d0cc92-3ca7-4a70-b0c8-90217e32650b',  -- 'Session aaaa…' (merged into 7d2e27fe)
    'a7414621-f14c-41ac-9899-b0f4ba8b389e',  -- 'Session Question: 我是誰？' (merged)
    '9d92c967-e3bf-4dc3-b5e3-f4444f442243',  -- low value: "Jerry at NETAPP … no detail"
    '34412ee2-666d-4c8e-ac0f-0ac29fa671ae',  -- low value: describes the CRM itself
    '3f12495f-12f4-47b7-a5fb-f59fb079c4b3',  -- stale daily rollup 2026-08-05
    'e52c8124-3888-4056-8c9c-b30a81803f11',  -- stale daily rollup 2026-08-06
    '2a81be99-326e-46d2-8431-b28b62ced729',  -- stale daily rollup 2026-08-10
    '9395b955-a1e4-4955-a38b-3d82fdb4374b',  -- dup topic (merged into a05a80b0)
    '0531b39a-bf0c-458c-9314-e8dbfbadde28',  -- dup: 子女就讀… (keep 1d94cff9)
    '8f1be35f-0c8b-4b80-9398-9b0aa146fede',  -- parent-evening split (keep d91bf372)
    '693422be-e613-40fa-b24f-eacc3cbecff5',  -- dup eClass (keep df9c23bb)
    'bc6af992-492d-49f1-a6c9-3b700e746105',  -- parent-evening split
    '0b1601d1-2dcd-47dc-9530-70d400f57c66',  -- parent-evening split
    '230d08f4-b564-46e7-99d4-ab8d7a781c4d',  -- dup Cantonese pref (keep 662b27d5)
    '0a4bec8d-a353-4f44-8a1c-0062d123e999',  -- low value: "用戶可能為…"
    '449871d6-28ba-4040-b122-17cb50c9b4ea',  -- parent-evening split
    'c9141280-e10f-43c5-b1ae-472f405afd01',  -- dup calendar pref (keep d8ae3387)
    '841f5e6a-0f87-4337-9f4b-246cd2d46fc6',  -- parent-evening split
    '291adeb0-b7de-4b34-947a-d844ba484844'   -- school contact (merged into 1d94cff9)
);

-- survivors: consolidate content, translate to 繁體中文, set honest confidence
UPDATE nexus_ai.user_memory SET
    content    = '用戶與 SYSTEX Information (H.K.) Ltd. 有業務往來；主要聯絡人：Wilson Chan、Vincent Chan、Jerry Chan（陳俊榮，jerry.chan@systex.com.hk，+852 6359 1613）。',
    source     = 'CRM 聯絡人記錄',
    confidence = 0.8
WHERE id = '7d2e27fe-caad-4d3b-b2e9-3b6f8e35ba8a';

UPDATE nexus_ai.user_memory SET
    content    = '用戶與 Manulife 有業務往來，需跟進其報價（到期日 2026-09-30）。',
    source     = '任務記錄',
    confidence = 0.7
WHERE id = 'a05a80b0-7940-48b5-b757-c232c058d2c3';

UPDATE nexus_ai.user_memory SET
    content    = '用戶子女就讀聖公會聖約瑟小學（學校聯絡人：李美鳳副校長）。',
    source     = '對話記錄',
    confidence = 0.9
WHERE id = '1d94cff9-f6e4-4312-9fd3-26ae83699058';

UPDATE nexus_ai.user_memory SET
    content    = '用戶使用 eClass 系統處理學校事務。',
    source     = '對話記錄',
    confidence = 0.8
WHERE id = 'df9c23bb-06c5-48d4-8bf6-8270029e3a4d';

UPDATE nexus_ai.user_memory SET
    content    = '用戶需出席 2026-09-15 於聖公會聖約瑟小學舉行的家長晚會（晚上 6:30–8:15），並於 2026-09-07 前回覆 eClass 回條。',
    source     = '對話記錄',
    confidence = 0.8
WHERE id = 'd91bf372-189d-4d05-8923-d5ba74a500c1';

UPDATE nexus_ai.user_memory SET
    content    = '用戶偏好以 CRM 任務方式記錄行事曆事項，並期望系統自動同步至行事曆。',
    source     = '對話偏好',
    confidence = 0.7
WHERE id = 'd8ae3387-e5d2-4e33-b1ea-2ad9c208162d';

-- ── tenant edc6add4 (all duplicates of the primary user's school facts) ─
SELECT set_config('app.tenant_id', 'edc6add4-c2e2-4178-a982-978992a4ed80', true);
DELETE FROM nexus_ai.user_memory WHERE id IN (
    '4f13d5b0-2c6d-4daf-be42-2943a6f3e88e',
    '532847ad-36e6-4244-8e03-6c438f983e49',
    'd98a2d75-8321-422d-b8a4-acbfe55216af'
);

-- ── tenant feadc447 (stale daily rollup) ──────────────────────────────
SELECT set_config('app.tenant_id', 'feadc447-6c20-4499-9d0c-87b16709d46d', true);
DELETE FROM nexus_ai.user_memory WHERE id IN (
    'a8c302f1-4c63-465e-a0ec-a6dfb23760e8'
);

-- ── tenant 6c5843c2 (consolidate / translate) ─────────────────────────
SELECT set_config('app.tenant_id', '6c5843c2-b51d-482d-8f5f-66f560331bf5', true);

UPDATE nexus_ai.user_memory SET
    content    = '用戶使用粵語（廣東話）溝通，偏好以粵語進行交流。',
    source     = '對話偏好',
    confidence = 0.95
WHERE id = '662b27d5-cf4d-4fd4-bdb4-0338bd6b0924';

UPDATE nexus_ai.user_memory SET
    content    = '用戶與 H3C（新華三集團）有業務往來，聯絡人為周卓賢（Albert Chau），電郵 albert.chau@h3c.com。',
    source     = 'CRM 聯絡人記錄',
    confidence = 0.8
WHERE id = '351fc5bc-f920-41aa-9025-01681df9379a';

COMMIT;

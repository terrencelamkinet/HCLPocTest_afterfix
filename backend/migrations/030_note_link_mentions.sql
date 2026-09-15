-- 030_note_link_mentions.sql
-- Notes V2 — @mention → nexus_crm.note_links 真正建立關係
--
-- 跟 AI_AGENT_CRM_JSON_PostgreSQL_Configuration_Guide §5.3 / §7 / §13 / §15：
--   ① link 由 server 驗證過嘅 canonical content 推導（唔信 client 送嘅 array）
--   ② 編輯後要刪走唔再存在嘅 link（§15-2）
--   ③ 同一 object 被 @ 幾次 → 一行 + mention_count（§15-3）
--   ④ 反向查詢（object → 相關 notes）要行 index（§13）
--
-- 背景（2026-09-13 實測）：note_links 表一直存在，但只有「人手加 link」同
--   「AI suggestion 確認」兩條寫入路徑 —— 由筆記內容 @ 出嚟嘅 chip 從來冇
--   寫入過任何 row（SELECT count(*) = 0，而 10 篇 live note 都冇 mention）。
--
-- Idempotent：可以安全重複執行。
--
-- Rollback：
--   DROP INDEX IF EXISTS nexus_crm.idx_note_links_entity;
--   ALTER TABLE nexus_crm.note_links DROP CONSTRAINT IF EXISTS chk_note_links_source;
--   ALTER TABLE nexus_crm.note_links DROP COLUMN IF EXISTS mention_count;
--   ALTER TABLE nexus_crm.note_links DROP COLUMN IF EXISTS source;
--   （沒有資料遺失：新增欄位都係 metadata）

-- ── source：區分 link 來源 ─────────────────────────────────────────────
-- sync 只可以刪自己抽嘅 source='mention' row；人手加／AI 確認嘅 'manual' 永久保留。
-- 現有 row（如有）一律當 'manual'（保守，唔會俾新 sync 刪走）。
ALTER TABLE nexus_crm.note_links
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'manual';

COMMENT ON COLUMN nexus_crm.note_links.source IS
    'mention = 由 note content 自動抽出；manual = 人手加 / AI suggestion 確認（sync 不會刪）';

-- ── mention_count：同一 object 喺文內出現次數（spec §15-3）─────────────
ALTER TABLE nexus_crm.note_links
    ADD COLUMN IF NOT EXISTS mention_count integer NOT NULL DEFAULT 1;

-- ── 約束：source 只准兩個值 ───────────────────────────────────────────
ALTER TABLE nexus_crm.note_links
    DROP CONSTRAINT IF EXISTS chk_note_links_source;
ALTER TABLE nexus_crm.note_links
    ADD CONSTRAINT chk_note_links_source
    CHECK (source IN ('mention', 'manual'));

-- ── 反向查詢 index（spec §13：object → 相關 notes 唔可以 seq scan）──────
CREATE INDEX IF NOT EXISTS idx_note_links_entity
    ON nexus_crm.note_links (tenant_id, entity_type, entity_id);

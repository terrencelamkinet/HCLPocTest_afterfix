-- 008_bible_progress_config_fingerprint.sql
-- 讀經進度：加 config_fingerprint — 用戶改讀經設定（plan/book_selection/
-- start_book/start_chapter/end_book/end_chapter/chapters_per_push）時
-- day_index 自動 reset 0，避免跳章/錯章（2026-08-26 事件：以西結書5
-- 起點設錯 → 用戶期望但以理書 3）。
-- 同時 backfill 現有 rows 嘅 fingerprint（NULL → 下次 generate 會 sync
-- 並 reset day_index，因為 fingerprint 唔 match）。

ALTER TABLE nexus_ai.bible_reading_progress
    ADD COLUMN IF NOT EXISTS config_fingerprint VARCHAR(64);

-- backfill: 現有 rows 設一個唔可能 match 嘅 fingerprint
-- （'legacy' 短 hash — 實際 code 計嘅 fingerprint 係 md5 hex 32 chars，
--  任何正常設定都唔會產生 'legacy' 呢個值）→ 下次 generate 一定 reset。
UPDATE nexus_ai.bible_reading_progress
SET config_fingerprint = 'legacy'
WHERE config_fingerprint IS NULL;

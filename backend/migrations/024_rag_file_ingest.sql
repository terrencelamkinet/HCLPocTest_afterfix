-- 024: T3 文件知識庫 — nexus_crm.files 加 content_hash（重複上載偵測）
--
-- 背景：nexus_crm.files 表已存在（storage_key / original_filename / mime_type /
-- file_size / uploaded_by）但從未使用（0 rows）。T3 用佢做「已上載文件」嘅記錄，
-- 需要多一個欄做內容指紋 → 同一份文件唔會重複入索引。
--
-- 注意：唔加 status / error 欄 —— ingest 係 all-or-nothing（先抽文字 + embed，
-- 成功先插入 file row），所以唔會出現「半生半死」嘅文件狀態。

BEGIN;

ALTER TABLE nexus_crm.files
    ADD COLUMN IF NOT EXISTS content_hash text;

-- 重複偵測：同一 tenant 用 hash 查
CREATE INDEX IF NOT EXISTS idx_files_tenant_content_hash
    ON nexus_crm.files (tenant_id, content_hash);

COMMIT;

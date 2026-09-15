-- 025: T5 — 文件／記錄層 AI 控制（准唔准 AI 用／機密級別／狀態）
--
-- 依據：one-user-one-tenant spec §4.3（classification）、§5.2/§5.3（ai_enabled /
-- document_status）、§7.1（retrieval 要 pre-filter）。
--
-- 設計取捨：**唔將 metadata 複製落 chunks**（spec §5.3 原本要求複製，但咁樣文件改
-- classification 就要連帶更新 N 條 chunk，必然漂移）。改為檢索時 JOIN documents 取最新
-- 狀態 —— 一個 source of truth。
--
-- 預設值刻意寬鬆（true / internal / approved）→ 現有 634 份 CRM 記錄 doc 唔會被過濾走。

BEGIN;

ALTER TABLE nexus_ai.vector_documents
    ADD COLUMN IF NOT EXISTS ai_enabled      boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS classification  text    NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS document_status text    NOT NULL DEFAULT 'approved';

-- 檢索 pre-filter 用（tenant + 可用性）
CREATE INDEX IF NOT EXISTS idx_vector_docs_retrieval
    ON nexus_ai.vector_documents (tenant_id, ai_enabled, document_status);

COMMIT;

-- 023: T1 語意檢索 — chunk embedding 加 HNSW 向量索引
--
-- 背景（實證 2026-09-12）：nexus_ai.vector_document_chunks 只有
--   vector_document_chunks_pkey (btree id) 同 idx_vector_chunks_tenant_ws (btree)
-- → 向量查詢 `ORDER BY embedding <=> :q LIMIT k` 只可以全表掃描（EXPLAIN 實測 Seq Scan）。
-- 489 rows 今日無感，但資料量一升就係 O(n) 每條 query。
--
-- pgvector 0.6.0 支援 HNSW；vector_cosine_ops 對應 search.py 用嘅 <=>（cosine distance）。
-- 呢個 index 唔改任何資料、唔改 RLS，可以隨時 DROP 回滾。

BEGIN;

CREATE INDEX IF NOT EXISTS idx_vector_chunks_embedding_hnsw
    ON nexus_ai.vector_document_chunks
    USING hnsw (embedding vector_cosine_ops);

COMMIT;

-- 驗證：
--   SELECT indexname FROM pg_indexes
--    WHERE tablename='vector_document_chunks' AND indexdef LIKE '%hnsw%';

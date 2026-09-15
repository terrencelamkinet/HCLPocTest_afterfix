-- 005_namecard_review.sql
-- NameCard LLM-enrichment: potential-duplicate candidates awaiting user resolution.

ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS review_candidates JSONB DEFAULT '[]'::jsonb;

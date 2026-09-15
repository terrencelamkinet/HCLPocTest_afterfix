-- 004_namecard_dual_images.sql
-- NameCard dual-image support: original + cropped versions, user-selectable default.
-- RLS v2 columns (visibility_scope / team_id / owner_user_id) untouched.

ALTER TABLE nexus_crm.name_cards
    ADD COLUMN IF NOT EXISTS original_image_url TEXT,
    ADD COLUMN IF NOT EXISTS cropped_image_url   TEXT,
    ADD COLUMN IF NOT EXISTS display_image       TEXT NOT NULL DEFAULT 'cropped';

-- 'no image at all' is a legal state after both versions are deleted.
ALTER TABLE nexus_crm.name_cards ALTER COLUMN display_image DROP NOT NULL;

-- Backfill: existing image_url is the original scan; no crop exists for them.
UPDATE nexus_crm.name_cards
   SET original_image_url = image_url,
       display_image      = 'original'
 WHERE original_image_url IS NULL AND image_url IS NOT NULL;

-- Sanity constraint on display_image values.
UPDATE nexus_crm.name_cards SET display_image = 'original'
 WHERE display_image NOT IN ('original', 'cropped');

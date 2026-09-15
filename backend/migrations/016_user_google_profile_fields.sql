-- 016_user_google_profile_fields.sql  (2026-09-11)
--
-- Google sign-in used to keep only email + sub, so a Google-created account landed
-- with an empty profile even though Google had told us plenty. These columns hold
-- what the ID token actually carries, plus the timezone Google does NOT provide.
--
--   avatar_url  <- claim "picture"   (Google-hosted headshot URL)
--   locale      <- claim "locale"    (e.g. zh-TW, en) — the account's language pref
--   timezone    <- NOT from Google. The ID token has no timezone at all, so the
--                  browser reports Intl.DateTimeFormat().resolvedOptions().timeZone
--                  (e.g. Asia/Hong_Kong) and the frontend sends it at login.
--
-- All nullable: accounts created before this, and password-only accounts, have no
-- Google profile to copy from and must keep working.
--
-- display_name already exists — it was simply never populated on the Google path.

ALTER TABLE nexus_auth.nexus_auth_users
    ADD COLUMN IF NOT EXISTS avatar_url TEXT,
    ADD COLUMN IF NOT EXISTS locale     TEXT,
    ADD COLUMN IF NOT EXISTS timezone   TEXT;

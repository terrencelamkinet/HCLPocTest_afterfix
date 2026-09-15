-- 015_google_signin.sql  (2026-09-11)
--
-- Sign in with Google — GIS ID-token flow.
--
-- We link a Google account to an EXISTING nexus_auth user by email. google_sub is
-- Google's stable per-account subject id: unlike an email address it never
-- changes (no rename, no re-issue on a different domain), so it is the durable
-- link. Email alone is not enough for a permanent binding.
--
-- Nullable on purpose: every existing account has no Google link yet, and a user
-- who signs in with a password forever keeps google_sub NULL. The partial unique
-- index only constrains rows that actually have a value.

ALTER TABLE nexus_auth.nexus_auth_users
    ADD COLUMN IF NOT EXISTS google_sub TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS nexus_auth_users_google_sub_key
    ON nexus_auth.nexus_auth_users (google_sub)
    WHERE google_sub IS NOT NULL;

-- 031_i18n_badgeJwt_httponly_cookie.sql
-- 2026-09-15 SAST / T11：登入頁 badge 文案要跟返事實。
-- 原文「JWT + refresh token 就緒 / ready」係描述「前端自己存 token」嘅舊設計；
-- v7.88.9 已經改成 httpOnly session cookie（前端碰唔到 token），文案要同步。
--
-- ⚠️ 重點：i18n 嘅 runtime 來源係 nexus_auth.i18n_entries
--    （app/routers/i18n.py → GET /api/v1/i18n/resources?locale=…
--      ← src/i18n/config.ts 用 i18next backend 去 fetch）。
--    src/i18n/locales/*.json 只係 build-time fallback / 離線用。
--    **改文案一定要兩邊都改**，否則 UI 會繼續顯示 DB 舊值（2026-09-15 中過）。
--
-- 呢個 UPDATE 係 idempotent（可以重跑）。

UPDATE nexus_auth.i18n_entries
   SET en         = 'HttpOnly session cookie ready',
       zh_tw      = 'HttpOnly session cookie 就緒',
       zh_cn      = 'HttpOnly session cookie 已就绪',
       updated_at = now(),
       updated_by = 'migration-031'
 WHERE key_path = 'login.badgeJwt'
   AND (en <> 'HttpOnly session cookie ready'
        OR zh_tw <> 'HttpOnly session cookie 就緒'
        OR zh_cn IS DISTINCT FROM 'HttpOnly session cookie 已就绪');

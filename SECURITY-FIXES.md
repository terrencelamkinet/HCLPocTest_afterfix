# HCL AppScan 360 — 修復報告（v7.88.10）

掃描：HCL AppScan 360 SAST，target `HCLPocTest-main.zip`，2026-09-15T05:45:07Z
結果：0 Critical / 92 High / 37 Medium / 0 Low = **129 findings**

## 總結

| Status | 數量 | 意思 |
|---|---|---|
| FIXED | **74** | 已改代碼 / 已刪檔案 |
| FP-ACCEPT | **55** | 誤報（附逐條理由，見 `appscan-129-status.csv`） |
| OPEN | **0** | — |

逐條 status + 證據：**`appscan-129-status.csv`**（issue_id, severity, rule, cwe, file, line, status, evidence）。

## 主要根治（唔係逐點補丁）

1. **Reflected XSS ×49（CWE-79）** — 根因係一批唔再使用嘅 legacy 頁面 + `dangerouslySetInnerHTML` 直接食 URL/API 字串。做法：刪走 25 個 legacy 頁；加 `src/lib/sanitizeHtml.ts`（前端）＋ `backend/app/services/html_sanitize.py`（`nh3`）＋ ORM 層 `Note.content` validator，令寫入 DB 前已消毒。
2. **localStorage 存 token ×11（CWE-20/CWE-922）** — 根因：JWT + refresh token 放 `localStorage`，XSS 一發即全取。做法：改成 **HttpOnly + Secure + SameSite=Lax cookie**（`nexus_at` / `nexus_rt`），前端 JS 完全碰唔到 token；後端喺 middleware edge 將 cookie 還原成內部 Bearer，幾百個 call site 唔使改；Google OAuth callback 亦唔再將 token 放 URL fragment。前端只留非敏感 session hint（email + 到期時間）。
3. **DB 憑證外洩風險 ×25（CWE-798）** — 根因：舊 migration／script 有硬編 DB URL、部分 `.env` 曾入過 git。做法：rotated DB 密碼（pgbouncer SCRAM verifier）、硬編值全部改讀環境變數、`backend/keys/` 同 `backend/.env` 加 `.gitignore` + `chmod 600`、加 `scripts/check_secrets.sh` 落 pre-commit hook（檔名 + 內容都會攔），並且**改寫 git history**清走所有舊 key／憑證 blob。
4. **Path traversal ×6 / XML injection ×1 / 例外處理 ×14** — 上傳檔名 `_safe_upload_name()`、`defusedxml` 解 XML、錯誤回覆改為分類訊息（唔再回原始 exception 文字）、log 由 info 降 debug。
5. **真 PII 清理** — 掃描範圍內嘅真客戶欄位匯出 script、真手機號（docstring／註解／測試常數）全部刪走或換成 placeholder。

## 驗證（唔係「睇 code」）

- Backend：`pytest tests/ -q` → **571 passed / 0 failed**（新增 24 條 SAST 回歸測試 + 7 條 cookie session 測試）
- Frontend：`vitest run` → **103 passed / 11 files**；`tsc -b` exit 0；`npm run build` 通過
- 真瀏覽器（Chromium）：cookie-only 登入 → `/dashboard`；`document.cookie` 讀唔到 token；
  `localStorage` 冇 JWT；reload 保持登入；AI SSE 串流正常；登出 → `/auth/me` 401
- Production 實測：登入 → 儀表板 → 登出全部通過；API health 200

## 未修／已接受（`FP-ACCEPT` 詳見 CSV）

- 22 條 `Authentication.Credentials.Unprotected`：命中的係 UUID / tenant id，唔係憑證
- 11 條 `Improper Handling of Exceptional Conditions`：本機 CLI 工具正常 print 統計落自己 terminal
- 4 條 SQL injection：全部係參數化 query 嘅 false positive
- 7 條 localStorage：UI 偏好設定（widget 排序、欄寬），唔含 token

## 環境要求（自架）

1. 自己 generate RS256 keypair：`openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out backend/keys/private.pem`
2. 自備 `backend/.env`（DB URL、JWT key 路徑、第三方 API key）— 唔好 commit
3. 本地 HTTP 開發要 `NEXUS_COOKIE_SECURE=false`（production HTTPS 保持 true）

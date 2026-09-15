#!/usr/bin/env bash
# Secret 檢查（2026-09-15 AppScan 修正）
#
# 目的：secret 唔准入 git。正確位置：
#   - 環境變數 / app config → backend/.env（0600，.gitignore）
#   - service account JSON、單獨 key 檔 → backend/.secrets/（0600，.gitignore）
#   - JWT RS256 keypair → backend/keys/（private 0600，.gitignore，路徑由 .env 控制）
#   - pgbouncer → /etc/pgbouncer/userlist.txt（0640 postgres:postgres）
#
# 由 .githooks/pre-commit 呼叫。緊急跳過：SKIP_SECRET_CHECK=1 git commit ...
set -uo pipefail

[ "${SKIP_SECRET_CHECK:-0}" = "1" ] && exit 0

FILES="$(git diff --cached --name-only --diff-filter=ACM || true)"
[ -z "$FILES" ] && exit 0

BAD=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    *.pem|*.key|*.p12|*.pfx|.git-credentials|*userlist.txt)
      BAD="$BAD
    [檔案] $f" ;;
    .env|*/.env|*/.env.*)
      case "$f" in
        *.env.example|*.env.sample) ;;
        *) BAD="$BAD
    [檔案] $f" ;;
      esac ;;
    .secrets/*|*/.secrets/*)
      BAD="$BAD
    [檔案] $f" ;;
  esac
done <<< "$FILES"

PATTERNS='^-----BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|postgres(ql)?://[A-Za-z_][A-Za-z0-9_]*:[^@/[:space:]]{6,}@'

while IFS= read -r f; do
  [ -z "$f" ] && continue
  H="$(git show ":$f" 2>/dev/null | grep -InE "$PATTERNS" | head -2 || true)"
  if [ -n "$H" ]; then
    LN="$(printf '%s' "$H" | head -1 | cut -d: -f1)"
    # 唔 print 命中內容（避免 secret 落入 terminal / log）
    BAD="$BAD
    [內容] $f 第 $LN 行命中 secret pattern"
  fi
done <<< "$FILES"

if [ -n "$BAD" ]; then
  printf '❌ secret 檢查唔過，唔准 commit：%s\n' "$BAD"
  printf '   正確位置：backend/.env 或 backend/.secrets/（兩者已 .gitignore，0600）\n'
  printf '   私鑰：backend/keys/private.pem（0600）；pgbouncer：/etc/pgbouncer/userlist.txt（0640）\n'
  printf '   確認係 false positive 先至用：SKIP_SECRET_CHECK=1 git commit ...\n'
  exit 1
fi
exit 0

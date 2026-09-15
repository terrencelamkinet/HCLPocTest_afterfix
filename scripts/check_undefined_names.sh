#!/usr/bin/env bash
# KB-040 — undefined-name gate。
#
# 為什麼要有：
#   commit 6b5c5d6 修「/resolve 雙重定義」時，連帶刪走 crm.py 236 行共用 helper
#   （_load_owned_note / _note_to_dict / _snapshot_revision_if_due …），但 call site 冇刪。
#   Python 唔會在 import 時報錯，只有真正行到嗰行才 NameError → notes autosave 靜靜地 500。
#   同類前科：a24ba9f 刪走 _resolve_image_file，名卡圖 route 一直 500。
#   → 呢類「刪咗定義、留返 call site」係重複風險，靠人手 review 一定再中。
#
# 用法：bash scripts/check_undefined_names.sh [file.py ...]
#   冇參數 = 掃 backend/app 全部；有參數 = 只掃指定檔案（pre-commit 用）。
# 退出碼：0 = 過；1 = 有 undefined name。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "⚠️  搵唔到 backend/venv/bin/python — 跳過 undefined-name 檢查"
  exit 0
fi
if ! "$PY" -c "import pyflakes" >/dev/null 2>&1; then
  echo "⚠️  pyflakes 未裝（pip install pyflakes）— 跳過 undefined-name 檢查"
  exit 0
fi

cd "$ROOT" || exit 0
if [ "$#" -gt 0 ]; then
  FILES=("$@")
else
  mapfile -t FILES < <(find backend/app -name '*.py' | sort)
fi
[ "${#FILES[@]}" -eq 0 ] && { echo "（冇 .py 要檢查）"; exit 0; }

OUT="$("$PY" -m pyflakes "${FILES[@]}" 2>&1 | grep -i "undefined name" || true)"

if [ -n "$OUT" ]; then
  echo "❌ pyflakes undefined name — 即係呼叫咗唔存在嘅函數／常數，runtime 一定 500："
  echo
  echo "$OUT"
  echo
  echo "   KB-040 正確手勢："
  echo "     1) 還原被刪嘅定義（git show <good-ref>:<path> 抽返 span），或"
  echo "     2) 連 call site 一齊改走。"
  echo "   ❌ 唔准用 try/except NameError、hasattr、globals().get() 去繞。"
  exit 1
fi

echo "✅ undefined-name 檢查通過（$((${#FILES[@]})) 個檔案）"

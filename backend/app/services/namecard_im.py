"""NameCard IM helpers — shared by Telegram & WhatsApp inbound flows.

One subprocess runner + one presentation formatter so both channels reply
identically to the 3-tier confidence routing (auto_link / review / created):

    HIGH (>0.95)  → 🔗 已連結現有聯絡人
    MEDIUM (0.7-0.95) → ⚠️ 疑似重複 → 用戶回覆「覆蓋」/「保留」
    LOW (<0.7)    → ✅ 已建立新聯絡人 (+ 弱提示)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

VENV_PY = str(Path(__file__).resolve().parents[2] / "venv" / "bin" / "python")
NAMECARD_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "upload_namecard_to_g08.py"


def run_script(args: list[str]) -> dict:
    """Run upload_namecard_to_g08.py (detect/upload/resolve) and parse JSON."""
    try:
        r = subprocess.run(
            [VENV_PY, str(NAMECARD_SCRIPT), *args],
            capture_output=True, text=True, timeout=180,
        )
        out = r.stdout.strip()
        if not out:
            return {"ok": False, "error": f"script no output (exit {r.returncode}): {r.stderr[-200:]}"}
        return json.loads(out)
    except Exception as e:  # noqa: BLE001 — IM flow must never crash the poller
        return {"ok": False, "error": str(e)}


def format_upload_result(res: dict) -> tuple[str, dict]:
    """3-tier reply for an upload result.

    Returns (message, review_state) — review_state = {"card_id": ...} when
    the card landed in review (caller should remember it for the follow-up),
    otherwise {}.
    """
    if not res.get("ok"):
        return f"⚠️ 上載失敗：{res.get('error', 'unknown error')}", {}
    status = res.get("status", "unknown")

    # ── Review tier (0.7-0.95): user decides overwrite vs keep-both ──
    if status == "review":
        cand = (res.get("review_candidates") or [{}])[0]
        card_id = res.get("name_card_id") or ""
        if cand and card_id:
            conf = cand.get("confidence")
            conf_txt = f"（信心 {conf:.0%}）" if isinstance(conf, (int, float)) else ""
            lines = [
                f"⚠️ 疑似重複{conf_txt}",
                f"名片：{res.get('contact_name') or '?'} · {res.get('company') or ''}",
                f"現有：{cand.get('name')} · {cand.get('company') or ''}",
            ]
            if cand.get("email") and cand.get("email") != res.get("email"):
                lines.append(f"現有 Email：{cand['email']}")
            if cand.get("reason"):
                lines.append(f"原因：{cand['reason']}")
            lines.append("")
            lines.append("回覆「覆蓋」= 用名片更新現有記錄")
            lines.append("回覆「保留」= 新增獨立記錄，兩者都留")
            return "\n".join(lines), {"card_id": card_id}

    # ── High tier (exact match) / created ──
    status_txt = {"created": "✅ 已建立新聯絡人", "matched": "🔗 已連結現有聯絡人"}.get(
        status, f"狀態：{status}"
    )
    lines = [f"{status_txt}並存入名片庫"]
    if res.get("contact_name"):
        lines.append(f"• 聯絡人：{res['contact_name']}")
    if res.get("email"):
        lines.append(f"• Email：{res['email']}")
    if res.get("company"):
        lines.append(f"• 公司：{res['company']}")
    if res.get("title"):
        lines.append(f"• 職位：{res['title']}")
    if res.get("context_note"):
        lines.append(f"📌 {res['context_note']}")
    return "\n".join(lines), {}


def format_resolve_result(res: dict, action: str) -> str:
    """Reply after a user decision on a review card."""
    if not res.get("ok"):
        return f"⚠️ 處理失敗：{res.get('error', 'unknown error')}"
    name = res.get("contact_name") or ""
    if action == "overwrite":
        return f"✅ 已用名片更新現有聯絡人{(' ' + name) if name else ''}"
    return f"✅ 已保留兩者，新增獨立聯絡人{(' ' + name) if name else ''}"


# Keyword sets shared by both channels
YES_WORDS = {"係", "是", "好", "yes", "y", "ok", "可以", "上載", "上傳", "upload"}
NO_WORDS = {"唔使", "不用", "no", "n", "取消", "cancel", "不要", "唔好"}
OVERWRITE_WORDS = {"覆蓋", "覆盖", "overwrite", "合併", "合拼", "更新"}
KEEP_WORDS = {"保留", "兩者", "keep", "keep_both", "新增", "分開"}


def match_intent(text: str, words: set[str]) -> bool:
    low = text.strip().lower()
    return low in words or low in {w.lower() for w in words}

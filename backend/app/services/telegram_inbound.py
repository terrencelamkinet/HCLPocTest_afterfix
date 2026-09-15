"""
Telegram AI Bridge — connects Telegram bot messages to the NEXUS AI engine.

Design (mirrors whatsapp_ai_bridge):
  - Telegram getUpdates long-polling (no public webhook URL needed)
  - Each inbound user message → internal AI chat (/api/v1/ai/chat) with the
    user's own SecretarySettings (tone / instructions / lang_pref) injected
    into the system prompt — per-user AI personality.
  - Reply sent back via sendMessage. Session persisted per chat per day so
    the AI remembers the conversation (same pattern as WhatsApp).

SOC 2:
  - CC6.1: Internal JWT (2min expiry) for cross-service AI calls
  - CC6.6: All internal calls via localhost
  - CC7.2: All AI interactions routed through platform's audit trail
"""
import uuid
import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from jose import jwt
from sqlalchemy import select, text as sa_text

from app.config import settings
from app.db import async_session
from app.models.telegram_bot import TelegramBotMapping
from app.models.ai.secretary_settings import SecretarySettings, ChannelCredential
from app.services.auth_service import _load_private_key
from app.services import telegram_service
from app.services import namecard_im
from app.services.secret_crypto import decrypt_secret
from app.services.im_routing import (
    CANCEL_TOKENS,
    CONFIRM_TOKENS,
    MessageOrigin,
    may_text_reply_claim,
    normalize_token,
)

# Routing/claim logging — every claim carries origin + consumer + gate reason so
# any swallowed message is visible in `journalctl -u nexus-crm`.
_routing_log = logging.getLogger("telegram_inbound.routing")

# NameCard pipeline helper (OCR detect + upload → G08 CRM)
NAMECARD_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "upload_namecard_to_g08.py"
PENDING_DIR = Path(__file__).resolve().parents[2] / "uploads" / "namecards" / "pending"
# Run the helper with the backend venv python so OpenCV/tesseract deps resolve
VENV_PY = Path(__file__).resolve().parents[2] / "venv" / "bin" / "python3"

AI_INTERNAL_URL = "http://localhost:8001/api/v1/ai"

# Telegram reply guidelines — base personality, then per-user tone/instructions
# appended from SecretarySettings. AI router strips client system messages, so
# this is prefixed into the user content (same approach as WhatsApp bridge).
TELEGRAM_BASE_PROMPT = (
    "你是 Penguin CRM 的專屬 AI 秘書，負責協助用戶處理 CRM 相關事務並提供專業意見。\n"
    "角色定位：\n"
    "- 你代表 Penguin CRM，以專業、簡潔、友善的語氣與用戶溝通\n"
    "- 你熟悉 Penguin CRM 的功能模組（客戶管理、銷售流程、報表分析、工作流程自動化等）\n"
    "- 你的目標是協助用戶更有效率地使用系統，並在需要時提供業務決策上的專業建議\n"
    "核心職責：\n"
    "1. 解答用戶關於 Penguin CRM 功能、操作流程的疑問，提供清晰步驟指引\n"
    "2. 根據用戶提供的資料（客戶紀錄、銷售數據、任務清單等），整理重點並提出可行建議\n"
    "3. 主動提醒重要事項，例如待跟進客戶、逾期任務、關鍵日期\n"
    "4. 遇到不確定或超出權限範圍的問題，應誠實告知並引導轉介人工客服\n"
    "溝通原則：\n"
    "- 回答簡潔直接，先給結論再補充細節\n"
    "- 使用用戶熟悉的業務術語，避免過度技術化解釋\n"
    "- 提供建議時附上依據（例如根據哪些數據或紀錄）\n"
    "- 不確定的資訊不要臆測，寧可請用戶確認或提供更多背景\n"
    "---\n"
    "Telegram reply rules:\n"
    "1. Be professional and structured. Use sections with emoji headers when showing CRM data:\n"
    "   📇 Contact / 🏢 Company / 📋 Tasks / 📅 Touchpoints / 🚀 Projects / 💼 Deals\n"
    "2. When asked about a person, include their related records too (company, tasks, touchpoints, projects) if present.\n"
    "3. Format: NO markdown symbols at all — no **, no *, no backticks. Use emoji headers and plain text only. Max 15 lines.\n"
    "4. For lists of CRM records use bullet list, one record per line, dash prefix:\n"
    "   - Name — detail\n"
    "5. Missing fields: say 未記錄 once, briefly — don't repeat it for every field.\n"
    "6. If you mention any CRM data (contacts/companies/deals), append this link at the end:\n"
    "   https://www.penguincrm.io\n"
    "7. Grouping: separate different topics with a blank line between groups. Each group starts with its emoji header. Never mix topics in one paragraph.\n"
    "8. First reply sets the language for the whole conversation — stick to it, never switch mid-reply.\n"
    "9. 現在日期：2026年8月22日（HKT）。用戶提到日期但冇寫年份時，一律用今年 2026 年，唔好用其他年份。\n"
    "10. 建立/更新 CRM 記錄（公司/聯絡人/任務/Touchpoint/項目）時：你唔可以只係口頭應承「我會建立」— 必須輸出 JSON 工具呼叫 block（喺回覆最尾，前面可以照常解釋），系統會顯示即將寫入嘅完整資料，用戶回「確認」就會執行（唔好用「草稿／draft」字眼）：\n"
    '    - 建立公司 → {"tool": "create_company_draft", "params": {"name": "公司全名", "industry": "...", "notes": "..."}}（name 必填）\n'
    '    - 建立聯絡人 → {"tool": "create_contact_draft", "params": {"name": "...", "email": "...", "company_name": "所屬公司全名", "phone": "...", "job_title": "..."}}（name 或 email 必填）\n'
    '    - 建立任務 → {"tool": "create_task_draft", "params": {"title": "...", "due_date": "YYYY-MM-DD", "priority": "low|medium|high|urgent"}}\n'
    '    - 建立 Touchpoint → {"tool": "create_touchpoint_draft", "params": {"type": "meeting|call|email|visit|other", "summary": "...", "company_name": "...", "date": "YYYY-MM-DD"}}\n'
    '    - 更新現有記錄 → update_company_draft / update_contact_draft / update_task_draft（params 帶 record id 或全名 + 要改嘅欄位）\n'
    "    一次過多項建立（例如公司＋幾個聯絡人）就輸出多個 JSON block。唔好問用戶「要唔要我建立」— 直接輸出工具呼叫。\n"
    "    **每個記錄都可以獨立建立，唔需要依附其他記錄**：Touchpoint 唔一定要有公司/聯絡人（淨 type + summary 就夠）；聯絡人唔一定要有公司；公司唔一定要有聯絡人。只有用戶明確講「呢個係 XX 公司嘅人／拜訪 XX 公司」先加 company_name 關聯，唔好擅自補。\n"
    "    回覆要精簡：寫入 preview 系統會自動顯示（✍️ 開頭），你嘅文字唔好重複列晒所有欄位細節，簡單講「以下就係會寫入嘅資料：」就夠，之後等用戶確認。\n"
)


def _make_internal_token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Generate a short-lived JWT for internal AI API calls."""
    payload = {
        "sub": str(user_id),
        "email": "telegram-bridge@internal",
        "role": "admin",
        "tenant_id": str(tenant_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=2),
    }
    return jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)


def _build_system_prompt(settings_row: SecretarySettings | None) -> str:
    """Base prompt + per-user tone / instructions / lang preference."""
    prompt = TELEGRAM_BASE_PROMPT
    if settings_row is None:
        return prompt

    tone = settings_row.tone or "professional"
    instructions = (settings_row.instructions or "").strip()
    lang = settings_row.lang_pref or "zh-HK"

    lang_rule = {
        "zh-HK": "語言：以繁體中文正式書面語為主，可夾雜小量廣東話口語語氣詞（例如「嘅」「咗」「喇」「唔使」），保持自然流暢，唔好全段口語化。專有名詞（CRM、Deal、Quote、Touchpoint 等）保留英文原文。首次回覆即鎖定語言，全程唔好轉台。",
        "zh-TW": "語言：以繁體中文（正體中文）正式書面語回覆，唔好夾雜廣東話口語。",
        "en": "語言：以 Professional Business English 回覆，禁止口語縮寫及港式英文。",
    }.get(lang, "語言：以繁體中文正式書面語為主，可夾雜小量廣東話口語語氣詞，保持自然流暢。")

    tone_rule = {
        "professional": "語氣：專業、簡潔、正式。",
        "friendly": "語氣：友善、親切、輕鬆但保持專業。",
        "direct": "語氣：直接了當，唔兜圈，講重點。",
        "encouraging": "語氣：正面、鼓勵性，同時保持客觀。",
        "formal": "語氣：非常正式，書面語，適合高層匯報。",
    }.get(tone, "語氣：專業、簡潔、正式。")

    extra = f"\n用戶額外指示（必須遵守）：{instructions}" if instructions else ""
    return f"{prompt}\n\n---\n用戶個人設定：\n{tone_rule}\n{lang_rule}{extra}"


async def _resolve_settings(db, mapping: TelegramBotMapping) -> SecretarySettings | None:
    row = (
        await db.execute(
            select(SecretarySettings).where(SecretarySettings.user_id == mapping.user_id)
        )
    ).scalar_one_or_none()
    return row


# ── Pending write-action confirm flow (IM-in confirm) ───────────────────────
# The AI may return an action envelope (draft) from /chat. We surface a
# preview in-band and remember pending_action_id in the mapping config so
# the user's next 確認/取消 reply executes or rejects it.
#
# LEGACY (KB-009, 2026-09-10): the three regexes below are NO LONGER USED to
# decide routing — the structural gate in app/services/im_routing.py does. They
# are kept only as reference for the token vocabulary (now widened into
# CONFIRM_TOKENS / CANCEL_TOKENS). Do NOT reintroduce keyword matching here.
_CONFIRM_WORDS = re.compile(
    r"^(?:確認|確定|執行|可以|好的|好|同意|ok|okay|yes|y|sure|go|go\s*ahead|do\s*it|proceed|confirmed|approved?|accept\b|建立|開始|好嘅|得|嗯|係|正確|冇錯|就咁|咁做|係嘅)"
    r"(?:執行|實施|做|create|建立|啦|囉)?[!。.？?]*$",
    re.IGNORECASE,
)
# 2026-09-09: 「是否建立？」「係咪執行？」等問句式確認 — pending drafts 存在時
# 用戶問「係咪要建立」= 想執行（AI 已列出全部 drafts）
_CONFIRM_QUESTION_WORDS = re.compile(
    r"^(?:是否|係咪|要唔要|需唔需要|可以)?(?:建立|執行|確認|create|confirm)[!。.？?]*$",
    re.IGNORECASE,
)
_CANCEL_WORDS = re.compile(r"^(取消|拒絕|唔要|不要|唔好|唔使|算啦|no|n|cancel|reject|decline|stop|abort)[!。. ]*$", re.IGNORECASE)

_ACTION_LABELS = {
    "create_company": "建立公司",
    "create_contact": "建立聯絡人",
    "create_task": "新增任務",
    "create_touchpoint": "新增 Touchpoint",
    "update_contact": "更新聯絡人",
    "update_company": "更新公司",
    "update_project": "更新項目",
    "update_task": "更新任務",
    "update_namecard": "更新名片",
}


def _format_action_preview(action: dict[str, Any]) -> str:
    """Render an action envelope into a compact preview line(s).

    2026-09-09: 精簡版 — 以前列晒所有 field（包括 null/company_pending）＋每個
    draft 重複 footer → 訊息好長。而家淨顯示關鍵資料，footer 由 caller 加一次。
    """
    preview = action.get("preview") or {}
    if isinstance(preview, dict) and preview.get("errors"):
        return f"⚠️ 無法草擬：{'；'.join(str(e) for e in preview['errors'])}"
    tool_key = action.get("tool_key") or ""
    act = (preview.get("action") if isinstance(preview, dict) else "") or tool_key
    label = _ACTION_LABELS.get(act, tool_key)
    lines = [f"✍️ {label}："]
    if isinstance(preview, dict):
        if act == "create_company":
            lines.append(f"   {preview.get('name')}")
        elif act == "create_contact":
            nm = preview.get("name")
            em = preview.get("email")
            cn = preview.get("company_name") or (preview.get("company_id") or "")
            extra = f" <{em}>" if em else ""
            extra += f"（{cn}）" if cn and not (cn == preview.get("company_id")) else ""
            lines.append(f"   {nm}{extra}")
        elif act == "create_touchpoint":
            tp = preview.get("type") or "note"
            sm = (preview.get("summary") or "").strip()
            if len(sm) > 70:
                sm = sm[:70] + "…"
            lines.append(f"   [{tp}] {sm}")
            if preview.get("company_name"):
                lines.append(f"   公司：{preview['company_name']}")
        else:
            for field, value in preview.items():
                if field in ("action", "validated", "errors", "id", "created_at", "company_pending"):
                    continue
                if value is None or value == "" or value == [] or value == {}:
                    continue
                lines.append(f"   {field}: {value}")
        # dup/merge 狀態短提示（唔好成段 warning）
        if preview.get("duplicate_warning"):
            lines.append("   ℹ️ 已存在 — 會自動合併／跳過")
    return "\n".join(lines)


# LEGACY (KB-009, 2026-09-10): superseded by CANCEL_TOKENS in im_routing.py —
# kept only as reference, not used for routing.
_FOLLOWUP_SKIP_WORDS = re.compile(
    r"^(?:唔使|唔洗|不用|不需要|算啦|算了|skip|no|nope|唔要|唔記得|記低|唔)|^(?:無|冇)需要", re.IGNORECASE
)


async def _handle_followup_reply(
    mapping: TelegramBotMapping,
    msg: str,
    origin: MessageOrigin = MessageOrigin.TYPED,
) -> str | None:
    """Calendar T+30 touchpoint follow-up reply handling (P3b).

    When the user has a pending calendar follow-up ask (followup_status='asked'
    within the last 24h), a reply that is EXACTLY one confirm/cancel token is
    handled here — no AI chat needed:
      - cancel token ("唔使") → mark skipped, ack
      - confirm token ("係") → create the touchpoint row from the CALENDAR
        EVENT's own metadata (title/time/company) — NEVER from the user's words
      - anything else (free text / PDF text / voice / 500-char paste) → None
        (falls through to the normal AI chat)

    KB-009 (2026-09-10): the old version keyword-matched on content, which
    swallowed 「今日天氣」, a troubleshooting question and a whole PDF as fake
    meetings. The structural gate in :mod:`app.services.im_routing` now decides.
    """
    t = (msg or "").strip()
    if not t:
        return None
    async with async_session() as db:
        try:
            await db.execute(
                sa_text(
                    "SELECT set_config('app.tenant_id', :tid, true), "
                    "set_config('app.user_id', :uid, true)"
                ),
                {"tid": str(mapping.tenant_id), "uid": str(mapping.user_id)},
            )
        except Exception:
            pass
        row = (
            await db.execute(
                sa_text(
                    "SELECT id, title, start, \"end\", project_id, location, followup_status, followup_asked_at "
                    "FROM nexus_crm.project_calendar_events "
                    "WHERE owner_user_id = :uid "
                    "  AND followup_status IN ('asked', 'snoozed') "
                    "  AND followup_asked_at >= :cutoff "
                    "ORDER BY followup_asked_at DESC LIMIT 1"
                ),
                {"uid": str(mapping.user_id), "cutoff": datetime.now(timezone.utc) - timedelta(hours=24)},
            )
        ).fetchone()
        if not row:
            return None

        event_id, event_title, event_start, _ev_end, project_id, ev_location, fp_status, asked_at = row

        # ── KB-009 structural gate (2026-09-10) ────────────────────────────
        # Only a TYPED message whose ENTIRE content is one EXACT confirm/cancel
        # token may be claimed, and only while the ask is still fresh. The
        # freshness window is the SAME 24h the SELECT above uses, so the 2h
        # default must not silently shorten it.
        age: float | None = None
        if asked_at is not None:
            try:
                _aa = asked_at
                if _aa.tzinfo is None:
                    _aa = _aa.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - _aa).total_seconds()
            except Exception:
                age = None
        allowed, gate_reason = may_text_reply_claim(
            origin, t, age, max_age_seconds=86400
        )
        if not allowed:
            _routing_log.info(
                "followup gate DENY origin=%s consumer=ai reason=%s text=%r",
                getattr(origin, "value", origin), gate_reason, t[:60],
            )
            return None
        tok = normalize_token(t)
        _routing_log.info(
            "followup gate ALLOW origin=%s consumer=%s reason=%s text=%r",
            getattr(origin, "value", origin),
            "followup-cancel" if tok in CANCEL_TOKENS else "followup-confirm",
            gate_reason,
            tok,
        )

        if tok in CANCEL_TOKENS:
            await db.execute(
                sa_text(
                    "UPDATE nexus_crm.project_calendar_events SET followup_status = 'skipped' "
                    "WHERE id = :eid"
                ),
                {"eid": event_id},
            )
            await db.commit()
            return "✅ 收到 — 唔會記錄今次會議。"

        # Resolve workspace + company from the event's project (if any).
        # workspace_id lives on companies (tenant_members has no such column —
        # 21:47 hotfix). Prefer the event's company workspace, else any
        # workspace in this tenant.
        company_id = None
        if project_id:
            prow = (
                await db.execute(
                    sa_text("SELECT company_id FROM nexus_crm.projects WHERE id = :pid"),
                    {"pid": str(project_id)},
                )
            ).fetchone()
            company_id = str(prow[0]) if prow and prow[0] else None
        workspace_id = None
        if company_id:
            wrow = (
                await db.execute(
                    sa_text("SELECT workspace_id FROM nexus_crm.companies WHERE id = :cid"),
                    {"cid": company_id},
                )
            ).fetchone()
            workspace_id = str(wrow[0]) if wrow and wrow[0] else None
        if not workspace_id:
            wrow = (
                await db.execute(
                    sa_text(
                        "SELECT workspace_id FROM nexus_crm.companies "
                        "WHERE tenant_id = :tid AND workspace_id IS NOT NULL LIMIT 1"
                    ),
                    {"tid": str(mapping.tenant_id)},
                )
            ).fetchone()
            workspace_id = str(wrow[0]) if wrow and wrow[0] else None

        t_title = (event_title or "").strip() or "會議記錄"
        fmt_date = event_start.astimezone().strftime("%Y-%m-%d %H:%M") if event_start else "—"
        loc = (ev_location or "").strip() or "—"
        try:
            await db.execute(
                sa_text(
                    "INSERT INTO nexus_crm.touchpoints "
                    "(id, tenant_id, workspace_id, company_id, type, title, description, date, "
                    " channel_type, extracted_from, created_by) "
                    "VALUES (gen_random_uuid(), :tid, :wid, :cid, 'meeting', :title, :desc, :dt, "
                    " 'meeting', 'meeting', :uid)"
                ),
                {
                    "tid": str(mapping.tenant_id),
                    "wid": str(workspace_id) if workspace_id else None,
                    "cid": company_id,
                    "title": t_title,
                    # KB-009: touchpoint body is built from the CALENDAR EVENT's
                    # own metadata only — NEVER the user's words (free text must
                    # never become touchpoint content).
                    "desc": f"👤 人物：—\n📅 時間：{fmt_date}\n📍 地點：{loc}\n📝 內容：{t_title}",
                    "dt": event_start or datetime.now(timezone.utc),
                    "uid": str(mapping.user_id),
                },
            )
            await db.execute(
                sa_text(
                    "UPDATE nexus_crm.project_calendar_events SET followup_status = 'created' "
                    "WHERE id = :eid"
                ),
                {"eid": event_id},
            )
            await db.commit()
        except Exception:
            return "⚠️ 記錄失敗 — 請再試一次，或者稍後直接喺 CRM 加。"
        return "✅ 已記錄今次會議！你可以喺 CRM → Touchpoint 搵到佢。"


async def _handle_pending_action_reply(
    mapping: TelegramBotMapping,
    text: str,
    token: str,
    origin: MessageOrigin = MessageOrigin.TYPED,
) -> str | None:
    """If the user's reply is an EXACT confirm/cancel token and a pending action
    exists, call the confirm/reject endpoint. Returns the reply text, or None if
    the message may not claim the pending action (gate denied / nothing pending).

    KB-009 (2026-09-10): the decision is now made by the structural gate, not by
    the old ``_CONFIRM_WORDS`` / ``_CANCEL_WORDS`` regexes. Real freshness comes
    from the stored ``pending_action_ts``; a legacy pending with no timestamp
    fails closed (C1) so a months-old draft can never be claimed by a bare 「係」.
    """
    cfg: dict[str, Any] = dict(mapping.config or {})
    action_id = cfg.get("pending_action_id")
    action_ids = cfg.get("pending_action_ids") or []
    # 2026-09-09: batch pending（pending_action_ids）優先 — 單一 pending_action_id fallback
    ids: list[str] = [str(i) for i in action_ids if i] if action_ids else ([str(action_id)] if action_id else [])
    if not ids:
        return None
    age: float | None = None
    _ts = cfg.get("pending_action_ts")
    if _ts is not None:
        try:
            age = datetime.now(timezone.utc).timestamp() - float(_ts)
        except (TypeError, ValueError):
            age = None
    tok = normalize_token(text)
    # 2026-09-10: ONE TTL everywhere. The API confirm layer enforces 24h
    # (ACTION_CONFIRM_TTL in routers/ai.py), so the IM gate must match — else a
    # confirm that succeeds on the web UI would be refused on Telegram/WhatsApp.
    allowed, gate_reason = may_text_reply_claim(origin, text, age, max_age_seconds=86400)
    if not allowed:
        _routing_log.info(
            "pending-action gate DENY origin=%s consumer=ai reason=%s ids=%d text=%r",
            getattr(origin, "value", origin), gate_reason, len(ids), text[:60],
        )
        return None
    if tok in CONFIRM_TOKENS:
        _routing_log.info(
            "pending-action gate ALLOW origin=%s consumer=confirm reason=%s ids=%d",
            getattr(origin, "value", origin), gate_reason, len(ids),
        )
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                AI_INTERNAL_URL + "/actions/batch-confirm",
                json={"action_ids": ids},
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("detail") if resp.content else "Unknown error"
            except Exception:
                detail = resp.text or "Unknown error"
            # 2026-09-09: pending action 已失效（rejected/executed/唔存在）—
            # 清走 config 殘留，引導用戶重新講一次，唔好卡死喺死 action。
            if "rejected" in str(detail) or "No matching" in str(detail) or resp.status_code == 404:
                async with async_session() as db:
                    m = (await db.execute(
                        select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                    )).scalar_one_or_none()
                    if m:
                        mc = dict(cast(dict[str, Any], m.config or {}))
                        mc.pop("pending_action_id", None)
                        mc.pop("pending_action_ts", None)
                        m.config = cast(Any, mc)
                        await db.commit()
                return (
                    "⚠️ 呢個寫入已經失效（可能之前已經處理過）。"
                    "請重新講一次你想建立/更新嘅內容，我會再顯示一次俾你確認。"
                )
            return f"⚠️ 執行失敗：{detail}"
        async with async_session() as db:
            m = (await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )).scalar_one_or_none()
            if m:
                mc = dict(cast(dict[str, Any], m.config or {}))
                mc.pop("pending_action_id", None)
                mc.pop("pending_action_ids", None)
                mc.pop("pending_action_ts", None)
                m.config = cast(Any, mc)
                await db.commit()
        return "✅ 已完成並寫入 CRM。"
    if tok in CANCEL_TOKENS:
        _routing_log.info(
            "pending-action gate ALLOW origin=%s consumer=reject reason=%s ids=%d",
            getattr(origin, "value", origin), gate_reason, len(ids),
        )
        async with httpx.AsyncClient(timeout=60) as client:
            for _aid in ids:
                try:
                    await client.post(
                        AI_INTERNAL_URL + f"/actions/{_aid}/reject",
                        json={},
                        headers={"Authorization": f"Bearer {token}"},
                    )
                except Exception:
                    pass
        async with async_session() as db:
            m = (await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )).scalar_one_or_none()
            if m:
                mc = dict(cast(dict[str, Any], m.config or {}))
                mc.pop("pending_action_id", None)
                mc.pop("pending_action_ts", None)
                m.config = mc
                await db.commit()
        return "已取消，不會寫入 CRM。"
    return None


# 2026-09-10 Terrence: session 邊界控制（升級文件 §1）。
# - `/new` 指令 → 強制開新 session（IM 渠道冇 UI session 概念，用戶需要出口 reset context）。
# - 閒置逾時預設 3 小時（Terrence 2026-09-10 拍板：「保持 3 hour」）。
#   可 per-mapping 覆蓋：config["ai_session_idle_minutes"]（例如 30 = 跟文件建議），
#   唔使改 code。
_SESSION_IDLE_DEFAULT_SECONDS = 3 * 3600


async def _persist_inband_exchange(mapping: Any, user_text: str, reply_text: str) -> None:
    """Persist an interceptor-handled exchange (confirm / cancel / follow-up reply).

    2026-09-10 (P仔 diagnosis): these in-band replies were returned WITHOUT being
    written to nexus_ai.messages, so the AI's replayed history had a hole exactly
    where the user had just confirmed something. Reported by the operator as
    「接唔到上一句」/ "the AI cannot connect to the previous message". Only
    routers/ai.py used to write Message rows; the interceptors wrote none.
    Best-effort: a history write must never break the actual reply.
    """
    try:
        sid = dict(mapping.config or {}).get("ai_session_id")
        if not sid or not reply_text:
            return
        from uuid import UUID as _UUID

        from app.models.ai import Message

        async with async_session() as db:
            for _role, _content in (("user", user_text), ("assistant", reply_text)):
                db.add(Message(session_id=_UUID(str(sid)), role=_role, content=_content))
            await db.commit()
    except Exception:
        pass


async def handle_telegram_message(
    mapping: TelegramBotMapping,
    text: str,
    origin: MessageOrigin = MessageOrigin.TYPED,
) -> str | None:
    """Telegram message → internal AI chat → return reply text. None if no reply.

    ``origin`` records where the text came from: the two pre-AI interceptors may
    only claim a TYPED message (see :mod:`app.services.im_routing`). Voice notes
    pass ``MessageOrigin.VOICE``; uploaded documents pass
    ``MessageOrigin.DOCUMENT`` — so document/voice text can never be swallowed
    as a follow-up/write-action reply, no matter what it contains.
    """
    async with async_session() as db:
        # Re-fetch mapping to get fresh config (session id may have been updated)
        fresh = (
            await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )
        ).scalar_one_or_none()
        if fresh is None:
            # NEVER-SILENT (KB-009): the mapping vanished mid-flight. Returning
            # None here would make the webhook send NOTHING; apologise instead.
            _routing_log.warning(
                "mapping %s vanished before reply — returning apology", mapping.id
            )
            return "⚠️ 系統暫時未能處理你嘅訊息（對話設定已失效），請重新開始對話再試。"
        mapping = fresh

        settings_row = await _resolve_settings(db, mapping)
        system_prompt = _build_system_prompt(settings_row)

        # Reuse recent session (v7.28: 24 小時內，唔止同一日曆日) so the AI
        # remembers the conversation — 用戶 2026-09-01：「最起碼儲存一天」
        hkt_now = datetime.now(timezone.utc) + timedelta(hours=8)
        cfg: dict[str, Any] = dict(mapping.config or {})
        session_id: str | None = None
        # /new → 唔重用舊 session，強制開新（見檔頂註釋）
        force_new = text.strip().lower().startswith("/new")
        idle_seconds = _SESSION_IDLE_DEFAULT_SECONDS
        try:
            _mins = float(cfg.get("ai_session_idle_minutes") or 0)
            if _mins > 0:
                idle_seconds = int(_mins * 60)
        except (TypeError, ValueError):
            pass
        sid = None if force_new else cfg.get("ai_session_id")
        ts = cfg.get("ai_session_ts")
        # 舊 config 冇 ai_session_ts → fallback 同日曆日比較
        if sid:
            if ts:
                try:
                    ts_f = float(ts)
                    if hkt_now.timestamp() - ts_f <= idle_seconds:
                        session_id = str(sid)
                except (TypeError, ValueError):
                    pass
            elif cfg.get("ai_session_date") == hkt_now.strftime("%Y-%m-%d"):
                session_id = str(sid)

    # /new 而冇其他內容 → 淨係確認，唔 call AI
    if force_new:
        _rest = text.strip()[4:].strip()
        if not _rest:
            return "✅ 已開始新對話，可以繼續問我。"
        text = _rest

    token = _make_internal_token(mapping.user_id, mapping.tenant_id)

    # KB-009 (2026-09-10): the two pre-AI interceptors (pending write-action
    # confirm / calendar follow-up) may ONLY claim a TYPED message whose whole
    # content is one exact confirm/cancel token AND a fresh pending. Each handler
    # runs the structural gate itself with the REAL age (follow-up →
    # now - followup_asked_at, 24h window; pending-action → now - pending_action_ts).
    # Everything else — free text, a pasted PDF, a voice transcript, a 500-char
    # paste, a stray 「1」 — falls straight through to the AI, so no message can
    # be silently swallowed and written into the CRM.
    if origin is MessageOrigin.TYPED:
        # Pending write-action confirm? If the user replies 確認/取消 while a
        # draft action awaits confirmation, execute it in-band (no AI call).
        action_reply = await _handle_pending_action_reply(mapping, text, token, origin)
        if action_reply is not None:
            await _persist_inband_exchange(mapping, text, action_reply)
            return action_reply

        # Calendar T+30 touchpoint follow-up reply? (P3b — user answers the
        # "要唔要我記低今次會議?" ask). Handle in-band before the AI chat.
        followup_reply = await _handle_followup_reply(mapping, text, origin)
        if followup_reply is not None:
            await _persist_inband_exchange(mapping, text, followup_reply)
            return followup_reply

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Question: {text}"},
    ]

    # Forward the REAL provenance so the AI router's write gate fails CLOSED
    # for voice/document text. Without this the router would have to assume
    # "typed" from the channel alone — and a voice note that happens to be
    # shaped like a command must never auto-write.
    _ai_params = {"channel": "telegram", "origin": origin.value}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            AI_INTERNAL_URL + "/chat",
            json=messages,
            params=dict(_ai_params, session_id=session_id) if session_id else _ai_params,
            headers={"Authorization": f"Bearer {token}"},
        )

    # Stale-session fallback — retry without session_id (same as WhatsApp)
    if resp.status_code == 404 and session_id:
        session_id = None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                AI_INTERNAL_URL + "/chat",
                json=messages,
                params=_ai_params,
                headers={"Authorization": f"Bearer {token}"},
            )

    if resp.status_code != 200:
        try:
            error_detail = resp.json().get("detail") or resp.json().get("error", {}).get("message", "Unknown error")
        except Exception:
            error_detail = f"HTTP {resp.status_code}"
        return f"⚠️ AI 暫時冇回應（{error_detail}）。請稍後再試。"

    data = resp.json()
    reply = data.get("text") or "抱歉，我暫時未能處理呢個請求。"

    # Persist session id for reuse (v7.28: 存 unix ts，24 小時內都 reuse)
    # 2026-09-10 fix: 原本只喺「有新 session id」時才更新 ai_session_ts → idle 由
    # session「建立」起計，令一直用緊嘅 session 3 小時後靜靜換新、歷史斷開
    # （「接唔到上一句」）。改為每條訊息都更新 ts = 「距上次訊息時間」；
    # session id / date 只喺真係換 session 時覆蓋。
    new_session_id = data.get("session_id")
    if new_session_id:
        hkt_now = datetime.now(timezone.utc) + timedelta(hours=8)
        async with async_session() as db:
            m = (
                await db.execute(
                    select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                )
            ).scalar_one_or_none()
            if m:
                m_cfg: dict[str, Any] = dict(m.config or {})
                if new_session_id != session_id:
                    m_cfg["ai_session_id"] = new_session_id
                    m_cfg["ai_session_date"] = hkt_now.strftime("%Y-%m-%d")
                m_cfg["ai_session_ts"] = str(hkt_now.timestamp())
                m.config = m_cfg
                await db.commit()

    # Embedded write-action (Draft → Confirm → Execute): surface ALL previews
    # in-band and remember pending_action_ids (list!) so the user's next
    # 確認/取消 reply executes/rejects the whole batch.
    # 2026-09-09 fix: /chat 可以一次過出多個 actions（company + contacts）—
    # 以前淨攞 data.action（單一）→ 用戶 confirm 只執行一個 → 其他 drafts 永遠
    # pending → 「話成功但 CRM 冇記錄」。
    action = data.get("action")
    resp_actions = list(data.get("actions") or [])
    if action and action.get("action_id") and not any(
        a.get("action_id") == action.get("action_id") for a in resp_actions
    ):
        resp_actions = [action] + resp_actions
    if resp_actions:
        preview_parts: list[str] = []
        pending_ids: list[str] = []
        for a in resp_actions:
            aid = a.get("action_id")
            if not aid:
                continue
            pending_ids.append(str(aid))
            pt = _format_action_preview(a)
            if pt and pt not in preview_parts:
                preview_parts.append(pt)
        if preview_parts:
            extra = "\n\n".join(preview_parts)
            if extra not in reply:
                # footer 只加一次（batch 尾）— 唔好每個 draft 重複
                reply = f"{reply}\n\n{extra}\n\n回覆「確認」執行，或「取消」拒絕。"
        if pending_ids:
            async with async_session() as db:
                m = (
                    await db.execute(
                        select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                    )
                ).scalar_one_or_none()
                if m:
                    mc: dict[str, Any] = dict(cast(dict[str, Any], m.config or {}))
                    mc["pending_action_ids"] = pending_ids
                    # KB-009/C5: store the real creation time so the confirm gate
                    # can measure the pending's age (and fail closed when absent).
                    mc["pending_action_ts"] = str(datetime.now(timezone.utc).timestamp())
                    mc.pop("pending_action_id", None)
                    m.config = cast(Any, mc)
                    await db.commit()
    else:
        import logging as _log
        _log.getLogger("telegram_inbound.confirm").info(
            "chat resp 冇 action envelope — 用戶確認將被當普通訊息"
        )

    return reply


async def _get_bot_token(db, mapping: TelegramBotMapping) -> str:
    """Bot token: ChannelCredential (encrypted store) preferred, fall back to
    mapping.bot_token (legacy rows where the credential write failed).

    NOTE: ChannelCredential query previously crashed the whole poller with
    `invalid input syntax for type uuid: ""` (empty-string UUID params in
    some tenant rows) — wrapped in try/except so a credential-store hiccup
    can never take down Telegram inbound processing again.
    """
    try:
        cred = (
            await db.execute(
                select(ChannelCredential).where(
                    ChannelCredential.tenant_id == mapping.tenant_id,
                    ChannelCredential.user_id == mapping.user_id,
                    ChannelCredential.channel == "telegram",
                )
            )
        ).scalar_one_or_none()
        if cred and cred.access_token:
            return decrypt_secret(str(cred.access_token))  # AES-256-GCM at rest
    except Exception:  # noqa: BLE001 — credential store must never block inbound
        import logging
        logging.getLogger("telegram_inbound").exception(
            "ChannelCredential lookup failed for bot %s — falling back to mapping token",
            mapping.bot_username,
        )
    tok = str(mapping.bot_token or "")
    return tok if tok and tok != "None" else ""


async def _download_photo(token: str, photo_sizes: list[dict]) -> str | None:
    """Download the largest photo size → temp file. Returns local path or None."""
    if not photo_sizes:
        return None
    largest = max(photo_sizes, key=lambda p: p.get("file_size", 0) or 0)
    file_id = largest.get("file_id")
    if not file_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            info = (await client.post(
                f"https://api.telegram.org/bot{token}/getFile",
                json={"file_id": file_id},
            )).json()
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        if resp.status_code != 200:
            return None
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_DIR / f"pending_{uuid.uuid4().hex[:12]}.jpg"
        tmp.write_bytes(resp.content)
        return str(tmp)
    except Exception:
        return None


async def _analyze_plain_image(
    path: str,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> str:
    """Non-namecard photo → Qwen3-VL (SiliconFlow) describes image + reads text.

    Route for plain photos in the IM AI flow: namecards go to the namecard
    pipeline; everything else lands here (卡片行卡片 flow, 其他行 normal
    request). Reply uses formal written Chinese per G08 output standard.
    Falls back to local Tesseract OCR on any API failure. user_id/tenant_id
    are used for central usage tracking (best-effort).
    """
    import base64

    # G08 獨立 key 儲存：provider_credentials（AES-256-GCM at rest）→ env fallback
    from app.services.provider_keys import load_provider_key

    key = await load_provider_key("siliconflow", tenant_id)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        raw = b""
    # 2026-09-10: 大圖先縮細 — 手機相 3-5MB，base64 再脹 33%，會 timeout
    # 而靜默跌去 Tesseract（出垃圾）。1600px 仍然睇得清文件細字。
    b64 = base64.b64encode(_downscale_image(raw)).decode() if raw else None

    if key and b64:
        prompt = (
            "這是一張用戶透過 Telegram 傳送的圖片。請以繁體中文正式書面語回覆：\n"
            "1. 第一句簡短描述圖片內容\n"
            "2. 接著列出圖片中偵測到的所有文字\n"
            "3. 若圖片包含文件或資訊，重點說明；若為一般照片，描述場景即可\n"
            "請直接輸出內容，無需任何前綴。"
        )
        payload = {
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            "max_tokens": 800,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.siliconflow.cn/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code != 200:
                # 2026-09-10: 之前完全靜默，睇唔到點解會跌去本地 OCR
                import logging

                logging.getLogger(__name__).warning(
                    "vision: HTTP %s from SiliconFlow → local OCR fallback: %s",
                    resp.status_code, resp.text[:200],
                )
            if resp.status_code == 200:
                result = resp.json()
                text = (result["choices"][0]["message"]["content"] or "").strip()
                if text:
                    # Core rule G08: central usage tracking (best-effort)
                    try:
                        u = result.get("usage") or {}
                        from app.models.ai.usage import UsageEvent
                        from sqlalchemy import text as _sqltext
                        async with async_session() as db:
                            # v7.28: 新 session 冇 GUC → RLS 擋 INSERT（usage 靜默
                            # 記錄唔到）— 開頭 set 返
                            await db.execute(
                                _sqltext(
                                    "SELECT set_config('app.tenant_id', :t, true), "
                                    "set_config('app.user_id', :u, true)"
                                ),
                                {"t": str(tenant_id), "u": str(user_id)},
                            )
                            db.add(UsageEvent(
                                session_id=None,
                                user_id=user_id,
                                tenant_id=tenant_id,
                                provider="siliconflow",
                                model="Qwen/Qwen3-VL-8B-Instruct",
                                input_tokens=int(u.get("prompt_tokens") or 0),
                                output_tokens=int(u.get("completion_tokens") or 0),
                                cost_estimate=None,
                                result_status="success",
                                module="telegram_image",
                                currency="USD",
                            ))
                            await db.commit()
                    except Exception:
                        pass  # usage recording is best-effort
                    return text
        except Exception as exc:
            # 2026-09-10: 唔再純靜默 — 之前冇 log 所以睇唔到點解跌去 OCR
            import logging

            logging.getLogger(__name__).warning(
                "vision: Qwen3-VL call failed (%s: %s) → local OCR fallback",
                type(exc).__name__, str(exc)[:160],
            )

    # Fallback: local Tesseract OCR
    try:
        from app.services.namecard_ocr import ocr_image
        txt = ocr_image(path) or ""
        if txt.strip():
            return f"（AI 圖片分析暫時無法使用，以下為本地 OCR 結果）\n\n{txt[:600]}"
    except Exception:
        pass
    return "收到圖片，但暫時無法分析內容。"


async def _handle_photo(mapping: TelegramBotMapping, token: str, photo_sizes: list[dict]) -> str | None:
    """Photo message → detect namecard → namecard flow OR plain-image AI analysis."""
    path = await _download_photo(token, photo_sizes)
    if not path:
        return "⚠️ 圖片下載失敗，請再試一次。"

    det = namecard_im.run_script(["--detect", path])
    if not det.get("is_namecard"):
        # Non-namecard photo → route to AI image analysis (normal request flow)
        try:
            reply = await _analyze_plain_image(path, mapping.user_id, mapping.tenant_id)
        except Exception:
            reply = "收到圖片，但暫時無法分析內容。"
        try:
            os.remove(path)
        except OSError:
            pass
        return reply

    # Store pending upload path in mapping config for the "係/是" follow-up
    # Preview: use parsed name + company when available (friendlier than raw OCR)
    preview = (det.get("ocr_preview") or "")[:80]
    async with async_session() as db:
        m = (
            await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )
        ).scalar_one_or_none()
        if m:
            m_cfg: dict[str, Any] = dict(m.config or {})
            m_cfg["pending_namecard_path"] = path
            m_cfg["pending_namecard_preview"] = preview
            m.config = m_cfg
            await db.commit()

    # Try to extract a clean name/company for the confirmation message
    tg_usage: list = []  # core rule G08: central token collection
    try:
        from app.services.namecard_ocr import parse_namecard, ocr_image
        det_txt = det.get("ocr_preview") or ""
        # Re-OCR full text for parse (detect only returns preview)
        full_txt = ocr_image(path, usage_out=tg_usage)
        parsed = parse_namecard(full_txt or det_txt)
        p_name = parsed.get("name") or ""
        p_company = parsed.get("company") or ""
        if p_name:
            preview = f"{p_name}" + (f" · {p_company}" if p_company else "")
        elif det_txt:
            preview = det_txt[:80]
    except Exception:
        pass
    if tg_usage:
        try:
            from app.models.ai.usage import UsageEvent
            from sqlalchemy import text as _sqltext
            from uuid import uuid4 as _uuid4
            async with async_session() as db:
                # v7.28: 新 session 冇 GUC → RLS 擋 INSERT（usage 靜默記錄唔到）
                await db.execute(
                    _sqltext(
                        "SELECT set_config('app.tenant_id', :t, true), "
                        "set_config('app.user_id', :u, true)"
                    ),
                    {"t": str(mapping.tenant_id), "u": str(mapping.user_id)},
                )
                for r in tg_usage:
                    db.add(UsageEvent(
                        session_id=None,
                        user_id=_uuid4(),
                        tenant_id=mapping.tenant_id,
                        provider=r.get("provider") or "siliconflow",
                        model=r.get("model") or "",
                        input_tokens=int(r.get("input_tokens") or 0),
                        output_tokens=int(r.get("output_tokens") or 0),
                        cost_estimate=float(r.get("cost_usd") or 0) if r.get("cost_usd") else None,
                        result_status="success",
                        module="namecard",
                        currency="USD",
                    ))
                await db.commit()
        except Exception:
            pass  # usage recording is best-effort

    return (
        f"📇 偵測到名片：{preview}\n\n"
        f"需要上載到名片庫嗎？（自動 OCR + 存入 CRM 聯絡人）\n"
        f"回覆「係」上載，或「唔使」取消"
    )


async def _resolve_workspace_id(db, tenant_id) -> str:
    """First workspace for the tenant (same fallback as im_push)."""
    try:
        row = await db.execute(
            sa_text(
                "SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :tid ORDER BY created_at ASC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
        val = row.scalar_one_or_none()
        if val:
            return str(val)
    except Exception:
        pass
    return ""


async def _transcribe_voice(path: str, tenant_id=None, user_id=None) -> str:
    """STT via SiliconFlow — thin wrapper around app.services.voice_stt.

    Returns transcript text, or "" on any failure (never raises). The shared
    helper owns the provider key loading + central usage recording so the
    Telegram and WhatsApp paths behave identically.
    """
    from app.services.voice_stt import transcribe_audio

    ext = (os.path.splitext(path)[1] or ".ogg").lower().lstrip(".")
    ctype = {
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "opus": "audio/ogg",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
    }.get(ext, "audio/ogg")
    return await transcribe_audio(
        path,
        tenant_id=tenant_id,
        user_id=user_id,
        filename=f"voice.{ext}",
        content_type=ctype,
    )


async def _handle_voice(mapping: TelegramBotMapping, token: str, voice: dict) -> str | None:
    """Voice note → STT → feed the transcript into the EXISTING text pipeline.

    The transcript is handled exactly like a typed message, so CRM search,
    conversation memory and tool drafts (Draft → Confirm → Execute) all apply.
    Returns the AI reply for Telegram; on STT failure returns a short zh-HK
    apology so the user is never left in silence.

    2026-09-10: was Phase D 語音記事 (STT → auto Touchpoint, canned confirmation)
    which gave the user no useful answer to an actual question.
    """
    file_id = (voice or {}).get("file_id")
    if not file_id:
        return None
    data = await telegram_service.download_file(token, file_id)
    if not data:
        return "😕 語音下載失敗，請再試一次。"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        text = await _transcribe_voice(tmp_path, mapping.tenant_id, mapping.user_id)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    if not text:
        return "😕 唔好意思，未能辨識呢段語音，請再錄一次或者用文字輸入。"

    # Feed the transcript into the normal text path — but as VOICE origin, so a
    # spoken confirm token can never be claimed by the text-reply interceptors.
    reply = await handle_telegram_message(mapping, text, origin=MessageOrigin.VOICE)
    if not reply:
        return "😕 已收到語音，但暫時未能處理，請稍後再試。"
    return reply


_TEXT_EXTS = {"txt", "md", "csv", "json", "log", "xml", "yaml", "yml", "ini", "cfg", "srt"}


def _extract_document_text(data: bytes, ext: str, mime: str) -> str:
    """Bytes + extension → plain text, covering the common document types.

    2026-09-10: Telegram only handled PDF before. Users also send Word, Excel,
    PowerPoint, HTML, RTF and plain text, so all of those extract here and then
    flow into the same AI pipeline. Any failure returns "" so the caller can
    give the user a clear message instead of silence.
    """
    import io as _io

    ext = (ext or "").lower()
    mime = (mime or "").lower()
    try:
        if ext == "pdf" or "pdf" in mime:
            return _extract_pdf_text(data)
        if ext in _TEXT_EXTS or mime.startswith("text/"):
            for enc in ("utf-8", "utf-16", "big5", "gb18030"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")
        if ext == "docx":
            import docx

            d = docx.Document(_io.BytesIO(data))
            parts = [p.text for p in d.paragraphs if p.text.strip()]
            for t in d.tables:
                for row in t.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        if ext in ("xlsx", "xlsm"):
            import openpyxl

            wb = openpyxl.load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
            parts: list[str] = []
            for ws in wb.worksheets[:5]:
                parts.append(f"[{ws.title}]")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 200:
                        parts.append("…")
                        break
                    cells = [str(c) for c in row if c is not None and str(c).strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        if ext == "xls":
            import xlrd

            wb = xlrd.open_workbook(file_contents=data)
            parts = []
            for ws in wb.sheets()[:5]:
                parts.append(f"[{ws.name}]")
                for r in range(min(ws.nrows, 200)):
                    cells = [str(c.value) for c in ws.row(r) if str(c.value).strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n".join(parts)
        if ext == "pptx":
            from pptx import Presentation

            prs = Presentation(_io.BytesIO(data))
            parts = []
            # list() first — python-pptx's Slides object does not support slicing
            for i, slide in enumerate(list(prs.slides)[:30], 1):
                parts.append(f"[Slide {i}]")
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                        parts.append(shape.text_frame.text.strip())
            return "\n".join(parts)
        if ext in ("html", "htm"):
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(data, "lxml")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text("\n", strip=True)
        if ext == "rtf":
            from striprtf.striprtf import rtf_to_text

            return rtf_to_text(data.decode("utf-8", errors="replace"))
    except Exception:
        return ""
    return ""


def _downscale_image(data: bytes, max_dim: int = 1600, quality: int = 85) -> bytes:
    """Shrink an image before it goes to the vision model.

    2026-09-10: phone photos are 3-5MB and base64 inflates them by ~33%, which
    pushed the vision call into a timeout and silently dropped the user onto
    local Tesseract (garbage output). Capping the long edge at 1600px keeps
    printed text legible while cutting the payload by roughly an order of
    magnitude. Returns the input unchanged if anything goes wrong.
    """
    try:
        import io as _io

        from PIL import Image

        im = Image.open(_io.BytesIO(data))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        out = _io.BytesIO()
        im.save(out, format="JPEG", quality=quality)
        return out.getvalue()
    except Exception:
        return data


def _pdf_to_images(data: bytes, max_pages: int = 2, max_dim: int = 1600) -> list[bytes]:
    """Rasterise the first pages of a PDF (PyMuPDF) → JPEG bytes.

    For scanned PDFs that carry no text layer. Pages are rendered at 2x then
    downscaled, so small print stays readable for the vision model without
    sending a huge payload. Returns [] if PyMuPDF is unavailable or the file
    is not a readable PDF.
    """
    out: list[bytes] = []
    try:
        try:
            import pymupdf as fitz  # PyMuPDF >= 1.24 preferred module name
        except ImportError:  # older releases only expose 'fitz'
            import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        for page in list(doc)[:max_pages]:
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                out.append(_downscale_image(pix.tobytes("png"), max_dim=max_dim))
            except Exception:
                continue
        doc.close()
    except Exception:
        return []
    return out


def _extract_pdf_text(data: bytes) -> str:
    """PDF bytes → text (pypdf). Returns '' if nothing extractable.

    Only the first 30 pages are read — enough for a document the user wants
    summarised, and it bounds both memory and the cost of the follow-up call.
    """
    import io

    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    out: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for page in reader.pages[:30]:
            try:
                out.append(page.extract_text() or "")
            except Exception:
                continue
    except Exception:
        return ""
    return "\n".join(out)


async def _handle_document(mapping: TelegramBotMapping, token: str, doc: dict) -> str | None:
    """Document upload (PDF / text-ish) → extract text → EXISTING text pipeline.

    2026-09-10: an uploaded PDF got no reply at all. The webhook dispatch only
    knew about text / photo / voice, and 'document' matched no branch, so the
    update was silently dropped. Text is now extracted and handled exactly like
    a typed message, so CRM search, memory and tools all apply. Never leaves
    the user in silence — every failure path returns an apology.
    """
    file_id = (doc or {}).get("file_id")
    if not file_id:
        return None
    name = ((doc or {}).get("file_name") or "文件").strip()
    mime = ((doc or {}).get("mime_type") or "").lower()
    ext = os.path.splitext(name)[1].lstrip(".").lower() or "bin"

    data = await telegram_service.download_file(token, file_id, ext=ext)
    if not data:
        return "😕 文件下載失敗，請再試一次。"
    if len(data) > 20 * 1024 * 1024:
        return "😕 呢個文件太大（超過 20MB），暫時處理唔到。"

    # 常見文件類型統一抽取（PDF / Word / Excel / PPT / HTML / RTF / 純文字）
    text = _extract_document_text(data, ext, mime)

    if not text.strip() and (ext == "pdf" or "pdf" in mime):
        # 掃描版 PDF（冇文字層）→ 轉圖交俾 vision model，唔好就咁放棄用戶。
        # 2026-09-10: 用戶傳「通告20262027年度063號…安排事宜.pdf」（掃描版）
        # 原本只回一句「抽唔到文字」。而家 render 頭 2 頁做圖再行 vision。
        parts: list[str] = []
        for img in _pdf_to_images(data):
            tmp = ""
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                    f.write(img)
                    tmp = f.name
                desc = await _analyze_plain_image(tmp, mapping.user_id, mapping.tenant_id)
                if desc and "暫時無法使用" not in desc:
                    parts.append(desc)
            except Exception:
                continue
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
        if parts:
            text = "\n\n".join(parts)

    if not text.strip():
        return (
            f"😕 收到「{name}」，但我喺入面抽唔到文字。\n"
            "支援：PDF、Word（.docx）、Excel（.xlsx／.xls）、PowerPoint（.pptx）、"
            "HTML、RTF、純文字。\n"
            "（掃描版 PDF 或者圖片，可以直接當相片傳，我會用 OCR 睇。）"
        )

    # Cap the payload — a big document should not blow up cost or context.
    text = text.strip()[:12000]
    # origin=DOCUMENT：文件內容唔係回答日曆跟進／write-action confirm，唔可以
    # 俾嗰兩個攔截器吞掉（2026-09-10 PDF 通告事件）。Provenance gate 保證無論
    # 內文含「會議／見／約」都會落到 AI。
    reply = await handle_telegram_message(
        mapping, f"（用戶上傳文件：{name}）\n\n{text}", origin=MessageOrigin.DOCUMENT
    )
    if not reply:
        return "😕 已收到文件，但暫時未能處理，請稍後再試。"
    return reply


async def _handle_namecard_confirm(mapping: TelegramBotMapping, text: str) -> str | None:
    """User replied '係/是/好/yes' after a namecard photo → run upload pipeline."""
    low = text.strip().lower()
    YES = {"係", "是", "好", "yes", "y", "ok", "可以", "上載", "上傳", "upload"}
    NO = {"唔使", "不用", "no", "n", "取消", "cancel", "不要", "唔好"}
    is_yes = low in YES or low in {w.lower() for w in YES}
    is_no = low in NO or low in {w.lower() for w in NO}
    if not is_yes and not is_no:
        return None  # not a confirmation — treat as normal message

    async with async_session() as db:
        m = (
            await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )
        ).scalar_one_or_none()
        if not m:
            return None
        cfg: dict[str, Any] = dict(m.config or {})
        pending = cfg.get("pending_namecard_path")
        # Clear pending immediately (single-use)
        for k in ("pending_namecard_path", "pending_namecard_preview"):
            cfg.pop(k, None)
        m.config = cfg
        await db.commit()

    if is_no:
        if pending:
            try:
                os.remove(pending)
            except OSError:
                pass
        return "✅ 已取消，名片唔會上載。"
    if not pending or not os.path.isfile(pending):
        return None  # no pending namecard — treat as normal message

    res = namecard_im.run_script(["--upload", pending])
    try:
        os.remove(pending)
    except OSError:
        pass

    msg, review_state = namecard_im.format_upload_result(res)
    # Review tier: remember the card so 「覆蓋/保留」can resolve it
    if review_state.get("card_id"):
        async with async_session() as db:
            m = (
                await db.execute(
                    select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                )
            ).scalar_one_or_none()
            if m:
                cfg2: dict[str, Any] = dict(m.config or {})
                cfg2["pending_review_card_id"] = review_state["card_id"]
                m.config = cfg2
                await db.commit()
    return msg


async def _handle_namecard_review_reply(mapping: TelegramBotMapping, text: str) -> str | None:
    """User replied '覆蓋/保留' to a review-status card → resolve via API."""
    is_ow = namecard_im.match_intent(text, namecard_im.OVERWRITE_WORDS)
    is_kp = namecard_im.match_intent(text, namecard_im.KEEP_WORDS)
    if not is_ow and not is_kp:
        return None  # not a review reply — treat as normal message

    card_id = ""
    async with async_session() as db:
        m = (
            await db.execute(
                select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
            )
        ).scalar_one_or_none()
        if not m:
            return None
        cfg: dict[str, Any] = dict(m.config or {})
        card_id = cfg.get("pending_review_card_id") or ""
        cfg.pop("pending_review_card_id", None)
        m.config = cfg
        await db.commit()

    if not card_id:
        return None  # no pending review — treat as normal message

    action = "overwrite" if is_ow else "keep_both"
    res = namecard_im.run_script(["--resolve", card_id, action])
    return namecard_im.format_resolve_result(res, action)


async def process_update(mapping: TelegramBotMapping, update: dict) -> None:
    """Process one Telegram update: extract message → AI reply → send back."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if not chat_id:
        return
    # Ignore our own outgoing messages (bot echo)
    if msg.get("from", {}).get("is_bot"):
        return

    async with async_session() as db:
        token = await _get_bot_token(db, mapping)
    if not token:
        return

    # Namecard photo flow
    if not text and msg.get("photo"):
        reply = await _handle_photo(mapping, token, msg["photo"])
        if reply:
            await telegram_service.send_message(token, chat_id, reply)
        return

    # Voice note → STT → feed transcript into the normal text chat pipeline
    if not text and (msg.get("voice") or msg.get("audio")):
        voice = msg.get("voice") or msg.get("audio")
        reply = await _handle_voice(mapping, token, voice)
        if reply:
            await telegram_service.send_message(token, chat_id, reply)
        return

    # Document upload (PDF etc.) → extract text → normal text chat pipeline.
    # 2026-09-10: this branch did not exist, so PDFs were silently dropped.
    if not text and msg.get("document"):
        reply = await _handle_document(mapping, token, msg["document"])
        if reply:
            await telegram_service.send_message(token, chat_id, reply)
        return

    # Namecard confirmation flow (係/唔使 after a photo)
    if text:
        confirm_reply = await _handle_namecard_confirm(mapping, text)
        if confirm_reply is not None:
            await telegram_service.send_message(token, chat_id, confirm_reply)
            return

    # Namecard review flow (覆蓋/保留 after a duplicate warning)
    if text:
        review_reply = await _handle_namecard_review_reply(mapping, text)
        if review_reply is not None:
            await telegram_service.send_message(token, chat_id, review_reply)
            return

    reply = await handle_telegram_message(mapping, text, origin=MessageOrigin.TYPED)
    if not reply:
        return

    result = await telegram_service.send_message(token, chat_id, reply)
    if not result.get("ok"):
        # Log failure, don't crash the poller
        import logging
        logging.getLogger("telegram_inbound").warning(
            "send failed: %s", result.get("description", "unknown")
        )


async def poll_once(db) -> int:
    """One polling pass: fetch updates for every active bot, process them.
    Returns number of updates processed. Used by the lifespan background task."""
    mappings = (
        await db.execute(
            select(TelegramBotMapping).where(TelegramBotMapping.status == "active")
        )
    ).scalars().all()
    processed = 0
    for mapping in mappings:
        token = await _get_bot_token(db, mapping)
        if not token:
            continue

        cfg: dict[str, Any] = dict(mapping.config or {})
        offset = cfg.get("tg_update_offset")
        try:
            data = await telegram_service.get_updates(token, offset=offset, timeout=1)
        except Exception as e:  # noqa: BLE001 — network errors must not kill the poller silently
            logging.getLogger("telegram_inbound").warning(
                "get_updates failed for %s (offset=%s): %s", mapping.bot_username, offset, e
            )
            continue
        if not data.get("ok"):
            # Telegram returns ok=false on 409 conflict / 401 / 429 / network blips.
            # A delivered-but-unconfirmed update is NOT re-sent with the same offset,
            # so a single failed poll can permanently lose a message — log loudly.
            logging.getLogger("telegram_inbound").warning(
                "get_updates !ok for %s (offset=%s): %s",
                mapping.bot_username, offset, data.get("description", data),
            )
            continue

        updates = data.get("result", [])
        for upd in updates:
            try:
                await process_update(mapping, upd)
            except Exception as e:  # noqa: BLE001 — per-update isolation
                import logging
                logging.getLogger("telegram_inbound").exception(
                    "process_update failed for update %s: %s", upd.get("update_id"), e
                )
                continue

        if updates:
            last_id = updates[-1]["update_id"]
            async with async_session() as db2:
                m = (
                    await db2.execute(
                        select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                    )
                ).scalar_one_or_none()
                if m:
                    m_cfg: dict[str, Any] = dict(m.config or {})
                    m_cfg["tg_update_offset"] = last_id + 1
                    m.config = m_cfg
                    await db2.commit()
            processed += len(updates)
    return processed


async def handle_webhook_update(data: dict) -> None:
    """Background processor for webhook-delivered updates (fast-ACK pattern).

    Telegram pushes the update here; the HTTP handler ACKs immediately and
    this runs in a background task. Idempotency via tg_last_webhook_update_id
    so Telegram retries (caused by slow ACK) never double-process.
    """
    import logging as _log
    try:
        async with async_session() as db:
            # 2026-09-09 fix: match mapping BY CHAT ID — 兩個 bots 共用同一個
            # webhook URL，update 冇 bot identity。以前 scalars().first() 淨攞
            # 第一個 active mapping → 用戶 message 用錯 bot token/user 處理 →
            # reply send 去錯 bot → 用戶永遠收唔到（「發訊息冇反應」）。
            # mapping.chat_id = bot 綁定嘅 Telegram chat — 由 update 嘅 chat.id match。
            upd_msg = data.get("message") or data.get("edited_message") or {}
            upd_chat_id = str(upd_msg.get("chat", {}).get("id", ""))
            q = select(TelegramBotMapping).where(TelegramBotMapping.status == "active")
            if upd_chat_id:
                q = q.where(TelegramBotMapping.chat_id == upd_chat_id)
            mapping = (
                await db.execute(q)
            ).scalars().first()
            if not mapping:
                _log.getLogger("telegram_inbound").warning(
                    "webhook update received (chat=%s) but no active bot mapping matches",
                    upd_chat_id,
                )
                return
            # RLS: set tenant/user GUCs so row-level policies can match
            # (webhook path bypasses get_tenant_session middleware). Without
            # this, ai_secretary_settings / ai_channel_credentials queries
            # would either return nothing or (legacy policies) crash with
            # 'invalid input syntax for type uuid: ""'.
            await db.execute(
                sa_text(
                    "SELECT set_config('app.tenant_id', :tid, true), "
                    "set_config('app.user_id', :uid, true)"
                ),
                {"tid": str(mapping.tenant_id), "uid": str(mapping.user_id)},
            )
            upd_id = data.get("update_id")
            cfg: dict[str, Any] = dict(mapping.config or {})
            last_id = cfg.get("tg_last_webhook_update_id")
            # 2026-09-09: watermark type safety — 唔同寫入路徑（jsonb_set /
            # python dict）寫出嚟可能係 int 或者 str；int <= str 會 TypeError
            # crash 成個 inbound path（18:41 real message 死因）。統一 cast。
            try:
                if isinstance(upd_id, str):
                    upd_id = int(upd_id)
                if isinstance(last_id, str):
                    last_id = int(last_id)
            except (TypeError, ValueError):
                last_id = None
            if upd_id is not None and last_id is not None and upd_id <= last_id:
                # ⚠️ 2026-08-22: silent dedup 幾乎令 production inbound 死寂 —
                # mock 測試用 393000xxx update_id 推高 watermark，真實 update
                # (~3922615xx) 全部被當 duplicate 忽略。必須 log 以便診斷。
                _log.getLogger("telegram_inbound").warning(
                    "webhook update %s SKIPPED (dedup: watermark=%s) — "
                    "若此為真實 message，watermark 可能被 mock/test 推高",
                    upd_id, last_id,
                )
                return  # duplicate delivery (Telegram retry) — already processed
            # Telegram webhook test pings (update_id 999999998 / 999999999)
            # must NEVER advance the dedup watermark — they are not real
            # updates and a later real update_id (e.g. 392261534) would be
            # < 999999998 and dropped as a "duplicate" forever. This exact
            # bug silently killed the whole inbound path on 2026-08-06
            # (15:55 test ping blocked every subsequent real message).
            # Real update_ids are ~1e6–4e8; anything ≥ 9e8 is a test ping.
            if upd_id is not None and upd_id >= 900_000_000:
                return  # test ping — ignore entirely, keep watermark
            await process_update(mapping, data)
            if upd_id is not None:
                # ⚠️ 更新 watermark 必須用「獨立 session」— 唔可以用而家呢個
                # session：佢嘅 transaction snapshot 喺開頭 load mapping 時已固定
                # （MVCC），process_update → handle_telegram_message 用另一個
                # session 存入 pending_action_id / ai_session_id 之後，
                # 喺呢個舊 transaction 度 fresh re-load 都睇唔到（舊 snapshot）→
                # 照樣覆寫沖走 pending_action_id。
                # 新 session 嘅 SELECT 一定睇到 process_update 嘅 commit。
                async with async_session() as wm_db:
                    fresh = (
                        await wm_db.execute(
                            select(TelegramBotMapping).where(TelegramBotMapping.id == mapping.id)
                        )
                    ).scalar_one_or_none()
                    if fresh:
                        fresh_cfg: dict[str, Any] = dict(cast(dict[str, Any], fresh.config or {}))
                        fresh_cfg["tg_last_webhook_update_id"] = upd_id
                        fresh.config = cast(Any, fresh_cfg)
                        await wm_db.commit()
    except Exception:  # noqa: BLE001 — one bad update must not kill the webhook path
        _log.getLogger("telegram_inbound").exception(
            "webhook update processing failed: %s", str(data)[:200]
        )


async def webhook_queue_consumer(stop_event: asyncio.Event | None = None) -> None:
    """BRPOP loop over the durable Redis webhook queue.

    Runs once per gunicorn worker (spawned in lifespan). BRPOP guarantees
    each queued update is delivered to exactly ONE worker, so 4 workers =
    parallel consumption with zero duplicates. If the update was already
    processed (update_id dedup in handle_webhook_update), it's a no-op.

    IMPORTANT: uses redis.asyncio (NOT sync redis) — a sync brpop would
    block the whole event loop and make the API unresponsive.
    """
    import json as _json
    import logging as _log
    import redis.asyncio as redis_async

    log = _log.getLogger("telegram_inbound.queue")
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            r = redis_async.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
            while True:
                if stop_event is not None and stop_event.is_set():
                    return
                item = await r.brpop("tg:webhook:updates", timeout=5)
                if item is None:
                    continue
                try:
                    data = _json.loads(item[1])
                except Exception:
                    continue
                try:
                    await handle_webhook_update(data)
                except Exception:
                    log.exception("queue item processing failed: %s", str(data)[:200])
        except Exception:
            # Redis connection blip — back off 2s, keep the worker alive
            log.warning("redis queue consumer error, retrying in 2s")
            await asyncio.sleep(2)

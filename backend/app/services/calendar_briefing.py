"""Calendar T-15 AI briefing engine (P2, 2026-09-09).

Design: docs/calendar-crm-integration-design-v3-2026-09-09.md
- Entity match first (event→project→company = high confidence; company-name
  match on title = medium; none = low → show "未找到明確相關" + manual link).
- Tenant scan collects real data only; no CRM match → no AI call (cost).
- AI generation with strict grounding rules (data-presented sections only,
  ≤300 chars bullets, section-level source attribution).
- Dispatch reuses calendar_lifecycle_job channel helpers (in-app + Telegram;
  WhatsApp bypassed per user 2026-09-09).
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.calendar_lifecycle_job import (  # noqa: E402
    _channel_enabled,
    _inapp_notify,
    _push_channel,
    _utcnow,
)

HKT = timezone(timedelta(hours=8))

# Company-name tokens to hunt in the event title (english words ≥3 chars +
# the full title itself for CJK substring matching).
_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")

# 2026-09-11: generic words that say nothing about WHICH company is meant.
# Without this the title "HKHA Network Assessment Regular Meeting" matched
# "Exclusive Networks JJNet Hong Kong Limited" on the single word "network" and
# the briefing then presented that company's staff as fact — wrong data is worse
# than no data. A real match must rest on a distinctive word or the full name.
_STOP_TOKENS = {
    "the", "and", "for", "with", "from", "our", "new", "all",
    "meeting", "meet", "call", "review", "assessment", "eval", "evaluation",
    "network", "networking", "regular", "ad-hoc", "adhoc",
    "project", "discussion", "discuss", "sync", "update", "catch",
    "hong", "kong", "limited", "ltd", "company", "group", "team", "dept",
    "department", "internal", "external", "general", "annual",
    "quarterly", "monthly", "weekly", "daily", "biweekly",
    "kickoff", "kick-off", "workshop", "training", "presentation", "interview",
    "lunch", "dinner", "breakfast", "coffee", "visit", "site", "demo",
    "follow", "up", "followup", "check", "plan", "planning", "strategy",
    "report", "reporting", "session", "briefing", "share", "sharing",
}


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(HKT).strftime("%m/%d")


def _fmt_hm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(HKT).strftime("%H:%M")


async def _entity_match(db, tenant_id, user_id, ev) -> tuple[str | None, list[str], int]:
    """Match an event to CRM entities. Returns (company_id, contact_ids, confidence).

    Scoring (v3 §2.2 simplified — deterministic rules, no AI):
      project_id link (event→project→company) : 92
      company name token match on title        : 65-75
      contact name match → their company       : 70
      else                                      : <40 (low — no content shown)
    """
    # 1) event→project→company (highest confidence)
    if getattr(ev, "project_id", None):
        row = (
            await db.execute(
                text(
                    "SELECT p.company_id FROM nexus_crm.projects p "
                    "JOIN nexus_crm.project_calendar_events e ON e.project_id = p.id "
                    "WHERE e.id = :eid"
                ),
                {"eid": ev.id},
            )
        ).fetchone()
        if row and row[0]:
            return str(row[0]), [], 92

    title = (getattr(ev, "title", "") or "") + " " + (getattr(ev, "description", "") or "")
    if not title.strip():
        return None, [], 0

    # 2) company name tokens vs title
    companies = (
        await db.execute(
            text("SELECT id, name FROM nexus_crm.companies ORDER BY name")
        )
    ).fetchall()
    tokens = set(_TOKEN_RE.findall(title.lower()))
    best_cid: str | None = None
    best_score = 0
    ties = 0
    for cid, name in companies:
        score = 0
        name_l = (name or "").lower()
        # The WHOLE company name appearing in the title is a strong signal.
        if len(name_l) >= 4 and name_l in title.lower():
            score = max(score, 80)
        else:
            # Otherwise require a DISTINCTIVE shared word. Generic words are
            # skipped: matching on "network"/"meeting"/"hong" is exactly how a
            # stranger company's staff ended up in a real briefing.
            for tok in tokens:
                if tok in _STOP_TOKENS:
                    continue
                if len(tok) >= 4 and tok in name_l:
                    score = max(score, 70)
        # CJK substring: company's chinese segment appears verbatim in title
        cjk = re.sub(r"[A-Za-z0-9\s\.\,\-\(\)&]+", "", name or "")
        if len(cjk) >= 2 and cjk in title:
            score = max(score, 75)
        if score > best_score:
            best_score = score
            best_cid = str(cid)
            ties = 1
        elif score and score == best_score:
            ties += 1
    # An ambiguous match is NOT a match. Showing the wrong company's people as
    # fact is worse than saying we could not tell, so fall through to the
    # "no CRM record" path instead of guessing.
    if best_cid and ties == 1:
        return best_cid, [], best_score

    # 3) contact names in title → their company
    contacts = (
        await db.execute(
            text(
                "SELECT c.id, c.name, c.company_id FROM nexus_crm.contacts c "
                "WHERE c.company_id IS NOT NULL ORDER BY c.name"
            )
        )
    ).fetchall()
    title_l = title.lower()
    for cid, name, company_id in contacts:
        name_l = (name or "").lower()
        if len(name_l) >= 3 and name_l in title_l:
            return str(company_id), [str(cid)], 70
    return None, [], 0


async def _collect_context(db, company_id: str | None, contact_ids: list[str]) -> list[dict]:
    """Scan tenant for real CRM context around the matched entity."""
    sections: list[dict] = []
    if not company_id:
        return sections

    # Company
    comp = (
        await db.execute(
            text(
                "SELECT name, status, industry, phone FROM nexus_crm.companies WHERE id = :cid"
            ),
            {"cid": company_id},
        )
    ).fetchone()
    if comp and comp[0]:
        status_label = {"lead": "潛在", "prospect": "跟進中", "customer": "客戶", "partner": "夥伴"}.get(
            (comp[1] or "").lower(), comp[1] or ""
        )
        sections.append({"icon": "🏢", "label": "公司",
                         "content": f"{comp[0]}{('（' + status_label + '）') if status_label and status_label not in ('lead','prospect','customer','partner') else ''}",
                         "source": f"company:{company_id}"})

    # Contacts of the company (top 5 by name)
    contacts = (
        await db.execute(
            text(
                "SELECT name, job_title FROM nexus_crm.contacts "
                "WHERE company_id = :cid "
                "ORDER BY name LIMIT 5"
            ),
            {"cid": company_id},
        )
    ).fetchall()
    if contacts:
        parts = []
        for name, job in contacts:
            parts.append(f"{name}{('（' + job + '）') if job else ''}")
        sections.append({"icon": "👤", "label": "聯絡人", "content": "、".join(parts),
                         "source": f"contacts:{company_id}"})

    # Open tasks linked to the company (due soon first)
    tasks = (
        await db.execute(
            text(
                "SELECT title, due_date, priority FROM nexus_crm.tasks "
                "WHERE company_id = :cid AND status IN ('pending','in_progress') "
                "ORDER BY (due_date IS NULL), due_date ASC, priority DESC LIMIT 5"
            ),
            {"cid": company_id},
        )
    ).fetchall()
    if tasks:
        lines = []
        for title, due, prio in tasks:
            tag = ""
            if prio in ("high", "urgent"):
                tag = "🔴"
            due_s = _fmt_date(due) if due else "未定"
            lines.append(f"{tag}{title}（due {due_s}）")
        sections.append({"icon": "✅", "label": "未完成任務", "content": "\n".join(lines),
                         "source": f"tasks:{company_id}"})

    # Projects linked to the company
    projects = (
        await db.execute(
            text(
                "SELECT name, budget_amount FROM nexus_crm.projects "
                "WHERE company_id = :cid ORDER BY created_at DESC LIMIT 3"
            ),
            {"cid": company_id},
        )
    ).fetchall()
    if projects:
        lines = []
        for name, budget in projects:
            if budget:
                lines.append(f"{name}（HK${float(budget):,.0f}）")
            else:
                lines.append(name)
        sections.append({"icon": "📁", "label": "項目", "content": "\n".join(lines),
                         "source": f"projects:{company_id}"})

    # Recent touchpoints (company-wide, last 3)
    tp = (
        await db.execute(
            text(
                "SELECT type, title, date FROM nexus_crm.touchpoints "
                "WHERE company_id = :cid ORDER BY date DESC LIMIT 3"
            ),
            {"cid": company_id},
        )
    ).fetchall()
    if tp:
        lines = []
        for ttype, title, date in tp:
            type_icon = {"meeting": "🤝", "call": "📞", "email": "📧", "lunch": "🍽", "note": "📝"}.get(
                (ttype or "").lower(), "📌")
            lines.append(f"{type_icon} {_fmt_date(date)} {title}")
        sections.append({"icon": "💡", "label": "最近接觸", "content": "\n".join(lines),
                         "source": f"touchpoints:{company_id}"})
    return sections


async def _ai_briefing(db, tenant_id, user_id, ev, sections: list[dict], confidence: int) -> str | None:
    """Generate a concise pre-meeting briefing via the default adapter."""
    from app.routers.ai import _default_adapter

    sections_txt = "\n".join(
        f"[{s['label']}] {s['content']}" for s in sections
    )
    sys_prompt = (
        "你係 CRM 會前 Briefing 助手。\n"
        "硬性規則：\n"
        "用繁體中文（廣東話語感）書面語\n"
        "全部 bullet points，每行一個 fact，高密度\n"
        "只可以用下面提供嘅 CRM 資料 — 嚴禁自己作任何資料（公司名/數字/日期都唔准作）\n"
        "冇資料嘅範疇就唔好提\n"
        "「Why this matters」係可選、唔係必須：只有當資料支持一個具體而唔明顯嘅行動點才寫"
        "（例如「有 2 個任務今日到期，可即場確認」）。資料唔夠就整段唔好寫。\n"
        "嚴禁把欄位當洞見重述 —— 例：「佢係 Channel Manager，所以可以傾渠道事宜」係廢話，唔准寫。\n"
        "寧短勿濫：冇實質內容就唔好勉強填。\n"
        "唔好加 commentary、感想、encouragement 尾句\n"
        "總長度 ≤ 300 字"
    )
    user_prompt = (
        f"Event：{getattr(ev, 'title', '')}（{_fmt_date(getattr(ev, 'start', None))} "
        f"{_fmt_hm(getattr(ev, 'start', None))}）\n\n"
        f"CRM 相關資料：\n{sections_txt}\n\n"
        "請整理成會前 Briefing。"
    )
    adapter = _default_adapter()
    try:
        content, _usage = await adapter.chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=600,
        )
    finally:
        await adapter.close()
    return (content or "").strip() or None


async def dispatch_t15(db, tenant_id, user_id, ev) -> dict:
    """Full T-15 pipeline: entity match → context scan → AI → send. (P2)"""
    result = {"confidence": 0, "company_id": None, "briefing": None, "sent": False, "low": False}

    company_id, contact_ids, confidence = await _entity_match(db, tenant_id, user_id, ev)
    result["confidence"] = confidence
    result["company_id"] = company_id

    sections = await _collect_context(db, company_id, contact_ids) if company_id else []

    if not sections:
        # Q2 (2026-09-09): low confidence still scans (done above — no match);
        # we show a plain "no CRM record found" note, no guessing.
        result["low"] = True
        body = (
            f"🧠 會議前 Briefing\n"
            f"⏰ {_fmt_date(getattr(ev, 'start', None))} "
            f"{_fmt_hm(getattr(ev, 'start', None))} — {getattr(ev, 'title', '')}\n"
            f"🔍 未找到明確相關的 CRM 記錄\n"
            f"（你可以喺 CRM 手動關聯公司，下次 briefing 就會自動帶出資料）"
        )
    else:
        briefing = await _ai_briefing(db, tenant_id, user_id, ev, sections, confidence)
        if not briefing:
            result["low"] = True
            return result
        result["briefing"] = briefing
        # 2026-09-11: show WHAT was matched and HOW sure we are. A wrong company
        # used to be indistinguishable from a right one — the operator only found
        # out by reading the names. With the reason on the line, a bad match is
        # obvious at a glance and the weaker matches say 請確認 instead of
        # pretending to be certain.
        comp_name = next((s["content"] for s in sections if s.get("label") == "公司"), "")
        if confidence >= 90:
            conf_label = "明確關聯"
        elif confidence >= 80:
            conf_label = "公司名完全吻合"
        elif confidence >= 75:
            conf_label = "公司名（中文）吻合"
        else:
            conf_label = "名稱部分吻合 — 請確認"
        match_line = f"🔗 關聯：{comp_name}（{conf_label}）" if comp_name else ""
        head = (
            f"🧠 會議前 Briefing\n"
            f"⏰ {_fmt_date(getattr(ev, 'start', None))} "
            f"{_fmt_hm(getattr(ev, 'start', None))} — {getattr(ev, 'title', '')}"
            + (f"\n{match_line}" if match_line else "")
        )
        body = f"{head}\n\n{briefing}"

    # Dispatch: in-app (always) + Telegram. WhatsApp bypassed (user 2026-09-09).
    inapp_ok = await _inapp_notify(db, tenant_id, user_id, ev, body, title=f"🧠 會前 Briefing：{getattr(ev, 'title', '')}")
    tg_result = "skipped"
    if await _channel_enabled(db, tenant_id, user_id, "telegram"):
        tg_result = await _push_channel(db, tenant_id, user_id, "telegram", body)
    result["sent"] = inapp_ok or tg_result == "sent"
    result["channels"] = {"inapp": inapp_ok, "telegram": tg_result}
    return result

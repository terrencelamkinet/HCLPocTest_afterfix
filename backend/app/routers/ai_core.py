"""AI Core Engine — grounded answers w/ citations, field autofill, tenant AI admin reads.

App-level endpoints (no system permission): retrieval reuses the CRM search
pipeline (`_search_crm_context` + TOOL_REGISTRY handlers), generation goes
through the same provider adapter as /chat (DeepSeek by default). All data
is tenant-scoped via the request's RLS session.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.ai.provider import ProviderCredential

router = APIRouter(prefix="/api/v1/crm/ai", tags=["AI Core"])


# ═══════════════════════════════════════════════════════════
# 天氣問題偵測 + HKO icon map（2026-09-08 fix — Terrence:
# 「Fix Ai issues」— 企鵝管家答「無法存取外部天氣」）
# ═══════════════════════════════════════════════════════════
_WEATHER_RE = re.compile(
    r"天氣|氣溫|溫度|凍|熱|落雨|降雨|下雨|天文台|濕度|風速|幾多度|會唔會",
    re.IGNORECASE,
)


def _is_weather_question(q: str) -> bool:
    return bool(_WEATHER_RE.search(q))


def _hko_icon_desc(icon: Any) -> tuple[str, str]:
    """HKO rhrread icon code → (中文描述, emoji)。鏡像 ai.py 嘅 mapping。"""
    try:
        n = int(icon)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "天氣", "🌤️"
    if n <= 50:
        return "天晴", "☀️"
    if n == 51:
        return "短暫陽光", "🌤️"
    if n == 52:
        return "間中多雲", "🌥️"
    if 53 <= n <= 55:
        return "多雲", "☁️"
    if 60 <= n <= 65:
        return "微雨", "🌦️"
    if 70 <= n <= 73:
        return "下雨", "🌧️"
    if 74 <= n <= 79:
        return "大雨/雷暴", "⛈️"
    if 80 <= n <= 88:
        return "有霧", "🌫️"
    if n >= 91:
        return "大風", "💨"
    return "多雲", "☁️"

# Provider chain mirrors /chat (tenant module_settings.ai can override)
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"

_TYPE_TO_PATH = {
    "company": "/companies/",
    "contact": "/contacts/",
    "deal": "/deals/",
    "project": "/projects/",
    "task": "/tasks/",
    "touchpoint": "/touchpoints/",
    "namecard": "/namecards/",
}
_TOOL_TO_TYPE = {
    "search_companies": "company",
    "get_company_detail": "company",
    "search_contacts": "contact",
    "get_contact_detail": "contact",
    "search_deals": "deal",
    "search_projects": "project",
    "list_tasks": "task",
    "company_tasks": "task",
    "related_tasks": "task",
    "list_touchpoints": "touchpoint",
    "related_touchpoints": "touchpoint",
}


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ThreadTurn(BaseModel):
    role: str
    content: str


class GroundedAnswerRequest(BaseModel):
    question: str
    scope: str = "page"  # 'page' | 'workspace'
    record: dict[str, Any] | None = None  # {type, id, name}
    context: list[ThreadTurn] = []


class CitedSource(BaseModel):
    index: int
    type: str
    title: str
    snippet: str
    href: str


class GroundedAnswerResponse(BaseModel):
    answer: str
    sources: list[CitedSource]
    followups: list[str]


class AutofillRequest(BaseModel):
    record_type: str  # company|contact|deal|project|task|touchpoint|namecard
    record_id: UUID
    field: str = "summary"
    mode: str = "summary"  # summary|tags|key_info|custom
    prompt: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(request: Request):
    ctx = getattr(request.state, "ai_context", None)
    if not ctx:
        raise HTTPException(400, "AI session context not initialized")
    return ctx


async def _adapter():
    from app.routers.ai import _default_adapter

    return _default_adapter()


def _item_title(item: dict[str, Any]) -> str:
    for k in ("name", "title", "summary"):
        if item.get(k):
            v = str(item[k])
            if item.get("chinese_name"):
                v = f"{v} ({item['chinese_name']})"
            comp = item.get("company")
            if isinstance(comp, dict) and comp.get("name"):
                v = f"{v} @ {comp['name']}"
            return v
    return str(item.get("id", "?"))[:24]


def _item_snippet(item: dict[str, Any], max_len: int = 140) -> str:
    for k in ("summary", "notes", "description", "email", "phone", "status"):
        if item.get(k):
            return str(item[k])[:max_len]
    parts = [f"{k}: {v}" for k, v in item.items() if not isinstance(v, (dict, list)) and v is not None]
    return ", ".join(parts)[:max_len] if parts else ""


async def _record_usage(db, ctx, usage, module: str):
    try:
        from app.routers.ai import _record_usage_event

        await _record_usage_event(db, ctx, None, usage, module=module)
    except Exception:
        pass  # best-effort


async def _flatten_sources(
    crm_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[CitedSource]]:
    """Flatten _search_crm_context output into prompt records + CitedSource list."""
    records: list[dict[str, Any]] = []
    sources: list[CitedSource] = []
    idx = 1
    for tool_key, data in crm_context.items():
        rtype = _TOOL_TO_TYPE.get(tool_key)
        if rtype is None or not isinstance(data, list):
            continue
        for item in data[:6]:
            rid = item.get("id")
            if not rid:
                continue
            title = _item_title(item)
            snippet = _item_snippet(item)
            records.append(
                {
                    "index": idx,
                    "type": rtype,
                    "title": title,
                    "snippet": snippet,
                    "raw": item,
                }
            )
            sources.append(
                CitedSource(
                    index=idx,
                    type=rtype,
                    title=title,
                    snippet=snippet,
                    href=f"{_TYPE_TO_PATH.get(rtype, '/')}{rid}",
                )
            )
            idx += 1
    return records, sources


async def _page_scope_context(record: dict[str, Any], ctx, db) -> dict[str, Any]:
    """scope='page': retrieve the record + its directly related records only."""
    from app.ai.tool_registry import TOOL_REGISTRY

    rtype = (record.get("type") or "").lower()
    rid = record.get("id")
    if not rid:
        return {}
    out: dict[str, Any] = {}
    tool_calls: list[tuple[str, str, dict]] = []

    if rtype == "company":
        tool_calls = [
            ("get_company_detail", "get_company_detail", {"company_id": rid}),
            ("search_projects", "related_projects", {"company_id": rid, "limit": 10}),
            ("list_tasks", "company_tasks", {"company_id": rid, "limit": 10}),
            ("list_touchpoints", "related_touchpoints", {"company_id": rid, "limit": 10}),
        ]
    elif rtype == "contact":
        tool_calls = [
            ("get_contact_detail", "get_contact_detail", {"contact_id": rid}),
            ("list_touchpoints", "related_touchpoints", {"contact_id": rid, "limit": 10}),
            ("list_tasks", "related_tasks", {"contact_id": rid, "limit": 10}),
        ]
    elif rtype == "deal":
        tool_calls = [("get_deal_detail", "get_deal_detail", {"deal_id": rid})] if "get_deal_detail" in TOOL_REGISTRY else []
    elif rtype == "project":
        tool_calls = [
            ("list_tasks", "related_tasks", {"project_id": rid, "limit": 10}),
            ("list_touchpoints", "related_touchpoints", {"project_id": rid, "limit": 10}),
        ]
    elif rtype == "task":
        tool_calls = [("list_tasks", "related_tasks", {"id": rid, "limit": 10})]

    for tool_key, label, params in tool_calls:
        tool = TOOL_REGISTRY.get(tool_key)
        if not tool or not tool.handler:
            continue
        try:
            result = await tool.handler(ctx, params, db)
            if result is not None and not (isinstance(result, list) and len(result) == 0):
                out[label] = result
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# 1. Grounded answer (Perplexity-style)
# ---------------------------------------------------------------------------


@router.post("/grounded-answer", response_model=GroundedAnswerResponse)
async def grounded_answer(
    body: GroundedAnswerRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    ctx = _ctx(request)
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "question is required")

    # ── 1. Retrieve ─────────────────────────────────────────────────────
    # 2026-09-08 fix（Terrence: AI 答「無法存取外部天氣」）: 天氣問題 → 注入 HKO 實時天氣
    # 做 record（grounded-answer 規則保持 — AI 引用 [1] 答，唔靠內部知識）
    weather_record = None
    if _is_weather_question(question):
        try:
            from app.ai import briefing_sources as bs

            wl = await bs.weather(ctx, db)
            if wl and wl[0].get("temperature") is not None:
                w = wl[0]
                icon = w.get("icon") or 0
                desc, emoji = _hko_icon_desc(icon)
                parts = [f"溫度 {w['temperature']}°C"]
                if w.get("humidity"):
                    parts.append(f"濕度 {w['humidity']}%")
                if w.get("wind"):
                    parts.append(f"風 {w['wind']}")
                if w.get("rainfall"):
                    parts.append(f"雨量 {w['rainfall']}mm")
                weather_record = {
                    "index": 1,
                    "type": "weather",
                    "title": f"香港而家天氣 {emoji} {desc}",
                    "snippet": " · ".join(parts),
                }
        except Exception:
            weather_record = None

    if weather_record is not None:
        records, sources = [weather_record], []
    else:
        if body.scope == "page" and body.record and body.record.get("id"):
            crm_context = await _page_scope_context(body.record, ctx, db)
        else:
            from app.routers.ai import _search_crm_context

            crm_context = await _search_crm_context(question, ctx, db)
        records, sources = await _flatten_sources(crm_context)

    # ── 2. Build prompt ──────────────────────────────────────────────────
    history_str = ""
    if body.context:
        history_str = "\n".join(
            f"{t.role}: {t.content}" for t in body.context[-8:]
        )

    if records:
        records_str = "\n".join(
            f"[{r['index']}] ({r['type']}) {r['title']} — {r['snippet']}"
            for r in records
        )
    else:
        records_str = "(no matching CRM records found)"

    system = (
        "你係 Penguin CRM 嘅 AI 助理。回答用戶問題時必須嚴格遵守以下規則：\n"
        "1. **Grounded Answer**：答案只可以基於以下編號 CRM 記錄 [1] [2] [3]...，"
        "喺相關句子後面插入引用標記，例如「Kinetix 係我哋客戶[1]」。\n"
        "2. 如果提供嘅記錄入面搵唔到相關資料，必須明確回答「喺 CRM 記錄入面搵唔到相關資料」，"
        "絕對唔可以憑你嘅內部知識作答。\n"
        "3. 用繁體中文書面語，簡潔、具體，有日期就寫日期。\n"
        "4. 最後生成 3 條用戶可能想繼續追問嘅問題（根據答案同記錄內容）。\n\n"
        "**輸出格式：必須輸出純 JSON（唔好加 markdown fence 或者其他文字），結構如下：\n"
        '{"answer": "你嘅完整答案（含 [1] 引用標記）", "followups": ["延伸問題1", "延伸問題2", "延伸問題3"]}\n\n'
        "以下係之前嘅對話記錄（如有）：\n"
        f"{history_str or '(無)'}\n\n"
        f"CRM 記錄：\n{records_str}"
    )
    user_msg = f"問題：{question}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    # ── 3. Generate ─────────────────────────────────────────────────────
    # Weekly plan quota guard (SPEC docs/ai-usage-quota-SPEC.md) — 統一 quota
    from app.ai.quota.weekly import enforce_weekly_quota, refund_request

    weekly_block = await enforce_weekly_quota(db, ctx.tenant_id, ctx.user_id)
    if weekly_block:
        raise HTTPException(429, weekly_block["message"])
    adapter = await _adapter()
    try:
        raw, usage = await adapter.chat(
            messages=messages,
            model=DEFAULT_MODEL,
            temperature=0.3,
            max_tokens=1200,
        )
    except Exception as e:
        # reserve-then-refund — 失敗嘅 call 唔扣週 quota
        try:
            await refund_request(db, ctx.tenant_id, ctx.user_id)
        except Exception:
            pass
        raise HTTPException(502, f"LLM call failed: {e}")

    try:
        await _record_usage(db, ctx, usage, module="grounded_answer")
    except Exception:
        pass

    answer = raw.strip()
    followups: list[str] = []

    # Try to parse JSON envelope {answer, followups}; fall back to raw text.
    try:
        parsed = json.loads(answer)
        if isinstance(parsed, dict) and parsed.get("answer"):
            answer = str(parsed["answer"]).strip()
            fups = parsed.get("followups") or []
            followups = [str(f) for f in fups][:3]
    except (json.JSONDecodeError, AttributeError):
        # strip a possible ```json fence
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", answer, re.S)
        if m:
            try:
                parsed = json.loads(m.group(1))
                if parsed.get("answer"):
                    answer = str(parsed["answer"]).strip()
                    followups = [str(f) for f in (parsed.get("followups") or [])][:3]
            except json.JSONDecodeError:
                pass

    return GroundedAnswerResponse(answer=answer, sources=sources, followups=followups)


# ---------------------------------------------------------------------------
# 2. Field autofill (Notion AI-style)
# ---------------------------------------------------------------------------


@router.post("/autofill")
async def autofill(
    body: AutofillRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    ctx = _ctx(request)
    from app.routers.ai import _get_ai_module_settings

    # ── Load record + related content ───────────────────────────────────
    table_map = {
        "company": "nexus_crm.companies",
        "contact": "nexus_crm.contacts",
        "deal": "nexus_crm.deals",
        "project": "nexus_crm.projects",
        "task": "nexus_crm.tasks",
        "touchpoint": "nexus_crm.touchpoints",
        "namecard": "nexus_crm.name_cards",
    }
    table = table_map.get(body.record_type)
    if not table:
        raise HTTPException(422, f"unsupported record_type: {body.record_type}")

    row = (
        await db.execute(
            text(f"SELECT * FROM {table} WHERE id = :rid"),
            {"rid": str(body.record_id)},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(404, "record not found")

    content_parts: list[str] = []
    for k, v in row.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        if k in ("id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by"):
            continue
        content_parts.append(f"{k}: {v}")

    # Related touchpoints/notes for context
    related: list[tuple[str, str]] = []
    if body.record_type in ("company", "contact"):
        fk = "company_id" if body.record_type == "company" else "contact_id"
        try:
            tps = (
                await db.execute(
                    text(
                        f"SELECT title, description FROM nexus_crm.touchpoints "
                        f"WHERE tenant_id = :tid AND {fk} = :rid ORDER BY date DESC NULLS LAST LIMIT 8"
                    ),
                    {"tid": str(ctx.tenant_id), "rid": str(body.record_id)},
                )
            ).mappings().all()
            for tp in tps:
                s = tp.get("title") or tp.get("description") or ""
                if s:
                    related.append(("touchpoint", str(s)))
        except Exception:
            pass

    ctx_str = "\n".join(content_parts[:40])
    related_str = "\n".join(f"- ({t}) {c}" for t, c in related[:8])

    mode_prompts = {
        "summary": "根據記錄內容，用 1-2 句繁體中文概括呢個記錄嘅重點（適合放喺 summary 欄位）。直接輸出摘要內容。",
        "tags": "根據記錄內容，建議 3-5 個分類標籤（繁體中文或英文均可），用逗號分隔。直接輸出標籤。",
        "key_info": "抽取記錄嘅關鍵資訊（金額、日期、聯絡人、公司、狀態等），用結構化清單列出。直接輸出。",
        "custom": body.prompt or "根據記錄內容生成有價值嘅摘要。",
    }
    instruction = mode_prompts.get(body.mode, mode_prompts["summary"])

    messages = [
        {
            "role": "system",
            "content": (
                "你係 Penguin CRM 嘅 AI 助理，負責根據記錄內容自動填寫欄位。"
                f"目標欄位：{body.field}。\n"
                "只可以根據以下記錄內容生成，唔可以憑空捏造；內容不足就寫「（資料不足）」"
                "而唔好作嘢。\n"
                f"任務：{instruction}"
            ),
        },
        {
            "role": "user",
            "content": f"記錄內容：\n{ctx_str}\n\n相關互動記錄：\n{related_str or '(無)'}",
        },
    ]

    adapter = await _adapter()
    try:
        # Weekly plan quota guard — 用晒直接 block，唔 call LLM
        from app.ai.quota.weekly import enforce_weekly_quota, refund_request

        weekly_block = await enforce_weekly_quota(db, ctx.tenant_id, ctx.user_id)
        if weekly_block:
            raise HTTPException(429, weekly_block["message"])
        raw, usage = await adapter.chat(
            messages=messages,
            model=DEFAULT_MODEL,
            temperature=0.3,
            max_tokens=600,
        )
    except HTTPException:
        raise
    except Exception as e:
        # reserve-then-refund — 失敗嘅 call 唔扣週 quota
        try:
            await refund_request(db, ctx.tenant_id, ctx.user_id)
        except Exception:
            pass
        raise HTTPException(502, f"LLM call failed: {e}")

    try:
        await _record_usage(db, ctx, usage, module="autofill")
    except Exception:
        pass

    value = raw.strip().strip('"')
    # tags mode → comma-separated list
    if body.mode == "tags":
        tags = [t.strip() for t in value.replace("，", ",").split(",") if t.strip()]
        value = ", ".join(tags[:6])

    return {"value": value, "mode": body.mode, "field": body.field}


# ---------------------------------------------------------------------------
# 3. Tenant AI admin reads (agent list + provider health)
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """List enabled AI agents (for the Agent Switcher). No system exposure."""
    ctx = _ctx(request)
    rows = (
        await db.execute(
            text(
                """
                SELECT id, agent_key, display_name, description, max_scope
                FROM nexus_ai.ai_agents
                WHERE tenant_id = :tid AND is_enabled = TRUE
                ORDER BY agent_key
                """
            ),
            {"tid": str(ctx.tenant_id)},
        )
    ).mappings().all()
    return {
        "agents": [
            {
                "id": str(r["id"]),
                "key": r["agent_key"],
                "name": r["display_name"],
                "description": r["description"],
                "scope": r["max_scope"],
            }
            for r in rows
        ]
    }


@router.get("/provider-health")
async def provider_health(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Read-only provider credential metadata (never exposes key material)."""
    ctx = _ctx(request)
    rows = (
        await db.execute(
            text(
                """
                SELECT provider, is_byok, status, last_health_check_at, created_at
                FROM nexus_ai.provider_credentials
                WHERE tenant_id = :tid AND status = 'active'
                ORDER BY created_at DESC
                """
            ),
            {"tid": str(ctx.tenant_id)},
        )
    ).mappings().all()
    providers = []
    for r in rows:
        expires = None
        if r["last_health_check_at"]:
            try:
                last = r["last_health_check_at"]
                if isinstance(last, datetime):
                    expires = max(1, 30 - (datetime.now(timezone.utc) - last).days)
            except Exception:
                pass
        providers.append(
            {
                "provider": r["provider"],
                "is_byok": r["is_byok"],
                "status": "connected" if r["status"] == "active" else r["status"],
                "expires_in_days": expires,
            }
        )
    return {"providers": providers}

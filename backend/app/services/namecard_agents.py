"""NameCard Agent Pipeline — sequential orchestration of 5 agent roles.

架構文檔 (§Agent 架構：五個核心Agent角色 + §Agent編排模式選擇):

    Signal Ingestion → Extraction → Entity Resolution → Enrichment → Inference

Each step runs through a named agent, snapshots its input/output, records
confidence + decision, and writes one row to nexus_crm.ai_agent_log for full
auditability. Every LLM call is fail-safe: on API error the step falls back
to heuristic output and `success=False` — enrichment never breaks upload.

Confidence tiers (架構文檔 §Human-in-the-Loop 三級信心分層):
    HIGH   > 0.95  → auto-execute, log only (exact email/phone match)
    MEDIUM 0.7-0.95 → review: user chooses override vs keep-both
    LOW    < 0.7   → mark pending, no automatic write
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from app.models.crm import AiAgentLog
from app.services import namecard_llm

AGENT_VERSION = "agents-v1"

# Confidence tier thresholds (架構文檔 §三級信心分層)
TIER_HIGH = 0.95
TIER_MEDIUM = 0.70


def _jsonable(obj: Any) -> Any:
    """Recursively convert UUID/datetime → str so snapshots survive asyncpg JSON."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (uuid.UUID, datetime, date)):
        return str(obj)
    return obj


class AgentStep:
    """One agent execution in the pipeline (logged to ai_agent_log)."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.provider = "heuristic"
        self.model = ""
        self.decision = ""
        self.confidence = 0.0
        self.output: dict[str, Any] = {}
        self.input_snapshot: dict[str, Any] = {}
        self.latency_ms = 0
        self.success = True
        self._t0 = time.monotonic()

    def finish(self, *, provider: str = "heuristic", model: str = "",
               decision: str, confidence: float, output: dict[str, Any],
               success: bool = True) -> "AgentStep":
        self.latency_ms = int((time.monotonic() - self._t0) * 1000)
        self.provider = provider
        self.model = model
        self.decision = decision
        self.confidence = round(float(confidence), 3)
        self.output = output
        self.success = success
        return self

    def as_log_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_version": AGENT_VERSION,
            "provider": self.provider,
            "model": self.model,
            "input_snapshot": self.input_snapshot,
            "output_snapshot": self.output,
            "confidence": self.confidence,
            "decision": self.decision,
            "latency_ms": self.latency_ms,
            "success": self.success,
        }


# ── Agent 1: Signal Ingestion ─────────────────────────────────────────
def ingestion_agent(raw_text: str, parsed_heuristic: dict[str, Any],
                    image_url: str) -> AgentStep:
    """Standardise the raw signal. No judgement, just format normalisation."""
    step = AgentStep("ingestion")
    step.input_snapshot = {
        "raw_text_len": len(raw_text or ""), "image_url": image_url,
        "heuristic_fields": list(parsed_heuristic.keys()),
    }
    signal = {
        "raw_ocr_text": (raw_text or "")[:4000],
        "parsed": parsed_heuristic or {},
        "image_url": image_url,
    }
    return step.finish(
        decision="normalise",
        confidence=1.0,
        output={"signal": signal},
    )


# ── Agent 2: Extraction ───────────────────────────────────────────────
def extraction_agent(signal: dict[str, Any], usage_out: list | None = None) -> AgentStep:
    """LLM (DeepSeek JSON mode): raw OCR text → clean structured fields."""
    step = AgentStep("extraction")
    raw = signal.get("raw_ocr_text", "")
    heuristic = signal.get("parsed", {})
    step.input_snapshot = {"raw_text": raw[:500], "heuristic": heuristic}
    llm_parsed = namecard_llm.llm_structured(raw, usage_out=usage_out)
    merged = dict(heuristic)
    for k, v in llm_parsed.items():
        if v:
            merged[k] = v
    return step.finish(
        provider="deepseek" if llm_parsed else "heuristic",
        model=namecard_llm.DEEPSEEK_MODEL if llm_parsed else "",
        decision="extract",
        confidence=0.9 if llm_parsed else 0.5,
        output={"parsed": merged},
        success=bool(llm_parsed),
    )


# ── Agent 3: Entity Resolution ────────────────────────────────────────
def entity_resolution_agent(parsed: dict[str, Any],
                            existing_contacts: list[dict[str, Any]],
                            company_id: Any,
                            usage_out: list | None = None) -> AgentStep:
    """Three layers: exact match → semantic similarity → LLM verdict.

    Returns tier routing decision: auto_link | review | create.
    """
    step = AgentStep("entity_resolution")
    email = (parsed.get("email") or "").strip().lower()
    phone = (parsed.get("phone") or "").strip()
    person_name = (parsed.get("name") or "").strip()

    # Layer 1 — exact unique identifiers
    exact = None
    exact_key = ""
    for c in existing_contacts:
        if email and (c.get("email") or "").strip().lower() == email:
            exact, exact_key = c, "email"
            break
        if phone:
            pd = "".join(ch for ch in phone if ch.isdigit())
            cd = "".join(ch for ch in (c.get("phone") or "") if ch.isdigit())
            od = "".join(ch for ch in (c.get("office_phone") or "") if ch.isdigit())
            if pd and (pd in cd or pd in od):
                exact, exact_key = c, "phone"
                break
    if exact is not None:
        return step.finish(
            decision="auto_link",
            confidence=0.98,
            output={"tier": "high", "candidate": exact, "match_key": exact_key,
                    "reason": f"exact {exact_key} match"},
        )

    # Layer 2 — semantic similarity (name_similarity as vector-layer fallback)
    _pn = person_name.lower()
    _name_tokens = [t for t in _pn.replace(",", " ").split() if len(t) >= 2]
    _email_domain = email.split("@")[-1] if email else ""
    candidates: list[dict[str, Any]] = []
    for c in existing_contacts:
        _cname = (c.get("name") or "").lower()
        name_hit = bool(_name_tokens and any(t in _cname for t in _name_tokens))
        sim = namecard_llm.name_similarity(person_name, c.get("name") or "")
        company_hit = bool(company_id and c.get("company_id") and
                           str(c["company_id"]) == str(company_id))
        domain_hit = bool(_email_domain and c.get("email") and
                          c["email"].lower().endswith("@" + _email_domain))
        if name_hit or company_hit or domain_hit:
            candidates.append({
                "id": str(c.get("id")), "name": c.get("name") or "",
                "chinese_name": c.get("chinese_name") or "",
                "title": c.get("job_title") or "",
                "company": c.get("company_name") or "",
                "company_id": str(c.get("company_id") or ""),
                "email": c.get("email") or "", "phone": c.get("phone") or "",
                "office_phone": c.get("office_phone") or "",
                "_similarity": round(sim, 3),
            })

    if not candidates:
        return step.finish(
            decision="create",
            confidence=0.8,
            output={"tier": "high", "candidate": None, "reason": "no candidates"},
        )

    # Layer 3 — LLM verdict on the grey zone
    llm_card = {k: parsed.get(k, "") for k in
                ("name", "chinese_name", "title", "company", "email", "phone")}
    dup = namecard_llm.llm_duplicate_analysis(llm_card, candidates, usage_out=usage_out)
    conf = float(dup.get("confidence") or 0.0)
    is_dup = bool(dup.get("is_duplicate")) and bool(dup.get("candidate_id"))

    if is_dup and conf >= TIER_MEDIUM:
        cand = next((c for c in candidates if c["id"] == dup["candidate_id"]), None)
        tier = "high" if conf >= TIER_HIGH else "medium"
        decision = "auto_link" if tier == "high" else "review"
        return step.finish(
            provider="deepseek", model=namecard_llm.DEEPSEEK_MODEL,
            decision=decision, confidence=conf,
            output={"tier": tier, "candidate": cand, "match_key": "llm",
                    "reason": dup.get("reason") or "",
                    "similarities": [c["_similarity"] for c in candidates]},
        )

    # Low confidence — no automatic write, flag for human review
    return step.finish(
        provider="deepseek" if dup else "heuristic",
        model=namecard_llm.DEEPSEEK_MODEL if dup else "",
        decision="create_pending_review",
        confidence=conf if is_dup else max(
            (c["_similarity"] for c in candidates), default=0.0),
        output={"tier": "low", "candidate": candidates[0] if candidates else None,
                "reason": dup.get("reason") or "weak signal only"},
        success=bool(dup),
    )


# ── Agent 4: Enrichment ───────────────────────────────────────────────
def enrichment_agent(company_name: str, usage_out: list | None = None) -> AgentStep:
    """Perplexity sonar: web-search the company → fill missing fields.

    Output carries source_url + confidence so humans can verify AI guesses
    (架構文檔 §Enrichment Agent 輸出必須帶 confidence_score 同 source_url).
    """
    step = AgentStep("enrichment")
    step.input_snapshot = {"company_name": company_name}
    research = namecard_llm.llm_company_research(company_name, usage_out=usage_out)
    filled = {k: v for k, v in research.items() if v}
    conf = float(research.get("confidence") or 0.0)
    return step.finish(
        provider="perplexity" if research else "heuristic",
        model=namecard_llm.PERPLEXITY_MODEL if research else "",
        decision="enrich",
        confidence=conf or (0.7 if filled else 0.0),
        output={"research": research, "filled_fields": list(filled.keys()),
                "source_url": research.get("source_url") or ""},
        success=bool(research),
    )


# ── Agent 5: Inference ────────────────────────────────────────────────
def inference_agent(parsed: dict[str, Any],
                    recent_events: list[dict[str, Any]],
                    usage_out: list | None = None) -> AgentStep:
    """DeepSeek triple-verification: could this person have been met recently?

    Auto-link only when time + location + company all match; otherwise a weak
    hint (架構文檔 §階段四).
    """
    step = AgentStep("inference")
    step.input_snapshot = {
        "card": {k: parsed.get(k, "") for k in ("name", "company", "title")},
        "events": [{"title": e.get("title"), "date": str(e.get("date"))[:10],
                    "location": e.get("location")} for e in recent_events[:10]],
    }
    result = namecard_llm.llm_context_suggestion(parsed, recent_events, usage_out=usage_out)
    verif = result.get("verification") or {}
    checks = [bool(verif.get("time")), bool(verif.get("location")),
              bool(verif.get("company"))]
    n_checks = sum(checks)
    conf = float(result.get("confidence") or 0.0)
    decision = "suggest_link" if n_checks >= 3 else (
        "weak_hint" if n_checks >= 1 else "none")
    return step.finish(
        provider="deepseek" if result.get("suggestion") else "heuristic",
        model=namecard_llm.DEEPSEEK_MODEL if result.get("suggestion") else "",
        decision=decision,
        confidence=conf if n_checks >= 1 else 0.0,
        output={"suggestion": result.get("suggestion") or "",
                "matched_event": result.get("matched_event") or "",
                "verification": verif, "checks_passed": n_checks},
        success=bool(result.get("suggestion")),
    )


# ── Data completeness (架構文檔 §Database Schema 擴充建議) ──────────
# Company 欄位完整率：name/industry/size/address/website/phone/ceo_name/
# linkedin_url 8 個高價值欄位，每月監測、AI 持續識別需要優先補全嘅記錄。
_COMPLETENESS_FIELDS = (
    "name", "industry", "size", "address", "website",
    "phone", "ceo_name", "linkedin_url",
)


def company_completeness_pct(company: dict[str, Any]) -> int:
    """0-100 — fraction of high-value Company fields that are non-empty."""
    filled = sum(1 for f in _COMPLETENESS_FIELDS if (company.get(f) or "").strip())
    return int(round(filled / len(_COMPLETENESS_FIELDS) * 100))


# ── Sequential orchestration ──────────────────────────────────────────
async def _record_namecard_usage(
    db: AsyncSession,
    tenant_id: Any,
    usage_reports: list[dict[str, Any]],
) -> None:
    """Write UsageEvent rows from namecard LLM calls (core rule G08).

    ``usage_reports`` entries: {provider, model, input_tokens, output_tokens,
    cost_usd}. Namecard pipeline has no chat session → session_id=None.
    """
    if not usage_reports:
        return
    try:
        from app.models.ai.usage import UsageEvent
        for r in usage_reports:
            db.add(UsageEvent(
                session_id=None,
                user_id=uuid4(),  # namecard pipeline is system-level; no user session
                tenant_id=tenant_id,
                provider=r.get("provider") or "deepseek",
                model=r.get("model") or "",
                input_tokens=int(r.get("input_tokens") or 0),
                output_tokens=int(r.get("output_tokens") or 0),
                cost_estimate=float(r.get("cost_usd") or 0) if r.get("cost_usd") else None,
                result_status="success",
                module="namecard",
                currency="USD",
            ))
    except Exception:
        pass  # usage recording is best-effort


async def persist_step(db: AsyncSession, *, tenant_id: Any, signal_id: Any,
                       step: AgentStep) -> None:
    """Write one agent step to ai_agent_log. Callable between pipeline stages
    so a router can interleave DB work (e.g. company match) with agents."""
    log_dict = step.as_log_dict()
    log_dict["input_snapshot"] = _jsonable(step.input_snapshot)
    log_dict["output_snapshot"] = _jsonable(step.output)
    db.add(AiAgentLog(
        tenant_id=tenant_id,
        signal_type="namecard",
        signal_id=signal_id,
        **log_dict,
    ))
    await db.flush()


async def run_namecard_pipeline(
    db: AsyncSession,
    *,
    tenant_id: Any,
    signal_id: Any,
    raw_text: str,
    parsed_heuristic: dict[str, Any],
    image_url: str,
    existing_contacts: list[dict[str, Any]],
    company_id: Any,
    company_name: str,
    recent_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the 5-agent pipeline in order, persist each step to ai_agent_log.

    Returns a combined analysis dict the router uses to write DB rows.
    """
    steps: list[AgentStep] = []
    usage_reports: list = []  # core rule G08: central token collection

    # 1 → 2: ingest then extract
    s1 = ingestion_agent(raw_text, parsed_heuristic, image_url)
    steps.append(s1)
    signal = s1.output["signal"]
    s2 = extraction_agent(signal, usage_out=usage_reports)
    steps.append(s2)
    parsed = s2.output["parsed"]

    # 3: entity resolution
    s3 = entity_resolution_agent(parsed, existing_contacts, company_id, usage_out=usage_reports)
    steps.append(s3)

    # 4: enrichment (only when we have a company to research)
    s4 = None
    if company_name.strip():
        s4 = enrichment_agent(company_name, usage_out=usage_reports)
        steps.append(s4)

    # 5: inference
    s5 = inference_agent(parsed, recent_events, usage_out=usage_reports)
    steps.append(s5)

    # ── Record usage events (namecard_* modules) — central token collection ──
    await _record_namecard_usage(db, tenant_id, usage_reports)

    # Persist audit trail — one row per step
    for st in steps:
        db.add(AiAgentLog(
            tenant_id=tenant_id,
            signal_type="namecard",
            signal_id=signal_id,
            **st.as_log_dict(),
        ))
    await db.flush()

    return {
        "parsed": parsed,
        "resolution": {
            "tier": s3.output.get("tier", "low"),
            "decision": s3.decision,
            "candidate": s3.output.get("candidate"),
            "confidence": s3.confidence,
            "reason": s3.output.get("reason", ""),
            "match_key": s3.output.get("match_key", ""),
        },
        "enrichment": s4.output if s4 else {},
        "inference": s5.output,
        "steps": [st.as_log_dict() for st in steps],
    }

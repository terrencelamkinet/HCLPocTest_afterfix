"""NameCard LLM enrichment layer — OCR post-processing with two providers.

  - DeepSeek (chat): structured field cleaning, duplicate analysis, context
    suggestion (meeting matching). Text-only.
  - Perplexity (sonar): company research with web search grounding.

Every function is fail-safe: any API error returns a fallback value and the
caller keeps the heuristic pipeline result — enrichment never breaks upload.

Keys come from backend/.env (DEEPSEEK_API_KEY, PERPLEXITY_API_KEY).
"""
from __future__ import annotations

import json
import os
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.ai.providers.base import compute_cost

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if v:
        return v
    try:  # fallback: read backend/.env directly (uvicorn may not export it)
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


_FIELDS = ("name", "chinese_name", "title", "company", "email", "phone",
           "website", "address", "linkedin")

# ── Company name normalisation (架構文檔 §階段三) ─────────────
# Strip legal suffixes so "Cohesity Ltd" fuzzy-matches "Cohesity".
_COMPANY_SUFFIXES = (
    "limited", "ltd", "inc", "incorporated", "corp", "corporation",
    "co", "company", "llc", "plc", "gmbh", "pte", "pvt", "bhd",
    "holding", "holdings", "group", "sdn", "ag", "sa", "bv", "nv",
)


def normalize_company_name(name: str) -> str:
    """Normalise a company name for matching: lowercase, strip suffixes.

    >>> normalize_company_name("Cohesity Ltd.")
    'cohesity'
    """
    import re
    s = re.sub(r"[.,]", " ", name.lower())
    tokens = [t for t in s.split() if t and t not in _COMPANY_SUFFIXES]
    return " ".join(tokens).strip()


def name_similarity(a: str, b: str) -> float:
    """Token-overlap similarity 0-1 — cheap semantic layer for dedup.

    Handles "A. Butoi" vs "Alexandra Butoi" via initial-token matching and
    substring containment for typos. Used as the vector layer fallback when
    no embedding API is available (架構文檔 §Entity Resolution 語意向量層).
    """
    if not a or not b:
        return 0.0
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    ta = [t for t in a.replace(".", " ").split() if t]
    tb = [t for t in b.replace(".", " ").split() if t]
    if not ta or not tb:
        return 0.0
    # initial-token match: "a. butoi" vs "alexandra butoi"
    if len(ta) == 2 and len(tb) == 2 and ta[0][0] == tb[0][0] and ta[1] == tb[1]:
        return 0.85
    inter = len(set(ta) & set(tb))
    union = len(set(ta) | set(tb))
    jac = inter / union if union else 0.0
    # partial-word overlap catches typos (e.g. "Butoi" vs "Butoiu")
    if jac == 0.0:
        for x in ta:
            for y in tb:
                if len(x) >= 4 and len(y) >= 4 and (x in y or y in x):
                    return 0.7
    return jac


def _post_json(url: str, key: str, payload: dict, timeout: int = 45,
               usage_out: list | None = None) -> dict | None:
    if not key:
        return None
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        # Core rule G08: collect usage for central token/cost tracking.
        if usage_out is not None:
            u = data.get("usage") or {}
            inp = int(u.get("prompt_tokens") or 0)
            out = int(u.get("completion_tokens") or 0)
            model = payload.get("model") or ""
            cost = compute_cost(model, inp, out)  # USD per-1K cost cards
            usage_out.append({
                "provider": "perplexity" if "perplexity" in url else
                            ("deepseek" if "deepseek" in url else "siliconflow"),
                "model": model,
                "input_tokens": inp,
                "output_tokens": out,
                "cost_usd": cost,
            })
        return {"content": content, "raw": data}
    except Exception:  # noqa: BLE001 — enrichment must never raise
        return None


def llm_structured(raw_text: str, usage_out: list | None = None) -> dict[str, Any]:
    """DeepSeek: raw OCR text → clean structured fields (fixes OCR noise)."""
    key = _env("DEEPSEEK_API_KEY")
    if not key or not raw_text.strip():
        return {}
    prompt = (
        "You are a business-card data cleaning assistant. Raw OCR text from a "
        "business card:\n---\n" + raw_text[:2000] + "\n---\n"
        "Return ONLY JSON with these keys (empty string if absent): "
        '{"name":"","chinese_name":"","title":"","company":"","email":"",'
        '"phone":"","website":"","address":"","linkedin":""}. '
        "Clean OCR noise (e.g. stray symbols, duplicated words, wrong "
        "capitalization). Keep Chinese company/person names in Chinese. "
        "Do not invent data that is not in the text."
    )
    resp = _post_json(DEEPSEEK_URL, key, {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }, usage_out=usage_out)
    if not resp:
        return {}
    data = _extract_json(resp["content"]) or {}
    return {k: str(data.get(k, "")).strip() for k in _FIELDS}


def llm_company_research(company_name: str, usage_out: list | None = None) -> dict[str, Any]:
    """Perplexity sonar: web-search the company → enrichment fields.

    Returns website/industry/address/size/description + source_url (best
    evidence page) and confidence (0-1). Empty dict on any failure.
    """
    key = _env("PERPLEXITY_API_KEY")
    if not key or not company_name.strip():
        return {}
    prompt = (
        f"Search the web for the company \"{company_name}\". Return ONLY JSON: "
        '{"website":"","industry":"","address":"","size":"","description":"",'
        '"source_url":"","confidence":0.0}. '
        "website = official domain only (e.g. https://cohesity.com). "
        "size = employee count range if known. "
        "source_url = the single most authoritative page you used "
        "(official site > business registry > LinkedIn > news). "
        "confidence = 0-1 how sure you are the data is about THIS company. "
        "Empty string when not found. Do not guess."
    )
    resp = _post_json(PERPLEXITY_URL, key, {
        "model": PERPLEXITY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 400,
    }, usage_out=usage_out)
    if not resp:
        return {}
    data = _extract_json(resp["content"]) or {}
    out = {k: str(data.get(k, "")).strip() for k in
           ("website", "industry", "address", "size", "description", "source_url")}
    try:
        out["confidence"] = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    return out


def llm_duplicate_analysis(parsed: dict[str, Any],
                           candidates: list[dict[str, Any]],
                           usage_out: list | None = None) -> dict[str, Any]:
    """DeepSeek: is the scanned card the same person as an existing contact?"""
    key = _env("DEEPSEEK_API_KEY")
    if not key or not candidates:
        return {"is_duplicate": False, "candidate_id": None, "confidence": 0.0,
                "reason": ""}
    card = {k: parsed.get(k, "") for k in
            ("name", "chinese_name", "title", "company", "email", "phone")}
    cands = [
        {k: c.get(k, "") for k in
         ("id", "name", "chinese_name", "title", "company", "email", "phone")}
        for c in candidates
    ]
    prompt = (
        "A newly scanned business card may belong to an existing contact. "
        "Card: " + json.dumps(card, ensure_ascii=False) + "\n"
        "Existing contacts: " + json.dumps(cands, ensure_ascii=False) + "\n"
        'Return ONLY JSON: {"is_duplicate":true/false,"candidate_id":"<id or '
        'empty>","confidence":0.0-1.0,"reason":"short reason in Chinese"}. '
        "Same person = same name/email/phone (allow HK/TW/CN name variants, "
        "typos, +852 vs 852, middle initials). Different company alone is not "
        "enough to say different person if name+title match."
    )
    resp = _post_json(DEEPSEEK_URL, key, {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }, usage_out=usage_out)
    if not resp:
        return {"is_duplicate": False, "candidate_id": None, "confidence": 0.0,
                "reason": ""}
    data = _extract_json(resp["content"]) or {}
    return {
        "is_duplicate": bool(data.get("is_duplicate")),
        "candidate_id": str(data.get("candidate_id") or ""),
        "confidence": float(data.get("confidence") or 0.0),
        "reason": str(data.get("reason") or ""),
    }


def llm_context_suggestion(parsed: dict[str, Any],
                           recent_events: list[dict[str, Any]],
                           usage_out: list | None = None) -> dict[str, Any]:
    """DeepSeek Inference Agent: could this person have been met recently?

    Triple-verification (架構文檔 §階段四): time + location + company-name
    overlap. Returns {"suggestion": str, "confidence": float, "matched_event": str}
    — caller decides auto-link (all three) vs weak hint (one match).
    """
    key = _env("DEEPSEEK_API_KEY")
    if not key or not recent_events:
        return {"suggestion": "", "confidence": 0.0, "matched_event": ""}
    card = {k: parsed.get(k, "") for k in ("name", "company", "title")}
    events = [
        {"title": e.get("summary") or e.get("title") or "",
         "date": str(e.get("occurred_at") or e.get("date") or "")[:10],
         "location": e.get("location") or ""}
        for e in recent_events[:10]
    ]
    prompt = (
        "A salesperson scanned a business card today. Card: " +
        json.dumps(card, ensure_ascii=False) + "\n"
        "Recent meetings/events (title/date/location): " +
        json.dumps(events, ensure_ascii=False) + "\n"
        "Could this person plausibly have been met at one of these events? "
        "Apply triple verification:\n"
        "  time: event date within 30 days of today AND no other event closer\n"
        "  location: event location mentions the card company name or its venue\n"
        "  company: card company name appears in the event title or description\n"
        'Return ONLY JSON: {"suggestion":"one short Chinese sentence or '
        'empty","confidence":0-1,"matched_event":"exact event title or empty",'
        '"verification":{"time":true/false,"location":true/false,'
        '"company":true/false}}. '
        "Only output a suggestion when at least one check is true. "
        "Example: card company 'Cohesity' + event 'Cohesity Q3 Review' "
        '→ verification.company=true, suggestion="可能喺 Cohesity Q3 Review 會議認識"'
    )
    resp = _post_json(DEEPSEEK_URL, key, {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }, usage_out=usage_out)
    if not resp:
        return {"suggestion": "", "confidence": 0.0, "matched_event": ""}
    data = _extract_json(resp["content"]) or {}
    try:
        conf = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "suggestion": str(data.get("suggestion") or ""),
        "confidence": conf,
        "matched_event": str(data.get("matched_event") or ""),
        "verification": data.get("verification") or {},
    }

"""Internal tenant entity search (companies/contacts) by keyword score — 共用 service.

`search_tenant_entities` 俾 smart-fill 同 suggest-related 共用。
Scoring 直接沿用 suggest_related 原有邏輯：token_hits / len(tokens) + substring bonus。
任何 exception 都唔 throw — return []（caller fallback）。
"""
from __future__ import annotations

import re as _re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Company, Contact

# resource -> (model, name column)
_RESOURCE_MODEL = {
    "companies": Company,
    "contacts": Contact,
}

# word-boundary token regex cache（避免每次 re.compile）
_token_re_cache: dict[str, _re.Pattern] = {}


def _word_match(tok: str, name_l: str) -> bool:
    """Word-boundary match：token 必須係完整 word，唔係 substring。

    避免「up」match「Supplies」「Group」呢類假陽性。
    """
    rx = _token_re_cache.get(tok)
    if rx is None:
        rx = _re.compile(rf"(?<![a-z0-9]){_re.escape(tok)}(?![a-z0-9])")
        _token_re_cache[tok] = rx
    return bool(rx.search(name_l))


def _score_entities(title_tokens: list[str], title_lower: str, rows: list[tuple]) -> list[dict]:
    """Scoring：token_hits / len(tokens) + substring bonus（同 suggest_related 原本邏輯等價）。"""
    scored = []
    for rid, rname in rows:
        rname_l = (rname or "").lower()
        if not rname_l:
            continue
        # word-boundary match：token 要係完整 word（「up」唔再 match「supplies」）
        token_hits = sum(1 for tok in title_tokens if _word_match(tok, rname_l))
        score = token_hits / len(title_tokens) if title_tokens else 0.0
        # substring bonus: continuous title substring present in name
        if title_lower in rname_l:
            score += 0.3
        if score > 0:
            scored.append({"id": str(rid), "name": rname, "score": score})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


async def search_tenant_entities(
    db: AsyncSession, tenant_id, resource: str, text: str, limit: int = 8
) -> list[dict]:
    """Search tenant-scoped companies/contacts by keyword score.

    resource: 'companies' | 'contacts'（其他可以加去 _RESOURCE_MODEL）。
    Return: [{"id": uuid_str, "name": str, "score": float}] 按 score desc。
    任何 exception 都唔好 throw — return []（caller fallback）。
    """
    if not text or not text.strip():
        return []
    model = _RESOURCE_MODEL.get(resource)
    if model is None:
        return []

    tokens = [t for t in _re.split(r"[\s\W_]+", text.lower()) if t]
    if not tokens:
        return []

    try:
        rows = (
            await db.execute(
                select(model.id, model.name).where(model.tenant_id == tenant_id)
            )
        ).all()
        scored = _score_entities(tokens, text.lower(), rows)
        return scored[:limit]
    except Exception:
        return []

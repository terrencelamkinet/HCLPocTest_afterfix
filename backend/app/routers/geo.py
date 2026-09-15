"""Geo endpoints — address autocomplete + reverse geocoding.

Server-side proxy（multi-tenant key protection — 唔好放 API key 喺前端）：

- Provider `photon`（default）：Photon / OpenStreetMap — 免費、唔使 key、
  支援 HK 中英文地址（community server，適合低至中用量）。
- Provider `geoapify`：Geoapify Geocoding API — 1 credit/req，free 3000/day，
  HK 地址質素更好。設定 `GEOAPIFY_API_KEY` 之後自動用。
- Provider 揀法：config `geo_provider` = "auto"（有 key 用 geoapify，冇用 photon）
  / "photon" / "geoapify"。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai/geo", tags=["geo"])

PHOTON_API = "https://photon.komoot.io"
GEOAPIFY_API = "https://api.geoapify.com/v1/geocode"

# Photon 公共 server 要求 User-Agent（冇 UA → 403 Forbidden，2026-08-23 實測）
_PHOTON_HEADERS = {"User-Agent": "NexusCRM/1.0 (contact: terrence@kinetix.com.hk)"}

# Photon 唔 support lang=zh（只 de/en/fr）— 中文時唔帶 lang（OSM 出本地名，HK 中英雙語）
PHOTON_LANG = {"zh-Hant": None, "zh": None, "en": "en"}

_ZERO = "00000000-0000-0000-0000-000000000000"


def _require_auth(request: Request) -> None:
    """G08 auth pattern — JWT middleware 將 user/tenant 放 request.state.ai_context."""
    ctx = getattr(request.state, "ai_context", None)
    user_id = getattr(ctx, "user_id", None) if ctx else None
    if not user_id or str(user_id) == _ZERO:
        raise HTTPException(401, "Not authenticated")


def _active_provider() -> str:
    p = (settings.geo_provider or "auto").lower()
    if p == "auto":
        return "geoapify" if settings.geoapify_api_key else "photon"
    return p


# ── Photon (OSM) ─────────────────────────────────────────────
async def _photon_autocomplete(q: str, lang: str, limit: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"q": q, "limit": limit}
    lang_v = PHOTON_LANG.get(lang)
    if lang_v:
        params["lang"] = lang_v
    async with httpx.AsyncClient(timeout=8, headers=_PHOTON_HEADERS) as client:
        r = await client.get(f"{PHOTON_API}/api/", params=params)
        r.raise_for_status()
        data = r.json()
    out: list[dict[str, Any]] = []
    for f in (data.get("features") or []):
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [0, 0]
        name = p.get("name") or ""
        street = p.get("street") or ""
        city = p.get("city") or p.get("district") or ""
        state = p.get("state") or ""
        country = p.get("country") or ""
        housenumber = p.get("housenumber") or ""
        parts = [x for x in [housenumber and f"{housenumber} {name}" if housenumber else name or street, city, state, country] if x]
        label = ", ".join(dict.fromkeys(parts)) or q
        out.append({
            "label": label,
            "lat": coords[1],
            "lng": coords[0],
            "source": "photon",
            "place_id": str(p.get("osm_id", "")),
            "components": {
                "street": street or name, "housenumber": housenumber,
                "city": city, "state": state, "country": country,
            },
        })
    return out


async def _photon_reverse(lat: float, lng: float) -> dict[str, Any] | None:
    params: dict[str, Any] = {"lat": lat, "lon": lng}
    async with httpx.AsyncClient(timeout=8, headers=_PHOTON_HEADERS) as client:
        r = await client.get(f"{PHOTON_API}/reverse", params=params)
        r.raise_for_status()
        data = r.json()
    feats = data.get("features") or []
    if not feats:
        return None
    p = feats[0].get("properties") or {}
    name = p.get("name") or ""
    street = p.get("street") or ""
    city = p.get("city") or p.get("district") or ""
    state = p.get("state") or ""
    country = p.get("country") or ""
    housenumber = p.get("housenumber") or ""
    parts = [x for x in [housenumber and f"{housenumber} {name}" if housenumber else name or street, city, state, country] if x]
    return {"label": ", ".join(dict.fromkeys(parts)) or f"{lat:.5f},{lng:.5f}", "lat": lat, "lng": lng, "source": "photon"}


# ── Geoapify ─────────────────────────────────────────────────
async def _geoapify_autocomplete(q: str, lang: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "text": q, "apiKey": settings.geoapify_api_key, "limit": limit,
        "lang": "zh" if lang.startswith("zh") else "en",
        "bias": "countrycode:hk",  # HK 優先
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{GEOAPIFY_API}/autocomplete", params=params)
        r.raise_for_status()
        data = r.json()
    out: list[dict[str, Any]] = []
    for f in (data.get("features") or []):
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [0, 0]
        out.append({
            "label": p.get("formatted") or p.get("address_line1") or q,
            "lat": coords[1],
            "lng": coords[0],
            "source": "geoapify",
            "place_id": str(p.get("place_id", "")),
            "components": {
                "street": p.get("street") or "", "housenumber": p.get("housenumber") or "",
                "city": p.get("city") or "", "state": p.get("state") or "",
                "country": p.get("country") or "",
            },
        })
    return out


async def _geoapify_reverse(lat: float, lng: float) -> dict[str, Any] | None:
    params = {"lat": lat, "lon": lng, "apiKey": settings.geoapify_api_key, "lang": "zh"}
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{GEOAPIFY_API}/reverse", params=params)
        r.raise_for_status()
        data = r.json()
    feats = data.get("features") or []
    if not feats:
        return None
    p = feats[0].get("properties") or {}
    return {
        "label": p.get("formatted") or p.get("address_line1") or f"{lat:.5f},{lng:.5f}",
        "lat": lat, "lng": lng, "source": "geoapify",
    }


# ── Endpoints ─────────────────────────────────────────────────
@router.get("/autocomplete")
async def autocomplete(
    request: Request,
    q: str = Query(..., min_length=2, max_length=120, description="地址搜尋文字（最少 2 個字）"),
    lang: str = Query("zh-Hant", pattern="^(zh-Hant|zh|en)$"),
    limit: int = Query(5, ge=1, le=10),
) -> dict[str, Any]:
    _require_auth(request)
    provider = _active_provider()
    try:
        if provider == "geoapify":
            items = await _geoapify_autocomplete(q, lang, limit)
        else:
            items = await _photon_autocomplete(q, lang, limit)
    except httpx.HTTPStatusError as e:
        logger.warning("geo autocomplete provider=%s failed: %s", provider, e)
        raise HTTPException(status_code=502, detail=f"geocoder upstream error ({e.response.status_code})")
    except httpx.HTTPError as e:
        logger.warning("geo autocomplete provider=%s network error: %s", provider, e)
        raise HTTPException(status_code=502, detail="geocoder unreachable")
    return {"provider": provider, "suggestions": items}


@router.get("/reverse")
async def reverse(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> dict[str, Any]:
    _require_auth(request)
    provider = _active_provider()
    try:
        if provider == "geoapify":
            item = await _geoapify_reverse(lat, lng)
        else:
            item = await _photon_reverse(lat, lng)
    except httpx.HTTPError as e:
        logger.warning("geo reverse provider=%s failed: %s", provider, e)
        raise HTTPException(status_code=502, detail="geocoder unreachable")
    if item is None:
        raise HTTPException(status_code=404, detail="no address found")
    return {"provider": provider, **item}

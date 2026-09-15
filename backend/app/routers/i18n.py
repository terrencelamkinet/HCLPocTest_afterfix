"""i18n Translation Management API — DB-backed UI strings (en / zh-TW / zh-CN).

2026-09-10（Terrence spec）:
- 主站 runtime fetch resources（改完即時生效，唔使 rebuild）
- Admin-only write（require_superadmin）— module tree + inline edit + autosave
- Table: nexus_auth.i18n_entries（global — 冇 RLS — 任何 tenant session 讀到）
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db_admin import require_superadmin, get_admin_session

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])

# locale param -> db column
_LOCALE_COL = {
    "en": "en", "en-US": "en", "en-GB": "en",
    "zh": "zh_tw", "zh-TW": "zh_tw", "zh-Hant": "zh_tw", "zh-HK": "zh_tw",
    "zh-CN": "zh_cn", "zh-Hans": "zh_cn", "zh-SG": "zh_cn", "zh-MO": "zh_tw",
}

def _unflatten(rows) -> dict:
    """rows of (key_path, value) -> nested dict; JSON-array values restored."""
    root: dict = {}
    for kp, val in rows:
        if val is None:
            continue
        try:
            v: object = json.loads(val) if val.startswith("[") else val
        except Exception:
            v = val
        node = root
        parts = kp.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return root


@router.get("/resources")
async def get_resources(locale: str = Query("zh-TW", description="en / zh-TW / zh-CN"),
                        db: AsyncSession = Depends(get_db)):
    """Full translation tree for one locale — main site loads this at boot / on language switch."""
    col = _LOCALE_COL.get(locale, _LOCALE_COL.get(locale.split("-")[0], "zh_tw"))
    rows = (await db.execute(text(f"SELECT key_path, {col} FROM nexus_auth.i18n_entries"))).mappings().all()
    return _unflatten([(r["key_path"], r[col]) for r in rows])


@router.get("/modules")
async def list_modules(db: AsyncSession = Depends(get_db)):
    """Module tree summary (admin i18n editor sidebar)."""
    rows = (await db.execute(text("""
        SELECT module, count(*) AS keys,
               count(*) FILTER (WHERE page_route <> '') AS with_route,
               max(updated_at) AS last_updated
        FROM nexus_auth.i18n_entries GROUP BY module ORDER BY module
    """))).mappings().all()
    return [{"module": r["module"], "keys": r["keys"], "with_route": r["with_route"],
             "last_updated": str(r["last_updated"]) if r["last_updated"] else None} for r in rows]


@router.get("/entries")
async def list_entries(module: str = Query("", description="filter by top module (empty = all)"),
                       search: str = Query("", max_length=200),
                       page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                       db: AsyncSession = Depends(get_db)):
    where, params = [], {}
    if module:
        where.append("module = :m"); params["m"] = module
    if search:
        where.append("(key_path ILIKE :q OR en ILIKE :q OR zh_tw ILIKE :q OR zh_cn ILIKE :q)")
        params["q"] = f"%{search}%"
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    params["limit"], params["offset"] = page_size, (page - 1) * page_size
    rows = (await db.execute(text(f"""
        SELECT key_path, module, en, zh_tw, zh_cn, description, page_route, location,
               updated_at, updated_by
        FROM nexus_auth.i18n_entries {wsql}
        ORDER BY key_path LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    cnt_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    cnt = (await db.execute(text(f"SELECT count(*) FROM nexus_auth.i18n_entries {wsql}"), cnt_params)).scalar_one()
    return {"total": cnt or 0, "items": [dict(r) | {"updated_at": str(r["updated_at"])} for r in rows]}


@router.patch("/entries/{key_path:path}")
async def update_entry(key_path: str, body: dict, _admin: str = Depends(require_superadmin),
                       db: AsyncSession = Depends(get_admin_session)):
    """Admin-only: patch en/zh_tw/zh_cn/description/page_route for one key. Autosave target."""
    allowed = {"en", "zh_tw", "zh_cn", "description", "page_route"}
    sets, params = [], {"kp": key_path}
    for field, val in body.items():
        if field in allowed and isinstance(val, str) and len(val) <= 2000:
            sets.append(f"{field} = :{field}"); params[field] = val
    if not sets:
        raise HTTPException(422, "no valid fields")
    params["by"] = _admin
    res = await db.execute(text(f"""
        UPDATE nexus_auth.i18n_entries
        SET {', '.join(sets)}, updated_at = now(), updated_by = :by
        WHERE key_path = :kp
    """), params)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "key not found")
    return {"ok": True, "key_path": key_path}

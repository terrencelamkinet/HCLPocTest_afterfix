"""Renewal Radar API —— 合約／訂閱到期追蹤。

Prefix: `/api/v1/crm/renewals`

`days_left` / `due` / `overdue` 由 server 計好俾 UI（唔想前端自己再計一次，兩邊會唔一致）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.services.renewal_radar import is_due

router = APIRouter(prefix="/api/v1/crm/renewals", tags=["crm-renewals"])

_COLS = ("id, name, company_id, amount, currency, renewal_date, notice_days, owner_id, "
         "status, notes, last_notified_at, created_at")


def _tid(request: Request) -> UUID:
    if getattr(request.state, "auth_status", "") == "expired":
        raise HTTPException(status_code=401, detail="Token expired")
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="No tenant in session")
    return tid


def _uid(request: Request) -> UUID | None:
    return getattr(request.state, "user_id", None)


def _ser(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    for k in ("id", "company_id", "owner_id"):
        out[k] = str(out[k]) if out.get(k) else None
    if out.get("amount") is not None:
        out["amount"] = float(out["amount"])
    for k in ("renewal_date",):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    for k in ("last_notified_at", "created_at"):
        if isinstance(out.get(k), datetime):
            out[k] = out[k].isoformat()
    return out


class RenewalIn(BaseModel):
    name: str
    renewal_date: date
    notice_days: int = 30
    company_id: UUID | None = None
    amount: float | None = None
    currency: str = "HKD"
    owner_id: UUID | None = None
    notes: str | None = None


class RenewalPatch(BaseModel):
    name: str | None = None
    renewal_date: date | None = None
    notice_days: int | None = None
    status: str | None = None  # active / renewed / cancelled
    notes: str | None = None


@router.get("")
async def list_renewals(
    request: Request,
    due_only: bool = False,
    include_closed: bool = False,
    db: AsyncSession = Depends(get_tenant_session),
):
    """到期追蹤清單。`due_only=true` → 只返入咗通知窗口（含 overdue）嘅。"""
    tid = _tid(request)
    where = "tenant_id = :t"
    if not include_closed:
        where += " AND status = 'active'"
    rows = (
        await db.execute(text(f"SELECT {_COLS} FROM nexus_crm.renewals WHERE {where} ORDER BY renewal_date"), {"t": tid})
    ).mappings().all()

    today = datetime.now(timezone.utc).date()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = (r["renewal_date"] - today).days
        due = r["status"] == "active" and is_due(r["renewal_date"], r["notice_days"], today)
        if due_only and not due:
            continue
        out.append({**_ser(dict(r)), "days_left": d, "due": due, "overdue": d < 0})

    return {"renewals": out, "due_count": sum(1 for x in out if x["due"])}


@router.post("", status_code=201)
async def create_renewal(
    body: RenewalIn,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tid = _tid(request)
    ws = getattr(request.state, "workspace_id", None)
    if not ws:
        ws = (
            await db.execute(
                text("SELECT id FROM nexus_auth.workspaces WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
                {"t": tid},
            )
        ).scalar()
    if not ws:
        raise HTTPException(status_code=400, detail="No workspace")

    row = (
        await db.execute(
            text("""
                INSERT INTO nexus_crm.renewals
                    (tenant_id, workspace_id, name, renewal_date, notice_days, company_id,
                     amount, currency, owner_id, notes, created_by)
                VALUES (:t, :ws, :name, :rd, :nd, :cid, :amt, :cur, :owner, :notes, :uid)
                RETURNING id
            """),
            {"t": tid, "ws": ws, "name": body.name, "rd": body.renewal_date,
             "nd": body.notice_days, "cid": body.company_id, "amt": body.amount,
             "cur": body.currency, "owner": body.owner_id or _uid(request),
             "notes": body.notes, "uid": _uid(request)},
        )
    ).scalar()
    await db.commit()
    return {"id": str(row)}


@router.patch("/{renewal_id}")
async def update_renewal(
    renewal_id: UUID,
    body: RenewalPatch,
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    """標記續約完成（status='renewed'）／取消／改期。"""
    tid = _tid(request)
    if body.status and body.status not in ("active", "renewed", "cancelled"):
        raise HTTPException(status_code=400, detail="status 只可以係 active / renewed / cancelled")

    sets, params = [], {"t": tid, "id": renewal_id}
    for k in ("name", "renewal_date", "notice_days", "status", "notes"):
        v = getattr(body, k, None)
        if v is not None:
            sets.append(f"{k} = :{k}")
            params[k] = v
    if not sets:
        raise HTTPException(status_code=400, detail="冇嘢要改")

    sets.append("updated_at = now()")
    res = await db.execute(
        text(f"UPDATE nexus_crm.renewals SET {', '.join(sets)} WHERE tenant_id = :t AND id = :id RETURNING id"),
        params,
    )
    if res.scalar() is None:
        raise HTTPException(status_code=404, detail="搵唔到 renewal")
    await db.commit()
    return {"ok": True, "id": str(renewal_id)}

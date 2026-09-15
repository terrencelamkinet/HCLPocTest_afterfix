"""Admin console API — cross-tenant, superadmin only (2026-09-09).

Spec: docs/admin-complete-spec.md §3  |  Impl guide: docs/admin-coding-details.md
DB: nexus_admin BYPASSRLS role (db_admin.py) — queries hit nexus_ai.usage_events (real table).
"""
import json as _json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_admin import get_admin_session

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _d(v):
    return v.isoformat() if v else None


# ─────────────────────────── 1. Overview ───────────────────────────

@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_admin_session)):
    base = (
        await db.execute(
            text(
                "SELECT (SELECT count(*) FROM nexus_auth.nexus_auth_tenants WHERE is_active) AS tenants,"
                "       (SELECT count(*) FROM nexus_auth.nexus_auth_users) AS users"
            )
        )
    ).mappings().first()
    u = (
        await db.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE created_at > now() - interval '24 hours')          AS today_calls,
                       count(*) FILTER (WHERE created_at > now() - interval '7 days')            AS week_calls,
                       count(*) FILTER (WHERE created_at > now() - interval '30 days')           AS month_calls,
                       count(DISTINCT tenant_id) FILTER (WHERE created_at > now() - interval '30 days') AS active_tenants,
                       COALESCE(sum(cost_estimate) FILTER (WHERE created_at > now() - interval '30 days'), 0) AS month_cost,
                       COALESCE(sum(cost_estimate) FILTER (WHERE created_at > now() - interval '24 hours'), 0)  AS today_cost,
                       count(*) FILTER (WHERE created_at > now() - interval '24 hours' AND result_status != 'success') AS today_errors
                FROM nexus_ai.usage_events
                """
            )
        )
    ).mappings().first()
    pl = (
        await db.execute(
            text(
                """
                SELECT COALESCE(ms.settings->>'plan', 'free') AS plan, count(*) AS n
                FROM nexus_auth.nexus_auth_tenants t
                LEFT JOIN nexus_crm.module_settings ms
                       ON ms.tenant_id = t.id AND ms.module_key = 'ai'
                WHERE t.is_active
                GROUP BY 1
                """
            )
        )
    ).mappings().all()
    plans = {"free": 0, "pro": 0, "enterprise": 0}
    for r in pl:
        if r["plan"] in plans:
            plans[r["plan"]] = int(r["n"])
    return {
        "tenants_total": base["tenants"] or 0,
        "users_total": base["users"] or 0,
        "tenants_active_30d": u["active_tenants"] or 0,
        "today": {"calls": u["today_calls"] or 0, "cost_usd": round(float(u["today_cost"] or 0), 4),
                  "errors": u["today_errors"] or 0},
        "week": {"calls": u["week_calls"] or 0},
        "month": {"calls": u["month_calls"] or 0, "cost_usd": round(float(u["month_cost"] or 0), 4)},
        "plans": plans,
    }


# ─────────────────────────── 2. Tenants ───────────────────────────

@router.get("/tenants")
async def list_tenants(
    search: str = "", sort: str = "month_cost_usd", order: str = "desc",
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_session),
):
    where, params = "", {"limit": page_size, "offset": (page - 1) * page_size}
    if search:
        where = "WHERE t.name ILIKE :q OR t.subdomain ILIKE :q OR u.email ILIKE :q"
        params["q"] = f"%{search}%"
    col = {"month_cost_usd": "month_cost_usd", "name": "t.name", "members": "members",
           "created_at": "t.created_at"}.get(sort, "month_cost_usd")
    order = order if order in ("asc", "desc") else "desc"
    rows = (
        await db.execute(
            text(
                f"""
                SELECT t.id, t.name, t.subdomain, t.is_active, t.created_at,
                       count(DISTINCT m.user_id) AS members,
                       max(u.email) AS owner_email,
                       max(u.display_name) AS owner_name,
                       COALESCE(max(ms.settings->>'plan'), 'free') AS plan,
                       count(e.id) AS month_calls, COALESCE(sum(e.cost_estimate), 0) AS month_cost_usd,
                       max(e.created_at) AS last_active
                FROM nexus_auth.nexus_auth_tenants t
                LEFT JOIN nexus_auth.nexus_auth_tenant_members m ON m.tenant_id = t.id
                LEFT JOIN nexus_auth.nexus_auth_users u ON u.id = m.user_id
                LEFT JOIN nexus_crm.module_settings ms ON ms.tenant_id = t.id AND ms.module_key = 'ai'
                LEFT JOIN nexus_ai.usage_events e ON e.tenant_id = t.id AND e.created_at > now() - interval '30 days'
                {where}
                GROUP BY t.id
                ORDER BY {col} {order.upper()}
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).mappings().all()
    total = (
        await db.execute(
            text(
                f"""SELECT count(DISTINCT t.id) AS c
                    FROM nexus_auth.nexus_auth_tenants t
                    LEFT JOIN nexus_auth.nexus_auth_tenant_members m ON m.tenant_id = t.id
                    LEFT JOIN nexus_auth.nexus_auth_users u ON u.id = m.user_id
                    {where}"""
            ),
            params,
        )
    ).mappings().first()
    return {
        "items": [
            {
                "id": str(r["id"]), "name": r["name"], "subdomain": r["subdomain"],
                "is_active": r["is_active"], "members": r["members"] or 0,
                "plan": r["plan"] or "free",
                "owner_email": r["owner_email"] or "", "owner_name": r["owner_name"] or "",
                "month_calls": r["month_calls"] or 0,
                "month_cost_usd": round(float(r["month_cost_usd"] or 0), 4),
                "last_active": _d(r["last_active"]),
            }
            for r in rows
        ],
        "total": total["c"] or 0,
        "page": page,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: dict, db: AsyncSession = Depends(get_admin_session)):
    """plan toggle / quota override. Body keys: plan | requests_limit | seats_limit | is_active"""
    if not body:
        raise HTTPException(400, "Empty body")
    if "is_active" in body:
        await db.execute(
            text("UPDATE nexus_auth.nexus_auth_tenants SET is_active=:v, updated_at=now() WHERE id=:tid"),
            {"v": bool(body["is_active"]), "tid": tenant_id},
        )
    plan_fields = {k: body[k] for k in ("plan", "requests_limit", "seats_limit") if k in body}
    if plan_fields:
        patch = _json.dumps(plan_fields, ensure_ascii=False)
        existing = (
            await db.execute(
                text("SELECT id FROM nexus_crm.module_settings WHERE tenant_id=:tid AND module_key='ai'"),
                {"tid": tenant_id},
            )
        ).first()
        if existing:
            await db.execute(
                text("UPDATE nexus_crm.module_settings SET settings = settings || :patch::jsonb, updated_at=now() WHERE id=:id"),
                {"id": existing[0], "patch": patch},
            )
        else:
            await db.execute(
                text("INSERT INTO nexus_crm.module_settings (tenant_id, module_key, enabled, settings) "
                     "VALUES (:tid, 'ai', true, :patch::jsonb)"),
                {"tid": tenant_id, "patch": patch},
            )
    return {"ok": True}


@router.get("/tenants/{tenant_id}")
async def tenant_detail(tenant_id: str, db: AsyncSession = Depends(get_admin_session)):
    t = (
        await db.execute(
            text(
                """
                SELECT t.id, t.name, t.subdomain, t.is_active, t.created_at, t.settings,
                       count(DISTINCT m.user_id) AS members
                FROM nexus_auth.nexus_auth_tenants t
                LEFT JOIN nexus_auth.nexus_auth_tenant_members m ON m.tenant_id = t.id
                WHERE t.id = :tid GROUP BY t.id
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().first()
    if not t:
        raise HTTPException(404, "Tenant not found")
    members = (
        await db.execute(
            text(
                """
                SELECT u.email, u.role, max(e.created_at) AS last_ai_use
                FROM nexus_auth.nexus_auth_users u
                JOIN nexus_auth.nexus_auth_tenant_members m ON m.user_id = u.id
                LEFT JOIN nexus_ai.usage_events e ON e.user_id = u.id
                WHERE m.tenant_id = :tid GROUP BY u.id
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    crm = (
        await db.execute(
            text(
                """
                SELECT 'contacts' AS k, count(*) AS v FROM nexus_crm.contacts WHERE tenant_id=:tid
                UNION ALL SELECT 'companies', count(*) FROM nexus_crm.companies WHERE tenant_id=:tid
                UNION ALL SELECT 'deals', count(*) FROM nexus_crm.deals WHERE tenant_id=:tid
                UNION ALL SELECT 'tasks', count(*) FROM nexus_crm.tasks WHERE tenant_id=:tid
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    usage = (
        await db.execute(
            text(
                """
                SELECT model, count(*) AS calls, COALESCE(sum(cost_estimate), 0) AS cost_usd
                FROM nexus_ai.usage_events
                WHERE tenant_id = :tid AND created_at > now() - interval '30 days'
                GROUP BY model ORDER BY calls DESC
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    q = (
        await db.execute(
            text(
                """
                SELECT period_key, requests_used, requests_limit FROM nexus_ai.ai_usage_quotas
                WHERE tenant_id = :tid AND period_key = to_char(now(), 'IYYY-"W"IW')
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().first()
    prov = (
        await db.execute(
            text(
                "SELECT provider, is_byok, status FROM nexus_ai.provider_credentials "
                "WHERE tenant_id=:tid AND status='active'"
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    ms = (
        await db.execute(
            text("SELECT settings FROM nexus_crm.module_settings WHERE tenant_id=:tid AND module_key='ai'"),
            {"tid": tenant_id},
        )
    ).mappings().first()
    plan = ((ms["settings"] or {}).get("plan") if ms and ms["settings"] else None) or "free"
    return {
        "tenant": {"id": str(t["id"]), "name": t["name"], "subdomain": t["subdomain"],
                   "is_active": t["is_active"], "members": t["members"] or 0,
                   "plan": plan, "created_at": _d(t["created_at"])},
        "members": [{"email": m["email"], "role": m["role"], "last_ai_use": _d(m["last_ai_use"])} for m in members],
        "crm": {x["k"]: x["v"] for x in crm},
        "usage_30d": {"calls": sum(u["calls"] for u in usage),
                      "cost_usd": round(sum(u["cost_usd"] for u in usage), 4),
                      "by_model": [{"model": u["model"], "calls": u["calls"]} for u in usage]},
        "quota": ({"period_key": q["period_key"], "used": q["requests_used"], "limit": q["requests_limit"]} if q else None),
        "providers": [{"provider": p["provider"], "is_byok": p["is_byok"], "status": p["status"]} for p in prov],
    }


# ─────────────────────────── 3. Users ───────────────────────────

@router.get("/users")
async def list_users(
    search: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_admin_session),
):
    where, params = "", {"limit": page_size, "offset": (page - 1) * page_size}
    if search:
        where = "WHERE u.email ILIKE :q"
        params["q"] = f"%{search}%"
    rows = (
        await db.execute(
            text(
                f"""
                SELECT u.email, u.role, u.email_verified, u.created_at, t.name AS tenant, t.id AS tenant_id,
                       (SELECT max(e.created_at) FROM nexus_ai.usage_events e WHERE e.user_id = u.id) AS last_ai_use
                FROM nexus_auth.nexus_auth_users u
                LEFT JOIN nexus_auth.nexus_auth_tenant_members m ON m.user_id = u.id
                LEFT JOIN nexus_auth.nexus_auth_tenants t ON t.id = m.tenant_id
                {where}
                ORDER BY u.created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).mappings().all()
    cnt_params = {"q": params["q"]} if search else {}
    cnt = (await db.execute(text(f"SELECT count(*) AS c FROM nexus_auth.nexus_auth_users u {where}"), cnt_params)).scalar_one()
    return {
        "total": cnt or 0,
        "items": [
            {"email": r["email"], "role": r["role"], "email_verified": r["email_verified"],
             "created_at": _d(r["created_at"]), "tenant": r["tenant"],
             "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
             "last_ai_use": _d(r["last_ai_use"])}
            for r in rows
        ]
    }


# ─────────────────────────── 4. Usage / Reporting ───────────────────────────

@router.get("/usage/trend")
async def usage_trend(days: int = Query(30, ge=1, le=365), granularity: str = "day",
                      db: AsyncSession = Depends(get_admin_session)):
    gran = {"day": "day", "week": "week", "month": "month"}.get(granularity, "day")
    rows = (
        await db.execute(
            text(
                f"""
                SELECT date_trunc(:gran, created_at)::date AS day, count(*) AS calls,
                       sum(input_tokens) AS in_tok, sum(output_tokens) AS out_tok,
                       COALESCE(sum(cost_estimate), 0) AS cost_usd,
                       count(*) FILTER (WHERE result_status != 'success') AS errors
                FROM nexus_ai.usage_events
                WHERE created_at > now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"gran": gran, "days": days},
        )
    ).mappings().all()
    return [{"day": str(r["day"]), "calls": r["calls"], "input_tokens": r["in_tok"] or 0,
             "output_tokens": r["out_tok"] or 0, "cost_usd": round(float(r["cost_usd"] or 0), 4),
             "errors": r["errors"] or 0} for r in rows]


@router.get("/usage/top-tenants")
async def top_tenants(days: int = Query(30, ge=1, le=365), metric: str = "cost",
                      db: AsyncSession = Depends(get_admin_session)):
    order = {"cost": "cost_usd DESC", "tokens": "in_tok DESC", "calls": "calls DESC"}.get(metric, "cost_usd DESC")
    rows = (
        await db.execute(
            text(
                f"""
                SELECT t.name AS tenant, count(e.id) AS calls, COALESCE(sum(e.cost_estimate), 0) AS cost_usd,
                       sum(e.input_tokens) AS in_tok, count(DISTINCT e.user_id) AS users,
                       max(e.created_at) AS last_active
                FROM nexus_ai.usage_events e
                JOIN nexus_auth.nexus_auth_tenants t ON t.id = e.tenant_id
                WHERE e.created_at > now() - make_interval(days => :days)
                GROUP BY t.id ORDER BY {order} LIMIT 20
                """
            ),
            {"days": days},
        )
    ).mappings().all()
    return [{"tenant": r["tenant"], "calls": r["calls"], "cost_usd": round(float(r["cost_usd"] or 0), 4),
             "input_tokens": r["in_tok"] or 0, "active_users": r["users"] or 0,
             "last_active": _d(r["last_active"])} for r in rows]


@router.get("/usage/top-users")
async def top_users(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_admin_session)):
    rows = (
        await db.execute(
            text(
                """
                SELECT u.email, t.name AS tenant, count(e.id) AS calls,
                       COALESCE(sum(e.cost_estimate), 0) AS cost_usd,
                       count(DISTINCT date_trunc('day', e.created_at)) AS active_days
                FROM nexus_ai.usage_events e
                JOIN nexus_auth.nexus_auth_users u ON u.id = e.user_id
                JOIN nexus_auth.nexus_auth_tenants t ON t.id = e.tenant_id
                WHERE e.created_at > now() - make_interval(days => :days)
                GROUP BY u.id, t.id ORDER BY cost_usd DESC LIMIT 20
                """
            ),
            {"days": days},
        )
    ).mappings().all()
    return [{"email": r["email"], "tenant": r["tenant"], "calls": r["calls"],
             "cost_usd": round(float(r["cost_usd"] or 0), 4), "active_days": r["active_days"] or 0} for r in rows]


@router.get("/quota/usage")
async def quota_usage(period: str | None = None, db: AsyncSession = Depends(get_admin_session)):
    p = period or "current"
    if p == "current":
        row = (await db.execute(text("SELECT to_char(now(), 'IYYY-\"W\"IW') AS p"))).mappings().first()
        p = row["p"]
    rows = (
        await db.execute(
            text(
                """
                SELECT t.name AS tenant, u.email, q.requests_used, q.requests_limit,
                       round(q.requests_used::numeric / NULLIF(q.requests_limit, 0) * 100) AS pct
                FROM nexus_ai.ai_usage_quotas q
                JOIN nexus_auth.nexus_auth_tenants t ON t.id = q.tenant_id
                JOIN nexus_auth.nexus_auth_users u ON u.id = q.user_id
                WHERE q.period_key = :p ORDER BY pct DESC NULLS LAST LIMIT 20
                """
            ),
            {"p": p},
        )
    ).mappings().all()
    return {"period": p, "items": [
        {"tenant": r["tenant"], "email": r["email"], "used": r["requests_used"],
         "limit": r["requests_limit"], "pct": r["pct"] or 0} for r in rows]}


# ─────────────────────────── 5. Connections / System ───────────────────────────

@router.get("/connections")
async def connections():
    out = {"overall": "ok", "checked_at": datetime.now(timezone.utc).isoformat(), "providers": []}
    # DeepSeek — Hermes token monitor state (host-local file; empty gracefully if absent)
    try:
        import os
        p = os.path.expanduser("~/.hermes/token_monitor_state.json")
        with open(p) as f:
            st = _json.load(f)
        out["providers"].append({"name": "deepseek", "kind": "llm-chat", "status": "ok",
                                 "balance_cny": st.get("balance"), "today_spend_cny": st.get("today_spend"),
                                 "daily_limit_cny": st.get("daily_limit", 10.0)})
    except Exception:
        out["providers"].append({"name": "deepseek", "kind": "llm-chat", "status": "unknown"})
    # Gemini Vertex — configured?
    from app.config import settings
    out["providers"].append({
        "name": "gemini-vertex", "kind": "llm-search",
        "status": "ok" if settings.vertex_project else "not-configured",
        "config": f"{settings.vertex_location} · gemini-2.5-flash · {settings.vertex_project}",
    })
    # External data probes (HKO / TD) — short timeout, non-fatal
    async def _probe(name: str, url: str):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(url)
            out["providers"].append({"name": name, "kind": "external-data",
                                     "status": "ok" if r.status_code == 200 else "down"})
            if r.status_code != 200:
                out["overall"] = "degraded"
        except Exception:
            out["providers"].append({"name": name, "kind": "external-data", "status": "down"})
            out["overall"] = "degraded"
    await _probe("hko-weather", "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=flw")
    await _probe("td-traffic", "https://www.td.gov.hk/special_news/specialnews.xml")
    return out


@router.get("/system")
async def system_stats():
    try:
        import psutil
    except ImportError:
        return {"error": "psutil not installed — cd backend && ./venv/bin/pip install psutil"}
    disk = psutil.disk_usage("/")
    ram = psutil.virtual_memory()
    procs = []
    for p in psutil.process_iter(["name", "pid", "cpu_percent", "memory_percent"]):
        try:
            if p.info["cpu_percent"] is not None:
                procs.append({"name": p.info["name"], "pid": p.info["pid"],
                              "cpu": p.info["cpu_percent"], "mem_pct": p.info["memory_percent"]})
        except Exception:
            pass
    procs.sort(key=lambda x: x["cpu"], reverse=True)
    return {
        "cpu": {"percent": psutil.cpu_percent(interval=0.3), "load_avg": list(psutil.getloadavg()),
                "cores": psutil.cpu_count()},
        "ram": {"used_gb": round(ram.used / 2**30, 1), "total_gb": round(ram.total / 2**30, 1),
                "percent": ram.percent},
        "disk": {"used_gb": round(disk.used / 2**30, 1), "total_gb": round(disk.total / 2**30, 1),
                 "percent": disk.percent},
        "uptime_s": int(psutil.boot_time()),
        "top_processes": procs[:5],
    }


# ─────────────────────────── 6. CSV Export ───────────────────────────

@router.get("/report/export")
async def export_csv(report: str = "top-tenants", days: int = Query(30, ge=1, le=365),
                     db: AsyncSession = Depends(get_admin_session)):
    import csv
    import io
    if report == "top-tenants":
        rows = (
            await db.execute(
                text(
                    """
                    SELECT t.name AS tenant, count(e.id) AS calls,
                           COALESCE(sum(e.cost_estimate), 0) AS cost_usd,
                           sum(e.input_tokens) AS input_tokens,
                           count(DISTINCT e.user_id) AS active_users, max(e.created_at) AS last_active
                    FROM nexus_ai.usage_events e
                    JOIN nexus_auth.nexus_auth_tenants t ON t.id = e.tenant_id
                    WHERE e.created_at > now() - make_interval(days => :days)
                    GROUP BY t.id ORDER BY cost_usd DESC LIMIT 500
                    """
                ),
                {"days": days},
            )
        ).mappings().all()
        cols = ["tenant", "calls", "cost_usd", "input_tokens", "active_users", "last_active"]
    elif report == "top-users":
        rows = (
            await db.execute(
                text(
                    """
                    SELECT u.email, t.name AS tenant, count(e.id) AS calls,
                           COALESCE(sum(e.cost_estimate), 0) AS cost_usd
                    FROM nexus_ai.usage_events e
                    JOIN nexus_auth.nexus_auth_users u ON u.id = e.user_id
                    JOIN nexus_auth.nexus_auth_tenants t ON t.id = e.tenant_id
                    WHERE e.created_at > now() - make_interval(days => :days)
                    GROUP BY u.id, t.id ORDER BY cost_usd DESC LIMIT 500
                    """
                ),
                {"days": days},
            )
        ).mappings().all()
        cols = ["email", "tenant", "calls", "cost_usd"]
    else:
        raise HTTPException(400, "report must be top-tenants | top-users")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r[c] for c in cols})
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=admin-{report}-{days}d.csv"},
    )


# ─────────────────────────── 7. Report Center (v1 — 8 real-data reports) ───────────────────────────
# 2026-09-10 Admin Console v1（SPEC admin-console-SPEC-v1）— 真數據源報表，冇 mock

@router.get("/reports/tenant-growth")
async def report_tenant_growth(days: int = Query(365, ge=30, le=730),
                               db: AsyncSession = Depends(get_admin_session)):
    """租戶成長趨勢 — 按月新增租戶（月結）"""
    rows = (
        await db.execute(
            text(
                """
                SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
                       count(*) AS new_tenants
                FROM nexus_auth.nexus_auth_tenants
                WHERE created_at > now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"days": days},
        )
    ).mappings().all()
    return [{"month": r["month"], "new_tenants": r["new_tenants"]} for r in rows]


@router.get("/reports/uptime")
async def report_uptime(hours: int = Query(24, ge=1, le=720),
                        db: AsyncSession = Depends(get_admin_session)):
    """Status page — 服務 uptime % + 平均 latency + incident（平台基建數據，非 tenant 數據）。

    Incident 由「連續失敗」推導（見 app/services/uptime_probe.py）—— 單次 blip 唔算。
    """
    from app.services.uptime_probe import uptime_report

    return await uptime_report(db, hours=hours)


@router.get("/reports/audit")
async def report_audit(hours: int = Query(168, ge=1, le=8760),
                       event_type: str | None = None,
                       db: AsyncSession = Depends(get_admin_session)):
    """審計報告 — AI 動作 / 檢索 / 系統事件（BYOK + DLP + 審計報告 之一）。

    資料源：`nexus_ai.ai_audit_log`（admin session = BYPASSRLS，跨 tenant 讀）。
    唔記原文：檢索事件只存 query SHA-256（見 app/ai/rag/audit.py）。
    """
    params: dict = {"h": hours}
    # ⚠️ ai_audit_log 嘅時間欄係 created_at（唔係 occurred_at）—— 2026-09-12 踩過
    where = "created_at > now() - make_interval(hours => :h)"
    if event_type:
        where += " AND event_type = :ev"
        params["ev"] = event_type

    total = (await db.execute(
        text(f"SELECT count(*) FROM nexus_ai.ai_audit_log WHERE {where}"), params)).scalar()

    by_type = (await db.execute(text(f"""
        SELECT event_type, count(*) AS hits, count(DISTINCT tenant_id) AS tenants
        FROM nexus_ai.ai_audit_log WHERE {where}
        GROUP BY 1 ORDER BY 2 DESC LIMIT 30
    """), params)).mappings().all()

    by_day = (await db.execute(text(f"""
        SELECT date_trunc('day', created_at)::date AS day, count(*) AS hits
        FROM nexus_ai.ai_audit_log WHERE {where}
        GROUP BY 1 ORDER BY 1
    """), params)).mappings().all()

    recent = (await db.execute(text(f"""
        SELECT created_at, event_type, tenant_id, user_id, session_id, detail
        FROM nexus_ai.ai_audit_log WHERE {where}
        ORDER BY created_at DESC LIMIT 50
    """), params)).mappings().all()

    return {
        "window_hours": hours,
        "event_type_filter": event_type,
        "total": int(total or 0),
        "by_event_type": [dict(r) for r in by_type],
        "by_day": [{"day": str(r["day"]), "hits": r["hits"]} for r in by_day],
        "recent": [
            {
                "occurred_at": r["created_at"].isoformat(),
                "event_type": r["event_type"],
                "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
                "user_id": str(r["user_id"]) if r["user_id"] else None,
                "session_id": str(r["session_id"]) if r["session_id"] else None,
                "detail": r["detail"],
            }
            for r in recent
        ],
    }


@router.get("/reports/errors")
async def report_errors(hours: int = Query(24, ge=1, le=720),
                        db: AsyncSession = Depends(get_admin_session)):
    """未處理錯誤 / 5xx 一覽（error monitoring）— 按時間+路徑+類型聚合 + 最近 20 筆。"""
    from app.services.error_monitor import list_errors

    return await list_errors(db, hours=hours)


@router.get("/reports/error-rate")
async def report_error_rate(days: int = Query(30, ge=1, le=365),
                            db: AsyncSession = Depends(get_admin_session)):
    """錯誤率趨勢 — 每日 calls / errors / error rate %"""
    rows = (
        await db.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       count(*) AS calls,
                       count(*) FILTER (WHERE result_status != 'success') AS errors
                FROM nexus_ai.usage_events
                WHERE created_at > now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 1
                """
            ),
            {"days": days},
        )
    ).mappings().all()
    return [{"day": str(r["day"]), "calls": r["calls"], "errors": r["errors"],
             "error_rate": round((r["errors"] or 0) / r["calls"] * 100, 2) if r["calls"] else 0.0}
            for r in rows]


@router.get("/reports/cost-by-provider")
async def report_cost_by_provider(days: int = Query(30, ge=1, le=365),
                                  db: AsyncSession = Depends(get_admin_session)):
    """Provider 成本分解 — GROUP BY provider"""
    rows = (
        await db.execute(
            text(
                """
                SELECT provider, count(*) AS calls,
                       COALESCE(sum(cost_estimate), 0) AS cost_usd,
                       sum(input_tokens) AS in_tok, sum(output_tokens) AS out_tok
                FROM nexus_ai.usage_events
                WHERE created_at > now() - make_interval(days => :days)
                GROUP BY provider ORDER BY cost_usd DESC
                """
            ),
            {"days": days},
        )
    ).mappings().all()
    return [{"provider": r["provider"] or "unknown", "calls": r["calls"],
             "cost_usd": round(float(r["cost_usd"] or 0), 4),
             "input_tokens": r["in_tok"] or 0, "output_tokens": r["out_tok"] or 0} for r in rows]


@router.get("/reports/db-size")
async def report_db_size(db: AsyncSession = Depends(get_admin_session)):
    """資料庫規模 — 主要表 row count（cross-schema）"""
    tables = [
        ("nexus_auth", "nexus_auth_tenants"), ("nexus_auth", "nexus_auth_users"),
        ("nexus_crm", "contacts"), ("nexus_crm", "companies"), ("nexus_crm", "tasks"),
        ("nexus_crm", "projects"), ("nexus_crm", "touchpoints"), ("nexus_crm", "namecards"),
        ("nexus_ai", "usage_events"), ("nexus_ai", "messages"),
    ]
    out = []
    for sch, tbl in tables:
        try:
            r = (await db.execute(text(f"SELECT count(*) AS c FROM {sch}.{tbl}"))).scalar_one()
            out.append({"schema": sch, "table": tbl, "rows": r or 0})
        except Exception:
            out.append({"schema": sch, "table": tbl, "rows": None})
    return out

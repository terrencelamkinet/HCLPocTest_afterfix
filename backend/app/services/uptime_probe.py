"""Status page —— uptime probe + incident 推導。

**為咩存在**：`error_events` 只記「有錯誤」，但**服務 down 咗可能連 request 都入唔到**
（middleware 都冇機會行）→ 冇 row。所以「有冇錯誤」≠「服務有冇死」。呢個 module 補嗰忽。

**設計取捨**：
  - **唔另開 incident 表** —— incident 由「連續失敗」推導（`derive_incidents`），
    冇 state 可以漂移，亦唔使兩個表同步
  - **冇 tenant_id / RLS** —— uptime 係平台基建數據，唔屬任何 tenant
  - HTTP client **可注入** → 測試唔打真 network；CLI 打真

CLI（建議 cron 每 2 分鐘）：
    cd backend && ./venv/bin/python -m app.services.uptime_probe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LOCK_PATH = "/tmp/uptime_probe.lock"
RETENTION_DAYS = 30
MIN_CONSECUTIVE = 2  # 連續幾個失敗先當 incident（單次 blip 唔報，避免誤報）

PROBES: list[dict[str, Any]] = [
    {"name": "main_api", "url": "http://127.0.0.1:8001/api/v1/ai/health", "expect": 200},
    {"name": "admin_api", "url": "http://127.0.0.1:8002/docs", "expect": 200},
    {"name": "admin_web", "url": "http://127.0.0.1:5175/", "expect": 200},
]

_TIMEOUT = 8.0


async def probe_once(
    *,
    targets: list[dict[str, Any]] | None = None,
    client: Any | None = None,
    db: AsyncSession | None = None,
    persist: bool = False,
) -> list[dict[str, Any]]:
    """探一次全部 target；**任何 target raise 都照記錄成失敗**（probe down 服務唔可以自己炸）。"""
    targets = targets if targets is not None else PROBES
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)

    results: list[dict[str, Any]] = []
    try:
        for t in targets:
            url = t["url"]
            expect = int(t.get("expect", 200))
            t0 = time.perf_counter()
            status_code = None
            err: str | None = None
            ok = False
            try:
                resp = await client.get(url, timeout=_TIMEOUT)
                status_code = getattr(resp, "status_code", None)
                ok = status_code == expect
                if not ok:
                    err = f"expected {expect}, got {status_code}"
            except Exception as e:  # 連唔到 / timeout / DNS ...
                err = f"{type(e).__name__}: {e}"
            latency_ms = int((time.perf_counter() - t0) * 1000)
            results.append(
                {
                    "probe_name": t["name"],
                    "target": url,
                    "ok": ok,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "error": err,
                }
            )
    finally:
        if own_client:
            await client.aclose()

    if persist and db is not None:
        for r in results:
            await db.execute(
                text("""
                    INSERT INTO nexus_ai.uptime_probes
                        (probe_name, target, ok, status_code, latency_ms, error, checked_at)
                    VALUES (:n, :t, :ok, :sc, :lat, :err, now())
                """),
                {"n": r["probe_name"], "t": r["target"], "ok": r["ok"],
                 "sc": r["status_code"], "lat": r["latency_ms"], "err": r["error"]},
            )
        await db.commit()

    for r in results:
        if not r["ok"]:
            logger.warning("uptime: %s DOWN (%s) %s", r["probe_name"], r["status_code"], r["error"])
    return results


def derive_incidents(rows: list[dict[str, Any]], min_consecutive: int = MIN_CONSECUTIVE) -> list[dict[str, Any]]:
    """由 probe rows 推導 incident：**連續** min_consecutive 次失敗 = 一個 window。

    單次失敗唔算（避免 blip 誤報）。仍然失敗到資料尾 = `resolved=False`。
    """
    by_probe: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_probe.setdefault(r["probe_name"], []).append(r)

    incidents: list[dict[str, Any]] = []
    for name, rs in by_probe.items():
        rs.sort(key=lambda x: x["checked_at"])
        i = 0
        while i < len(rs):
            if rs[i]["ok"]:
                i += 1
                continue
            j = i
            while j < len(rs) and not rs[j]["ok"]:
                j += 1
            run = rs[i:j]
            if len(run) >= min_consecutive:
                started = run[0]["checked_at"]
                ended = run[-1]["checked_at"]
                incidents.append(
                    {
                        "probe_name": name,
                        "started_at": started,
                        "ended_at": ended,
                        "duration_min": int((ended - started).total_seconds() // 60),
                        "failed_probes": len(run),
                        "resolved": j < len(rs),  # 尾後仲有 row = 已經恢復
                    }
                )
            i = j

    incidents.sort(key=lambda x: x["started_at"], reverse=True)
    return incidents


def uptime_pct(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """每個 probe 嘅 ok / total / pct。"""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = out.setdefault(r["probe_name"], {"total": 0, "ok": 0, "pct": 0.0})
        s["total"] += 1
        if r["ok"]:
            s["ok"] += 1
    for s in out.values():
        s["pct"] = round(s["ok"] * 100.0 / s["total"], 2) if s["total"] else 0.0
    return out


async def uptime_report(
    db: AsyncSession,
    *,
    hours: int = 24,
    probes: list[dict[str, Any]] | None = None,
    min_consecutive: int = MIN_CONSECUTIVE,
) -> dict[str, Any]:
    """Status page 要嘅數：per-probe uptime % / 平均 latency / 最新狀態 + incidents。"""
    rows = (
        await db.execute(
            text("""
                SELECT probe_name, target, ok, status_code, latency_ms, error, checked_at
                FROM nexus_ai.uptime_probes
                WHERE checked_at > now() - make_interval(hours => :h)
                ORDER BY checked_at DESC
            """),
            {"h": hours},
        )
    ).mappings().all()
    rows = [dict(r) for r in rows]

    stats = uptime_pct(rows)
    # 冇數據嘅 probe 都要出現（唔係 UI 就靜靜哋唔見咗）
    for p in (probes if probes is not None else PROBES):
        stats.setdefault(p["name"], {"total": 0, "ok": 0, "pct": None})

    latest: dict[str, dict[str, Any]] = {}
    lat: dict[str, list[int]] = {}
    for r in rows:  # 已經 DESC
        latest.setdefault(r["probe_name"], {"ok": r["ok"], "status_code": r["status_code"],
                                            "checked_at": r["checked_at"].isoformat(),
                                            "error": r["error"]})
        if r["latency_ms"] is not None:
            lat.setdefault(r["probe_name"], []).append(r["latency_ms"])

    out_probes: dict[str, Any] = {}
    for name, s in stats.items():
        lats = lat.get(name) or []
        out_probes[name] = {
            **s,
            "avg_latency_ms": int(sum(lats) / len(lats)) if lats else None,
            "latest_ok": (latest.get(name) or {}).get("ok"),
            "latest_at": (latest.get(name) or {}).get("checked_at"),
            "latest_error": (latest.get(name) or {}).get("error"),
            "down": (latest.get(name) or {}).get("ok") is False,
        }

    return {
        "window_hours": hours,
        "probes": out_probes,
        "incidents": [
            {
                **inc,
                "started_at": inc["started_at"].isoformat(),
                "ended_at": inc["ended_at"].isoformat(),
            }
            for inc in derive_incidents(rows, min_consecutive=min_consecutive)
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── CLI / cron ──

def _lock_acquire() -> bool:
    """PID-aware singleton lock（同 error_alert_job / rag_freshness 一致）。"""
    try:
        if os.path.exists(LOCK_PATH):
            with open(LOCK_PATH) as f:
                pid = int((f.read().strip() or "0"))
            try:
                os.kill(pid, 0)
                return False  # 仲跑緊
            except OSError:
                pass  # stale
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True  # lock 問題唔應該阻止 probe


def _lock_release() -> None:
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


async def _main_async(args: argparse.Namespace) -> int:
    from app.db import async_session

    async with async_session() as db:
        results = await probe_once(db=db, persist=True)
        # retention（順手；每日一次就夠，但便宜）
        if args.retention:
            await db.execute(
                text("DELETE FROM nexus_ai.uptime_probes "
                     "WHERE checked_at < now() - make_interval(days => :d)"),
                {"d": RETENTION_DAYS},
            )
            await db.commit()

    down = [r["probe_name"] for r in results if not r["ok"]]
    print(json.dumps({"probed": len(results), "down": down}, ensure_ascii=False))
    return 1 if down else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Uptime probe")
    p.add_argument("--retention", action="store_true", help="順便清 >30 日嘅 probe")
    args = p.parse_args(argv)

    if not _lock_acquire():
        logger.info("uptime_probe: 另一個 instance 跑緊，跳過")
        return 0
    try:
        return asyncio.run(_main_async(args))
    except Exception:
        logger.exception("uptime_probe failed")
        return 2
    finally:
        _lock_release()


if __name__ == "__main__":
    sys.exit(main())

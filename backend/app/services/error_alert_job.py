"""Error monitoring 告警 + retention（cron，建議每 10 分鐘）。

用途：
    python -m app.services.error_alert_job               # 告警檢查（順便每日做 retention）
    python -m app.services.error_alert_job --retention   # 只做 retention

行為：
  - 最近 WINDOW_MIN 分鐘錯誤數 ≥ THRESHOLD → 通知平台 owner（app 通知 + log）
    **唔准靜默**：有錯誤但唔出聲 = 等於冇監控
  - Cooldown（COOLDOWN_MIN 分鐘）防止洗版 —— 狀態存 file，重啟都唔會狂發
  - 每日（03:30-04:00 之間跑嗰次）清走 >RETENTION_DAYS 日嘅 error_events
  - Singleton lock（同 rag_freshness_job 一樣，PID-aware）
  - 有告警 → 非零 exit code（俾外部監控捕捉）

⚠️ 改 admin.py / 呢個 job 之後，兩個 service 都要重啟：
    sudo systemctl restart nexus-crm nexus-admin-api
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger("error_alert")

# 告警閾值：15 分鐘內 ≥5 個未處理錯誤
WINDOW_MIN = 15
THRESHOLD = 5
COOLDOWN_MIN = 60
RETENTION_DAYS = 30

LOCK_PATH = "/tmp/error_alert.lock"
COOLDOWN_PATH = "/tmp/error_alert_cooldown"

# 平台 owner（告警收件人）—— 同 admin console 嘅 owner tenant 一致
OWNER_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _acquire_lock() -> bool:
    """PID-aware singleton lock（stale lock 自動接手）。"""
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH) as f:
                pid = int((f.read().strip() or "0"))
        except Exception:
            pid = 0
        if pid and os.path.exists(f"/proc/{pid}"):
            return False
        logger.warning("stale error_alert lock (pid=%s dead) — taking over", pid)
    try:
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        return False
    return True


def _release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except Exception:
        pass


def _in_cooldown() -> bool:
    if not os.path.exists(COOLDOWN_PATH):
        return False
    try:
        last = datetime.fromtimestamp(os.path.getmtime(COOLDOWN_PATH), tz=timezone.utc)
    except Exception:
        return False
    return datetime.now(timezone.utc) - last < timedelta(minutes=COOLDOWN_MIN)


def _mark_alerted() -> None:
    try:
        with open(COOLDOWN_PATH, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


async def _summary(adb, tenant_id: str | None = None) -> dict:
    """最近窗口嘅錯誤摘要（按路徑/類型）。

    2026-09-15：可選 tenant filter。生產 cron 唔傳（全局，行為不變）；test 傳自己
    個 tenant，令結果唔會被其他 test 產生嘅錯誤污染（之前真係互相污染）。
    """
    where = "occurred_at > now() - make_interval(mins => :m)"
    params: dict = {"m": WINDOW_MIN}
    if tenant_id:
        where += " AND tenant_id = :t"
        params["t"] = str(tenant_id)
    rows = (
        await adb.execute(
            text(f"""
                SELECT path, error_type, status_code, count(*) AS hits
                FROM nexus_ai.error_events
                WHERE {where}
                GROUP BY 1, 2, 3
                ORDER BY 4 DESC
                LIMIT 5
            """),
            params,
        )
    ).mappings().all()
    total = (
        await adb.execute(
            text(f"SELECT count(*) FROM nexus_ai.error_events WHERE {where}"),
            params,
        )
    ).scalar()
    return {"total": int(total or 0), "top": [dict(r) for r in rows]}


async def check_and_alert(tenant_id: str | None = None) -> dict:
    """檢查閾值 → 超標就通知 owner。回傳結果（供 test / log）。
    tenant_id: 只計某個 tenant 嘅錯誤（test 隔離用）；預設 None = 全局（生產行為）。
    """
    from app.db_admin import _get_admin_sessionmaker

    async with _get_admin_sessionmaker()() as adb:
        s = await _summary(adb, tenant_id=tenant_id)

    result = {"total": s["total"], "threshold": THRESHOLD, "alerted": False, "skipped": None}
    if s["total"] < THRESHOLD:
        return result
    if _in_cooldown():
        result["skipped"] = "cooldown"
        logger.warning(
            "error alert SUPPRESSED by cooldown (total=%s in %smin)", s["total"], WINDOW_MIN
        )
        return result

    lines = [f"最近 {WINDOW_MIN} 分鐘有 {s['total']} 個未處理錯誤（閾值 {THRESHOLD}）"]
    for t in s["top"]:
        lines.append(f"• {t['path']} [{t['error_type']}] ×{t['hits']}")
    body = "\n".join(lines)

    # 告警寫入 error_events（error_type=ALERT_THRESHOLD）—— 會直接出現喺
    # admin console 嘅 Errors 頁，唔需要硬編碼 user_id，亦唔依賴通知偏好。
    try:
        from app.services.error_monitor import record_error

        await record_error(
            method="ALERT",
            path="/__alert__/error-threshold",
            status_code=599,
            error_type="ALERT_THRESHOLD",
            message=body,
        )
        result["notified"] = True
        _mark_alerted()
        result["alerted"] = True
        logger.error("error alert RAISED: %s", body.replace("\n", " | "))
    except Exception:
        logger.exception("error alert write failed (total=%s)", s["total"])

    return result


async def run_retention(days: int = RETENTION_DAYS) -> int:
    """清走舊 error_events（admin session）+ 過期 OAuth state（app session）。

    2026-09-15：OAuth state 一次性 + 15 分鐘 TTL（見 crm_integrations.oauth_callback）。
    冇人 callback 嘅 state 會一直留低（實測累積 300+ row），順手清。1 日足夠 cover
    任何仲進行緊嘅 flow。用 app session（nexus_oauth_states owner = gg_fighter）；
    admin role 對呢張表只有 SELECT。
    """
    from app.db_admin import _get_admin_sessionmaker

    async with _get_admin_sessionmaker()() as adb:
        res = await adb.execute(
            text("DELETE FROM nexus_ai.error_events WHERE occurred_at < now() - make_interval(days => :d)"),
            {"d": days},
        )
        await adb.commit()
        deleted = int(getattr(res, "rowcount", 0) or 0)

    from app.db import async_session

    async with async_session() as s:
        st = await s.execute(
            text("DELETE FROM nexus_crm.nexus_oauth_states WHERE created_at < now() - interval '1 day'")
        )
        await s.commit()
        states = int(getattr(st, "rowcount", 0) or 0)

    logger.info(
        "retention: error_events deleted %s rows older than %s days; oauth_states deleted %s rows older than 1 day",
        deleted,
        days,
        states,
    )
    return deleted


async def run(*, retention_only: bool = False) -> dict:
    out: dict = {"alert": None, "retention_deleted": None}
    if not retention_only:
        out["alert"] = await check_and_alert()
    # 每日 03:xx 跑嗰次順便做 retention
    now_hkt = datetime.now(timezone.utc) + timedelta(hours=8)
    if retention_only or (now_hkt.hour == 3):
        out["retention_deleted"] = await run_retention()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retention", action="store_true", help="只做 retention")
    args = ap.parse_args()

    if not _acquire_lock():
        logger.warning("another error_alert run is in progress — skipping this tick")
        return 0
    try:
        out = asyncio.run(run(retention_only=args.retention))
    finally:
        _release_lock()

    alert = out.get("alert") or {}
    logger.info("error_alert done: %s", out)
    return 1 if alert.get("alerted") else 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    raise SystemExit(main())

"""Renewal Radar —— 合約／訂閱到期追蹤 + 到期前提醒。

**為咩存在**：CRM 用戶會唔記得客戶合約／訂閱／licence 幾時到期 → 白白走失續約生意。
之前完全冇 renewal 概念，亦冇任何「到期前提醒」。

**設計（Less is more）**：唔砌完整「合約管理模組」，只做追蹤 + 提醒所需嘅嘢。
  - `is_due` 有**下界**（default 30 日）：過期太耐嘅唔再嘈（唔係死線已過就無限提醒）
  - 提醒去重靠 `last_notified_at`（7 日窗口）→ **唔會日日嘈你**
  - 冇 owner 就唔發通知（唔可以通知「冇人」）

CLI（建議 cron 每日一次）：
    cd backend && ./venv/bin/python -m app.services.renewal_radar
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LOCK_PATH = "/tmp/renewal_radar.lock"
OVERDUE_GRACE_DAYS = 30   # 過期幾多日之內仍然提醒
RENOTIFY_AFTER_DAYS = 7   # 同一張幾多日後可以再提醒


def days_left(renewal_date: date, today: date) -> int:
    return (renewal_date - today).days


def is_due(
    renewal_date: date,
    notice_days: int,
    today: date,
    *,
    overdue_grace_days: int = OVERDUE_GRACE_DAYS,
) -> bool:
    """到咗 `renewal_date - notice_days` 就要提醒；過期但 ≤ grace 日都要（overdue 警告）。"""
    d = days_left(renewal_date, today)
    if d > notice_days:
        return False
    return d >= -overdue_grace_days


async def scan_renewals(
    db: AsyncSession, tenant_id: UUID, *, today: date | None = None
) -> list[dict[str, Any]]:
    """所有 status='active' 且 due 嘅 renewal（含仲未到期但入咗通知窗口嘅）。"""
    today = today or datetime.now(timezone.utc).date()
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    rows = (
        await db.execute(
            text("""
                SELECT id, name, company_id, amount, currency, renewal_date, notice_days,
                       owner_id, last_notified_at,
                       (renewal_date - CAST(:today AS date)) AS days_left
                FROM nexus_crm.renewals
                WHERE tenant_id = :t AND status = 'active'
                ORDER BY renewal_date
            """),
            {"t": tenant_id, "today": today},
        )
    ).mappings().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        if not is_due(r["renewal_date"], r["notice_days"], today):
            continue
        d = dict(r)
        d["id"] = str(d["id"])
        d["company_id"] = str(d["company_id"]) if d["company_id"] else None
        d["owner_id"] = str(d["owner_id"]) if d["owner_id"] else None
        d["overdue"] = d["days_left"] < 0
        out.append(d)
    return out


async def notify_due_renewals(
    db: AsyncSession, tenant_id: UUID, *, today: date | None = None
) -> dict[str, Any]:
    """為 due 嘅 renewal 寫通知（受 7 日窗口 + owner 存在限制）。"""
    from app.services.notification_writer import notify_event

    today = today or datetime.now(timezone.utc).date()
    due = await scan_renewals(db, tenant_id, today=today)

    notified: list[str] = []
    skipped_no_owner: list[str] = []
    skipped_recent: list[str] = []

    for r in due:
        if not r["owner_id"]:
            skipped_no_owner.append(r["name"])
            continue
        ln = r["last_notified_at"]
        if ln is not None:
            # naive vs aware 都要頂得住
            ln_date = ln.date() if isinstance(ln, datetime) else ln
            if (today - ln_date).days < RENOTIFY_AFTER_DAYS:
                skipped_recent.append(r["name"])
                continue

        d = r["days_left"]
        if d < 0:
            when = f"已經過期 {abs(d)} 日"
        elif d == 0:
            when = "今日到期"
        else:
            when = f"{d} 日後到期"
        amt = f"（{r['amount']} {r['currency']}）" if r["amount"] is not None else ""
        await notify_event(
            db,
            tenant_id,
            UUID(r["owner_id"]),
            source_module="business",
            source_record_type="renewal",
            source_record_id=UUID(r["id"]),
            title=f"🔄 續約提醒：{r['name']}",
            body=f"{when}{amt}。到期日 {r['renewal_date']}。",
            group_key=f"renewal:{r['id']}:{today.isoformat()}",
        )
        await db.execute(
            text("UPDATE nexus_crm.renewals SET last_notified_at = now() WHERE id = :id"),
            {"id": UUID(r["id"])},
        )
        notified.append(r["name"])

    await db.commit()
    if notified:
        logger.info("renewal_radar: notified %d (%s)", len(notified), ", ".join(notified))
    return {
        "due": len(due),
        "notified": len(notified),
        "skipped_no_owner": skipped_no_owner,
        "skipped_recent": skipped_recent,
    }


# ── CLI / cron ──

def _lock_acquire() -> bool:
    try:
        if os.path.exists(LOCK_PATH):
            with open(LOCK_PATH) as f:
                pid = int((f.read().strip() or "0"))
            try:
                os.kill(pid, 0)
                return False
            except OSError:
                pass
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True


def _lock_release() -> None:
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


async def _main_async(args: argparse.Namespace) -> int:
    from app.db import async_session
    from app.db_admin import _get_admin_sessionmaker

    # 用 admin session（BYPASSRLS）搵「有 due renewal」嘅 tenant，再逐個 tenant 用 app session 做
    admin_sm = _get_admin_sessionmaker()
    async with admin_sm() as adb:
        tenants = [
            r[0]
            for r in (
                await adb.execute(
                    text("""
                        SELECT DISTINCT tenant_id FROM nexus_crm.renewals
                        WHERE status = 'active'
                          AND renewal_date <= (CURRENT_DATE + make_interval(days => notice_days))
                          AND renewal_date >= (CURRENT_DATE - make_interval(days => :grace))
                    """),
                    {"grace": OVERDUE_GRACE_DAYS},
                )
            ).all()
        ]

    total = {"due": 0, "notified": 0}
    for tid in tenants:
        async with async_session() as db:
            res = await notify_due_renewals(db, tid)
            total["due"] += res["due"]
            total["notified"] += res["notified"]

    print(json.dumps({"tenants": len(tenants), **total}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Renewal Radar daily scan").parse_args(argv)
    if not _lock_acquire():
        logger.info("renewal_radar: 另一個 instance 跑緊，跳過")
        return 0
    try:
        return asyncio.run(_main_async(argparse.Namespace()))
    except Exception:
        logger.exception("renewal_radar failed")
        return 2
    finally:
        _lock_release()


if __name__ == "__main__":
    sys.exit(main())

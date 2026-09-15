"""RAG 索引新鮮度 job（T2）— cron 入口。

用法：
    python -m app.services.rag_freshness_job            # 增量（建議每 15 分鐘）
    python -m app.services.rag_freshness_job --full     # 全量重建兜底（建議每日 03:00）
    python -m app.services.rag_freshness_job --check    # 只做落後檢查（唔重建）

設計：
  - 掃描（跨 tenant）用 admin session（BYPASSRLS）—— app role 受 RLS 限制睇唔到其他 tenant
  - 重建（寫入）用 app session + RLS GUC + 明確 tenant_id —— 寫入永遠受 RLS 約束（雙重保障）
  - 索引落後超 24h → WARNING log（唔准靜默落後）
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

from app.ai.rag.freshness import DEFAULT_MAX_LAG, detect_stale_tenants, dirty_tenants
from app.ai.rag.reindex import ENTITY_QUERIES, delete_tenant_vectors, reindex_tenant
from app.db import async_session
from app.db_admin import _get_admin_sessionmaker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag_freshness")

# 增量窗口：稍為大過 cron 間隔，防止「跑完之後即刻又有改動」之間漏掉
INCREMENTAL_WINDOW = timedelta(minutes=45)

# Singleton lock（PID-aware）：兩個 run 同時跑會產生重複 doc —— 見 _acquire_lock 註解
LOCK_PATH = "/tmp/rag_freshness.lock"


async def _tenants_with_crm_data(adb) -> set[UUID]:
    """邊啲 tenant 有 CRM 資料（由資料推導，唔假設 tenants 表 schema）。"""
    found: set[UUID] = set()
    for _module, table_name, _sql in ENTITY_QUERIES:
        try:
            rows = (await adb.execute(text(f"SELECT DISTINCT tenant_id FROM {table_name}"))).scalars().all()
        except Exception as exc:
            logger.warning("tenant scan skipped %s: %s", table_name, exc)
            continue
        found.update(r for r in rows if r)
    return found


async def _index_state(adb) -> dict[str, datetime]:
    rows = (
        await adb.execute(
            text(
                "SELECT tenant_id, max(created_at) AS latest "
                "FROM nexus_ai.vector_documents GROUP BY tenant_id"
            )
        )
    ).all()
    return {str(r[0]): r[1] for r in rows}


async def run(*, full: bool = False, check_only: bool = False) -> dict:
    summary: dict = {
        "mode": "check" if check_only else ("full" if full else "incremental"),
        "tenants_touched": 0,
        "docs": 0,
        "chunks": 0,
        "stale": [],
        "errors": [],
    }

    admin = _get_admin_sessionmaker()

    # ── 1. 掃描（admin / BYPASSRLS，唯讀）──
    async with admin() as adb:
        if full:
            _tenants = await _tenants_with_crm_data(adb)
            plan: dict[UUID, set[str] | None] = {t: None for t in _tenants}
        elif check_only:
            plan = {}
        else:
            since = datetime.now(timezone.utc) - INCREMENTAL_WINDOW
            dirty = await dirty_tenants(adb, since=since)
            plan = {t: mods for t, mods in dirty.items()}

        state = await _index_state(adb)
        summary["stale"] = detect_stale_tenants(state, max_lag=DEFAULT_MAX_LAG)

    if summary["stale"]:
        # 唔准靜默落後 —— 落後要出聲
        logger.warning(
            "RAG index STALE for %d tenant(s) (>%sh): %s",
            len(summary["stale"]),
            int(DEFAULT_MAX_LAG.total_seconds() // 3600),
            ", ".join(summary["stale"][:5]),
        )

    if not plan:
        logger.info("rag_freshness: nothing to reindex (mode=%s)", summary["mode"])
        return summary

    # ── 2. 重建（app session + RLS，逐 tenant 明確範圍）──
    for tenant_id, modules in plan.items():
        try:
            async with async_session() as db:
                if full:
                    # T2 修正：全量重建要先清空該 tenant 嘅向量。
                    # 唔清空嘅話「孤兒」(source_record_id 已唔存在嘅舊 doc) 永遠清唔走 ——
                    # 因為 per-record purge 只會處理到仲存在嘅記錄。實測：舊 tf-idf 438 份
                    # 就係咁樣留低，令索引新舊混。
                    deleted = await delete_tenant_vectors(db, tenant_id=tenant_id)
                    await db.commit()
                    logger.info("purged existing vectors tenant=%s deleted=%s", tenant_id, deleted)
                stats = await reindex_tenant(
                    db,
                    tenant_id=tenant_id,
                    source_modules=sorted(modules) if modules else None,
                )
            summary["tenants_touched"] += 1
            summary["docs"] += int(stats.get("total_docs", 0))
            summary["chunks"] += int(stats.get("total_chunks", 0))
            logger.info(
                "reindexed tenant=%s modules=%s docs=%s chunks=%s",
                tenant_id,
                sorted(modules) if modules else "ALL",
                stats.get("total_docs"),
                stats.get("total_chunks"),
            )
        except Exception as exc:  # 單一 tenant 失敗唔可以拖冧成個 job
            summary["errors"].append(f"{tenant_id}: {exc}")
            logger.exception("reindex failed tenant=%s", tenant_id)

    logger.info("rag_freshness done: %s", summary)
    return summary


def _acquire_lock() -> str | None:
    """PID-aware singleton lock —— 防止兩個 run 同時跑（會產生重複 doc）。

    實證 2026-09-12：手動 --full 同 14:45 嘅 cron 增量重疊，兩邊都插入 task doc
    → 25 份重複（增量 run 睇唔到未 commit 嘅 doc，purge 冇嘢可刪）。
    Stale lock（PID 已死）自動失效，唔會永久卡住。
    """
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH) as f:
                pid = int((f.read().strip() or "0"))
        except Exception:
            pid = 0
        if pid and os.path.exists(f"/proc/{pid}"):
            return None
        logger.warning("stale rag_freshness lock (pid=%s dead) — taking over", pid)
    try:
        with open(LOCK_PATH, "w") as f:
            f.write(str(os.getpid()))
    except Exception as exc:
        logger.warning("cannot write lock file: %s", exc)
        return None
    return LOCK_PATH


def _release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="全量重建兜底")
    ap.add_argument("--check", action="store_true", help="只檢查落後，唔重建")
    args = ap.parse_args()

    lock = _acquire_lock()
    if lock is None:
        logger.warning("another rag_freshness run is in progress — skipping this tick")
        return 0
    try:
        summary = asyncio.run(run(full=args.full, check_only=args.check))
    finally:
        _release_lock()
    # 有 tenant 落後 → 非零 exit code，方便外部監控捕捉（唔靠人睇 log）
    return 1 if summary["stale"] or summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

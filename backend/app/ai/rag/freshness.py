"""索引新鮮度（T2）— 令 RAG 索引跟得上 CRM 改動。

設計（docs/rag-TODO.md T2 + docs/rag-SPEC.md D4）：
  - 偵測：搵出最近有 CRM 改動嘅 tenant（需要 admin / BYPASSRLS session —— app role
    受 RLS 限制，正常情況睇唔到其他 tenant，所以跨 tenant 掃描只可以讀，唔可以寫）
  - 增量：只重建受影響 module（範圍由 ENTITY_QUERIES 提供，單一 source of truth）
  - 兜底：每日一次全量重建（防止漏事件）
  - 監控：索引落後超閾值要報（唔准靜默落後）
  - 隔離：所有寫入都以明確 tenant_id 為範圍，經 app session + RLS GUC（雙重保障）

狀態唔另開表：索引新鮮度 = `max(vector_documents.created_at)`，直接由真實資料推導，
避免「state 表同現實脫節」。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.reindex import ENTITY_QUERIES, purge_record_vectors

logger = logging.getLogger(__name__)

DEFAULT_MAX_LAG = timedelta(hours=24)

__all__ = [
    "DEFAULT_MAX_LAG",
    "purge_record_vectors",
    "dirty_tenants",
    "detect_stale_tenants",
    "index_freshness",
]


async def dirty_tenants(
    db: AsyncSession,
    *,
    since: datetime,
) -> dict[UUID, set[str]]:
    """邊個 tenant 有 CRM 記錄喺 *since* 之後改過 → {tenant_id: {module, ...}}。

    用 admin session（BYPASSRLS）；app session 只會見到自己 tenant。
    某個表掃唔到（例如冇 updated_at）→ log warning 同跳過，唔會靜默當「冇改動」。
    """
    changed: dict[UUID, set[str]] = {}
    for module_name, table_name, _query_sql in ENTITY_QUERIES:
        sql = f"SELECT DISTINCT tenant_id FROM {table_name} WHERE updated_at > :since"
        try:
            rows = (await db.execute(text(sql), {"since": since})).scalars().all()
        except Exception as exc:  # 表冇 updated_at / 權限問題 → 要出聲
            logger.warning("dirty scan skipped %s: %s", table_name, exc)
            continue
        for tid in rows:
            if tid:
                changed.setdefault(tid, set()).add(module_name)
    return changed


def detect_stale_tenants(
    state: dict[str, datetime],
    *,
    now: datetime | None = None,
    max_lag: timedelta = DEFAULT_MAX_LAG,
) -> list[str]:
    """索引落後超 *max_lag* 嘅 tenant（純函數，方便測）。

    state = {tenant_id: 最後成功索引時間}
    """
    now = now or datetime.now(timezone.utc)
    stale: list[str] = []
    for tenant_id, last_success in state.items():
        if last_success is None:
            stale.append(str(tenant_id))
            continue
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        if now - last_success > max_lag:
            stale.append(str(tenant_id))
    return sorted(stale)


async def index_freshness(db: AsyncSession, *, tenant_id: UUID) -> dict:
    """某 tenant 嘅索引新鮮度（落後秒數 / 最後更新）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    row = (
        await db.execute(
            text("""
                SELECT max(created_at) AS latest, count(*) AS docs
                FROM nexus_ai.vector_documents WHERE tenant_id = :t
            """),
            {"t": tenant_id},
        )
    ).mappings().first()
    latest = row["latest"] if row else None
    lag = None
    if latest is not None:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        lag = (datetime.now(timezone.utc) - latest).total_seconds()
    return {
        "tenant_id": str(tenant_id),
        "docs": int(row["docs"] or 0) if row else 0,
        "latest_indexed_at": latest.isoformat() if latest else None,
        "lag_seconds": lag,
        "stale": (lag is None) or (lag > DEFAULT_MAX_LAG.total_seconds()),
    }

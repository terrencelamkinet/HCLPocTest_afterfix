"""Tenant 建立時嘅一次過 bootstrap（2026-09-12 結構性修復）。

背景（用戶質問：「點解有人會冇 workspace？點解會 500？」）：
  * register（email/password）同 Google signup 兩個路徑，都只建立
    Tenant + TenantMember，**從來冇建立 workspace**。
  * 所有寫入（companies / contacts / tasks / projects / notes / deals /
    touchpoints）都要求 workspace_id NOT NULL。
  * 全世界唯一建立過 workspace 嘅地方係 app/migrations/003_backfill_workspace.sql
    —— 一次性 backfill，只覆蓋「當時已存在」嘅 tenant。
  → 003 之後每一個新註冊用戶，都由第一日開始「建立任何嘢都 HTTP 500」，
    但 GET 完全正常（GET 唔需要 workspace_id），所以一直冇人為意。

修復策略（唔靠逐次加 guard 補鑊）：
  tenant 一建立就同步建立 default workspace，令 tenant 由一開始就完整。
  app/db.py 嘅 lazy self-heal 保留做第二層防線（覆蓋未知嘅舊路徑）。
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def ensure_default_workspace(
    db: AsyncSession,
    tenant_id: UUID,
    owner_user_id: UUID | None = None,
) -> UUID | None:
    """確保 tenant 最少有一個 workspace，回傳 workspace id（idempotent）。"""
    # Workspaces 目前冇開 RLS，但同 notification_service 一樣明確 set GUC，
    # 咁將來就算開 RLS 都唔會靜默失敗。
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )

    existing = (
        await db.execute(
            text(
                """
                SELECT id FROM nexus_auth.workspaces
                WHERE tenant_id = :tid
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"tid": str(tenant_id)},
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    wid = (
        await db.execute(
            text(
                """
                INSERT INTO nexus_auth.workspaces
                    (tenant_id, name, owner_user_id, is_system_generated)
                VALUES (:tid, 'Default Workspace', :uid, true)
                RETURNING id
                """
            ),
            {
                "tid": str(tenant_id),
                "uid": str(owner_user_id) if owner_user_id else None,
            },
        )
    ).scalar_one_or_none()
    logger.info("bootstrapped Default Workspace %s for tenant %s", wid, tenant_id)
    return wid

"""Notification writer helper — SPEC notifications-revamp T2/T3 (2026-09-06).

系統/業務事件 producer 統一入口。寫入 notifications 表（source_module 標記），
同一 group_key 已存在 → skip（dedup — 防重複 spam，跟 notification_scan 做法）。
寫入失敗絕唔可以影響主流程（try/except 全吞）。

用法：
    from app.services.notification_writer import notify_event
    await notify_event(db, tenant_id, user_id, source_module="system",
                       title="AI 用量已用完", body="...",
                       group_key=f"quota_exhausted:{week_key}")
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def notify_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    source_module: str,
    title: str,
    body: str | None = None,
    group_key: str | None = None,
    priority: str = "NORMAL",
    source_record_type: str | None = None,
    source_record_id: uuid.UUID | None = None,
) -> bool:
    """寫一條 notification；group_key 已存在 → skip（同日唔重複）。

    Return True = 寫入咗；False = dedup skip 或寫入失敗。
    """
    try:
        if group_key:
            exists = (
                await db.execute(
                    select(Notification.id)
                    .where(
                        Notification.tenant_id == tenant_id,
                        Notification.user_id == user_id,
                        Notification.group_key == group_key,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if exists:
                return False
        # savepoint — RLS fail 只 rollback 通知寫入，唔可以炸 caller 主流程
        # （2026-09-06 實錘：special-access handler 無 GUC session 寫 Notification
        #  違反 RLS → 成個 commit 500）
        async with db.begin_nested():
            db.add(
                Notification(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    source_module=source_module,
                    source_record_type=source_record_type,
                    source_record_id=source_record_id,
                    title=title,
                    body=body,
                    priority=priority,
                    group_key=group_key,
                    status="UNREAD",
                )
            )
        return True
    except Exception:
        return False  # 通知寫入失敗唔可以影響主流程（savepoint 由 caller 控制）

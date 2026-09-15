"""Meeting → Task 自動轉換。

**為咩存在**：`calendar_followup.py` 嘅 T+30 engine 只係**問用戶**「有冇跟進」（出 touchpoint
草稿），**從來冇建立 Task** → 跟進事項唔會入任務清單，即係冇人會做。呢個 module 補嗰忽。

**設計**（用返 `tasks` 表本身為此而設嘅欄）：
  - `auto_suggested=True` + `suggestion_confidence` → UI 分得出「AI 建議」vs「人手建立」
  - `linked_via_signal = <event id>` → **呢個係去重鍵**：同一會議唔可以出兩張 task

**唔自己 commit**：由 caller 控制 transaction（同 DLP / audit 一致 —— 見 KB-022）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TITLE_PREFIX = "跟進會議："
DEFAULT_CONFIDENCE = 0.6


def build_task_title(event_title: str | None) -> str:
    """空白 / 冇 title 都要出一個**有意義**嘅 task title（唔准建空白 task）。"""
    t = (event_title or "").strip()
    if not t:
        return f"{TITLE_PREFIX}（未命名會議）"
    return f"{TITLE_PREFIX}{t[:180]}"


async def create_task_from_meeting(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    workspace_id: UUID,
    event_id: UUID,
    event_title: str | None,
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    due_date: date | None = None,
    days_after: int = 1,
    confidence: float = DEFAULT_CONFIDENCE,
    visibility_scope: str = "workspace",
) -> dict:
    """由一個會議（calendar event）建立跟進 Task。

    **Idempotent**：同一 `event_id` 只可以有一張 task（靠 `linked_via_signal`）。
    回 `{"created": bool, "task_id": str, ...}`。
    """
    # RLS：app session 寫入前要設 GUC
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})

    existing = (
        await db.execute(
            text(
                """
                SELECT id FROM nexus_crm.tasks
                WHERE tenant_id = :t AND linked_via_signal = :e AND status <> 'cancelled'
                LIMIT 1
                """
            ),
            {"t": tenant_id, "e": event_id},
        )
    ).first()
    if existing:
        return {"created": False, "reason": "exists", "task_id": str(existing[0])}

    due = due_date or (date.today() + timedelta(days=days_after))
    title = build_task_title(event_title)

    task_id = (
        await db.execute(
            text(
                """
                INSERT INTO nexus_crm.tasks
                    (tenant_id, workspace_id, title, due_date, priority, status,
                     assignee_id, company_id, contact_id, created_by,
                     auto_suggested, suggestion_confidence, linked_via_signal, visibility_scope)
                VALUES (:tenant_id, :workspace_id, :title, :due_date, 'medium', 'pending',
                        :assignee_id, :company_id, :contact_id, :created_by,
                        true, :confidence, :event_id, :visibility_scope)
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "title": title,
                "due_date": due,
                "assignee_id": user_id,
                "company_id": company_id,
                "contact_id": contact_id,
                "created_by": user_id,
                "confidence": confidence,
                "event_id": event_id,
                "visibility_scope": visibility_scope,
            },
        )
    ).scalar()
    await db.flush()

    logger.info(
        "meeting_task created: event=%s task=%s title=%r due=%s confidence=%s",
        event_id, task_id, title, due, confidence,
    )
    return {"created": True, "task_id": str(task_id), "title": title, "due_date": str(due)}

"""
Notifications Router — Platform-level notification API.

Endpoints:
  GET    /notifications                  → list (paginated, filterable)
  GET    /notifications/unread-count     → unread count
  PATCH  /notifications/{id}/read        → mark single as read
  POST   /notifications/read-all         → mark all as read
  GET    /notification-preferences       → get preferences
  PUT    /notification-preferences       → update preferences
  POST   /notifications/ai               → Agent API: push AI notification

Phase 3: GET /notifications/stream (SSE)
"""

from uuid import UUID
from datetime import datetime, timezone, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tenant_session
from app.models.notification import Notification, NotificationPreference

router = APIRouter(prefix="/api/v1")


def _tid(request: Request) -> UUID:
    tid = request.state.tenant_id
    if not tid:
        raise HTTPException(403, "Tenant not identified")
    return tid


def _uid(request: Request) -> UUID:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "User not authenticated")
    return uid


# ─── LIST ─────────────────────────────────────────────────────
@router.get("/notifications")
async def list_notifications(
    request: Request,
    status: Optional[str] = Query(None, regex="^(UNREAD|READ|DISMISSED)$"),
    module: Optional[str] = Query(None),
    priority: Optional[str] = Query(None, regex="^(CRITICAL|HIGH|NORMAL|LOW)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(Notification).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
    )
    if status:
        q = q.where(Notification.status == status)
    if module:
        q = q.where(Notification.source_module == module)
    if priority:
        q = q.where(Notification.priority == priority)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    # NULLS LAST：created_at 可能係 NULL（舊 raw insert）— 唔加嘅話 Postgres DESC
    # 默認 NULLS FIRST，最新通知會排到最尾（2026-09-10 Terrence 真機反饋）
    q = q.order_by(Notification.created_at.desc().nullslast()).offset(offset).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {"items": [_dump(n) for n in rows], "total": total, "page": page, "page_size": page_size}


# ─── UNREAD COUNT ─────────────────────────────────────────────
@router.get("/notifications/unread-count")
async def unread_count(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    q = select(func.count()).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
        Notification.status == "UNREAD",
    )
    count = (await db.execute(q)).scalar() or 0
    return {"unread_count": count}


# ─── MARK SINGLE READ ─────────────────────────────────────────
@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    request: Request,
    notification_id: UUID,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    n = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not n:
        raise HTTPException(404, "Notification not found")

    n.status = "READ"
    n.read_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok"}


# ─── MARK ALL READ ────────────────────────────────────────────
@router.post("/notifications/read-all")
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)
    now = datetime.now(timezone.utc)

    await db.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.status == "UNREAD",
        )
        .values(status="READ", read_at=now)
    )
    await db.commit()
    return {"status": "ok"}


# ─── AGENT API: PUSH AI NOTIFICATION ──────────────────────────
@router.post("/notifications/ai", status_code=201)
async def create_ai_notification(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_tenant_session),
):
    """Agent API — external AI agent pushes a notification (Phase 3: validate agent_token)."""
    tenant_id = _tid(request)
    user_id = payload.get("user_id", _uid(request))

    n = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        source_module=payload.get("source_module"),
        source_record_type=payload.get("source_record_type"),
        source_record_id=payload.get("source_record_id"),
        title=payload["title"],
        body=payload.get("body"),
        priority=payload.get("priority", "NORMAL"),
        is_ai_generated=True,
        ai_rationale=payload.get("rationale"),
        ai_confidence=payload.get("confidence"),
        generated_by_agent_id=payload.get("agent_id", "hermes"),
        action_url=payload.get("action_url"),
    )
    db.add(n)
    await db.commit()
    return {"id": str(n.id)}


# ─── GET PREFERENCES ──────────────────────────────────────────
@router.get("/notification-preferences")
async def get_preferences(
    request: Request,
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    rows = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.tenant_id == tenant_id,
                NotificationPreference.user_id == user_id,
            )
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(p.id),
                "module_key": p.module_key,
                "channels": p.channels if p.channels else ["IN_APP"],
                "priority_min": p.priority_min,
                "is_muted": p.is_muted,
                "digest": p.digest,
                "quiet_start": p.quiet_start.isoformat() if p.quiet_start else None,
                "quiet_end": p.quiet_end.isoformat() if p.quiet_end else None,
                "timezone": p.timezone,
                "agent_push_enabled": p.agent_push_enabled,
                "agent_digest_enabled": p.agent_digest_enabled,
            }
            for p in rows
        ],
    }


# ─── UPDATE PREFERENCES ───────────────────────────────────────
@router.put("/notification-preferences")
async def update_preferences(
    request: Request,
    payload: list[dict],
    db: AsyncSession = Depends(get_tenant_session),
):
    tenant_id = _tid(request)
    user_id = _uid(request)

    for item in payload:
        existing = (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.tenant_id == tenant_id,
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.module_key == item["module_key"],
                )
            )
        ).scalar_one_or_none()

        if existing:
            for field in ("channels", "priority_min", "is_muted", "digest",
                          "agent_push_enabled", "agent_digest_enabled", "timezone"):
                if field in item:
                    setattr(existing, field, item[field])
            if item.get("quiet_start"):
                existing.quiet_start = time.fromisoformat(item["quiet_start"])
            if item.get("quiet_end"):
                existing.quiet_end = time.fromisoformat(item["quiet_end"])
        else:
            db.add(NotificationPreference(
                tenant_id=tenant_id,
                user_id=user_id,
                module_key=item["module_key"],
                channels=item.get("channels", ["IN_APP"]),
                priority_min=item.get("priority_min", "NORMAL"),
                is_muted=item.get("is_muted", False),
                digest=item.get("digest", "REALTIME"),
                quiet_start=time.fromisoformat(item["quiet_start"]) if item.get("quiet_start") else None,
                quiet_end=time.fromisoformat(item["quiet_end"]) if item.get("quiet_end") else None,
                timezone=item.get("timezone", "Asia/Hong_Kong"),
                agent_push_enabled=item.get("agent_push_enabled", True),
                agent_digest_enabled=item.get("agent_digest_enabled", True),
            ))

    await db.commit()
    return {"status": "ok"}


# ─── HELPER ───────────────────────────────────────────────────
def _dump(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "user_id": str(n.user_id),
        "source_module": n.source_module,
        "source_record_type": n.source_record_type,
        "source_record_id": str(n.source_record_id) if n.source_record_id else None,
        "title": n.title,
        "body": n.body,
        "priority": n.priority,
        "is_ai_generated": n.is_ai_generated,
        "ai_rationale": n.ai_rationale,
        "ai_confidence": float(n.ai_confidence) if n.ai_confidence else None,
        "generated_by_agent_id": n.generated_by_agent_id,
        "status": n.status,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "action_url": n.action_url,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }

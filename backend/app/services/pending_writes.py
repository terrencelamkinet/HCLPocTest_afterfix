"""Short-lived staging cache for CRM writes — show-once → confirm → execute.

WHY THIS EXISTS (2026-09-10, operator decision)
-----------------------------------------------
The old mechanism persisted a ``nexus_ai.action_requests`` row with
``status='pending'`` for every prepared write and waited for a LATER turn to
confirm it. On a real tenant those rows accumulated (23 stale pending rows,
oldest 22h) and a stray 「確認」 could execute a long-forgotten draft. The
operator's final decision:

    「全取消，只要 create 前 show 一次會入的data 給的確認就可以了，
      apply to all tenants. Remove all 草稿」

So there is now NO persisted draft/pending entity. Each write is:

  1. PREPARE — the AI builds the exact record it would write and shows every
     field to the user (uncertain fields flagged in the preview). At this
     point the prepared payload is stashed in this SHORT-LIVED CACHE, keyed by
     an unguessable one-time token; **nothing is written to Postgres**.
  2. CONFIRM — the user confirms ONCE (UI button → /actions/{id}/confirm or
     /actions/batch-confirm). The token is consumed (one-time use) and the
     real record is written.
  3. The consumed token is gone; the cache entry self-expires (TTL) even if
     the user never confirms → nothing accumulates, no visible residue.

WHY A CACHE AND NOT THE CONVERSATION / MESSAGE HISTORY
------------------------------------------------------
The session message history was the natural alternative (Message.tool_calls
already exists as a JSONB column), but the write payload is produced by
``_run_model_tool_calls`` in an SSE generator whose teardown does not reliably
commit (that is exactly why the old code did an explicit ``db.commit()`` per
draft, and why RLS context has to be re-applied mid-generator). Routing the
payload through the message row would couple staging to commit ordering on
both ``/chat`` and ``/chat/stream`` and risk losing a payload the user was
already shown. A cache key is decoupled from all of that, works identically on
both endpoints, needs ZERO schema change, and expires on its own.

Redis is already a hard dependency of this app (OTP, session cache, quota,
dashboard cache) — this is not new infrastructure.

PROVENANCE (KB-011 invariant — unchanged)
-----------------------------------------
Staging a payload confers NO write authority. Every staged write still needs
the user's own ONE confirmation before the handler runs in ``execute`` mode.
A document / voice transcript / OCR / RAG text can never confirm itself.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.redis_service import get_redis

__all__ = [
    "stage_write",
    "load_write",
    "consume_write",
    "discard_write",
    "PENDING_WRITE_TTL",
    "KEY_PREFIX",
]

# 30 minutes is long enough for a user to read the shown payload and tap
# confirm, short enough that an abandoned preview self-destructs.
PENDING_WRITE_TTL = 1800

KEY_PREFIX = "nexus:ai:pending_write:"


def _key(token: str) -> str:
    return f"{KEY_PREFIX}{token}"


async def stage_write(
    *,
    tenant_id: Any,
    user_id: Any,
    tool_key: str,
    module: str | None,
    params: dict[str, Any],
    preview: dict[str, Any],
    session_id: Any = None,
    origin: str | None = None,
    origin_text: str | None = None,
    ttl: int = PENDING_WRITE_TTL,
) -> str:
    """Stash ONE prepared write and return its one-time confirmation token.

    Nothing is written to Postgres here.
    """
    token = uuid.uuid4().hex
    record = {
        "token": token,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "user_id": str(user_id) if user_id is not None else None,
        "session_id": str(session_id) if session_id is not None else None,
        "tool_key": tool_key,
        "module": module,
        "params": params or {},
        "preview": preview or {},
        "origin": origin,
        "origin_text": (origin_text or "")[:500] or None,
        "staged_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await get_redis()
    await r.setex(_key(token), ttl, json.dumps(record, default=str))
    return token


async def load_write(token: str, *, tenant_id: Any, user_id: Any) -> dict[str, Any] | None:
    """Read a staged write WITHOUT consuming it (inspection / debugging).

    Tenant + user must match, else None (fail closed).
    """
    try:
        r = await get_redis()
        raw = await r.get(_key(token))
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if str(data.get("tenant_id")) != str(tenant_id) or str(data.get("user_id")) != str(user_id):
        return None
    return data


async def consume_write(token: str, *, tenant_id: Any, user_id: Any) -> dict[str, Any] | None:
    """Atomically take a staged write (one-time use) — GETDEL.

    Returns None when the token is unknown, already used, expired, or belongs
    to a different tenant/user. Callers MUST treat None as "expired — ask
    again"; never as "write anyway".
    """
    key = _key(token)
    try:
        r = await get_redis()
        try:
            raw = await r.getdel(key)  # Redis >= 6.2 — atomic one-time use
        except Exception:
            raw = await r.get(key)
            if raw:
                await r.delete(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if str(data.get("tenant_id")) != str(tenant_id) or str(data.get("user_id")) != str(user_id):
        return None  # fail closed — already deleted, cannot be replayed
    return data


async def discard_write(token: str, *, tenant_id: Any, user_id: Any) -> bool:
    """Drop a staged write the user rejected (idempotent)."""
    try:
        r = await get_redis()
        raw = await r.get(_key(token))
        if not raw:
            return False
        data = json.loads(raw)
        if str(data.get("tenant_id")) != str(tenant_id) or str(data.get("user_id")) != str(user_id):
            return False
        await r.delete(_key(token))
        return True
    except Exception:
        return False

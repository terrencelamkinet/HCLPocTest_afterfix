"""Error monitoring（Critical）— 未處理錯誤 / 5xx 落地。

設計：
  - **middleware 捕捉**：任何 exception 或 status >= 500 都寫一筆
  - **自己短 session**：同 audit 一樣，唔可以影響正在失敗嘅請求
  - **唔記 body/headers**：只記路徑 + 類型 + message + traceback（截斷）
  - **best-effort**：記錄失敗絕不可以令請求再爆一次
  - 噪音過濾：/health、/metrics 之類唔記

用法（main.py）：
    from app.services.error_monitor import ErrorMonitorMiddleware
    app.add_middleware(ErrorMonitorMiddleware)
"""

from __future__ import annotations

import logging
import traceback as tb
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

SKIP_PATH_PREFIXES = ("/health", "/api/v1/ai/health", "/metrics", "/favicon")
MAX_FIELD = 4000


def _truncate(value: str | None, limit: int = MAX_FIELD) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "…[truncated]"


async def record_error(
    *,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    error_type: str | None = None,
    message: str | None = None,
    traceback_text: str | None = None,
    tenant_id: Any = None,
    user_id: Any = None,
    request_id: str | None = None,
) -> None:
    """寫一筆錯誤記錄（best-effort，永不 raise）。"""
    if path and any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
        return
    try:
        from app.db import async_session

        async with async_session() as db:
            if tenant_id is not None:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(tenant_id)},
                )
            await db.execute(
                text("""
                    INSERT INTO nexus_ai.error_events
                        (tenant_id, user_id, request_id, method, path, status_code,
                         error_type, message, traceback)
                    VALUES
                        (:t, :u, :rid, :m, :p, :sc, :et, :msg, :tb)
                """),
                {
                    "t": tenant_id,
                    "u": user_id,
                    "rid": request_id,
                    "m": (method or "")[:10],
                    "p": _truncate(path, 500),
                    "sc": status_code,
                    "et": _truncate(error_type, 200),
                    "msg": _truncate(message),
                    "tb": _truncate(traceback_text),
                },
            )
            await db.commit()
    except Exception:
        logger.exception("error_monitor: failed to record error (path=%s)", path)


def _context(scope: dict) -> tuple[Any, Any, str | None]:
    """由 ASGI scope 抽 tenant / user / request id（可能冇）。"""
    state = scope.get("state") or {}
    ctx = state.get("ai_context")
    tenant_id = getattr(ctx, "tenant_id", None) or state.get("tenant_id")
    user_id = getattr(ctx, "user_id", None) or state.get("user_id")
    request_id = None
    for name, value in (scope.get("headers") or []):
        if name == b"x-request-id":
            request_id = value.decode("latin-1")[:100]
            break
    return tenant_id, user_id, request_id


class ErrorMonitorMiddleware:
    """純 ASGI middleware（唔用 BaseHTTPMiddleware，避免影響 SSE streaming）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        status_holder = {"code": None}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            tenant_id, user_id, request_id = _context(scope)
            await record_error(
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=500,
                error_type=type(exc).__name__,
                message=str(exc),
                traceback_text="".join(tb.format_exception(type(exc), exc, exc.__traceback__)),
                tenant_id=tenant_id,
                user_id=user_id,
                request_id=request_id,
            )
            raise
        else:
            code = status_holder["code"]
            if code is not None and code >= 500:
                tenant_id, user_id, request_id = _context(scope)
                await record_error(
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status_code=code,
                    error_type="HTTPError",
                    message=f"HTTP {code}",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    request_id=request_id,
                )


async def list_errors(db, *, hours: int = 24, limit: int = 50) -> dict:
    """錯誤一覽（需要用 admin / BYPASSRLS session）。

    回傳：按路徑/類型聚合 + 最近 N 筆。
    """
    rows = (
        await db.execute(
            text("""
                SELECT date_trunc('hour', occurred_at) AS hour,
                       path, error_type, status_code, count(*) AS hits
                FROM nexus_ai.error_events
                WHERE occurred_at > now() - make_interval(hours => :h)
                GROUP BY 1, 2, 3, 4
                ORDER BY 1 DESC, 5 DESC
                LIMIT :lim
            """),
            {"h": hours, "lim": limit},
        )
    ).mappings().all()

    recent = (
        await db.execute(
            text("""
                SELECT occurred_at, method, path, status_code, error_type, message, tenant_id
                FROM nexus_ai.error_events
                WHERE occurred_at > now() - make_interval(hours => :h)
                ORDER BY occurred_at DESC
                LIMIT 20
            """),
            {"h": hours},
        )
    ).mappings().all()

    total = (
        await db.execute(
            text("""
                SELECT count(*) FROM nexus_ai.error_events
                WHERE occurred_at > now() - make_interval(hours => :h)
            """),
            {"h": hours},
        )
    ).scalar()

    return {
        "window_hours": hours,
        "total": int(total or 0),
        "by_hour_path": [dict(r) for r in rows],
        "recent": [
            {**{k: v for k, v in dict(r).items()}, "occurred_at": r["occurred_at"].isoformat()}
            for r in recent
        ],
    }


async def error_count_recent(db, *, minutes: int = 60) -> int:
    """最近 N 分鐘錯誤數（俾 cron 做告警閾值判斷）。"""
    value = (
        await db.execute(
            text("""
                SELECT count(*) FROM nexus_ai.error_events
                WHERE occurred_at > now() - make_interval(mins => :m)
            """),
            {"m": minutes},
        )
    ).scalar()
    return int(value or 0)

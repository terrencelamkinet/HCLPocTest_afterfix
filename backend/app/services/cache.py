"""Redis-backed short-TTL cache for hot, rarely-changing AI lookups.

Wraps Redis with hard safety guarantees so a cache problem can NEVER break a
chat request:

* **Graceful degradation** — every public call is wrapped in ``try/except`` and
  degrades to a cache miss / no-op. A down, unreachable, slow, or erroring
  Redis simply falls through to the existing DB query, exactly as before.
* **Bounded latency** — connect + socket timeouts default to 200ms
  (``NEXUS_CACHE_TIMEOUT_MS``, hard-capped at 200ms) so a hung Redis costs at
  most one short penalty instead of hanging the request.
* **Circuit breaker** — after the first failure the cache is skipped for a
  short cooldown window (``NEXUS_CACHE_COOLDOWN_SECONDS``, default 30s), so a
  dead Redis costs ~one 200ms penalty per window rather than one per request.
* **Log-once** — the first failure is logged at WARNING; subsequent failures
  are silent (no per-request log spam).

**Multi-tenant isolation** — every key is namespaced
``nxcache:<tenant_scope>:<kind>[:<name>]`` where ``tenant_scope`` is the
tenant_id (or ``global`` when none is given). A tenant can never read another
tenant's cached value.

Only small JSON-serialisable values belong here — never PII-heavy blobs.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from app.config import settings

log = logging.getLogger("app.services.cache")

# Hard cap on the connect/socket timeout, regardless of config.
_MAX_TIMEOUT_MS = 200.0

try:  # pragma: no cover - import guard keeps callers safe if redis is absent
    import redis.asyncio as _aioredis
    from redis.asyncio.connection import ConnectionPool as _ConnectionPool

    _REDIS_AVAILABLE = True
except Exception:  # pragma: no cover
    _aioredis = None
    _ConnectionPool = None
    _REDIS_AVAILABLE = False

_pool: Any = None
_client: Any = None

# Failure bookkeeping (module-level, process-wide).
_warned = False
_breaker_until = 0.0  # monotonic deadline; cache skipped while now < this


# ---------------------------------------------------------------------------
# Settings accessors (all optional — sane defaults, never raise)
# ---------------------------------------------------------------------------
def enabled() -> bool:
    return bool(getattr(settings, "cache_enabled", True)) and _REDIS_AVAILABLE


def ttl() -> int:
    try:
        value = int(getattr(settings, "cache_ttl_seconds", 60))
    except Exception:
        value = 60
    return value if value > 0 else 60


def _timeout_s() -> float:
    try:
        ms = float(getattr(settings, "cache_timeout_ms", 200))
    except Exception:
        ms = _MAX_TIMEOUT_MS
    ms = max(1.0, min(ms, _MAX_TIMEOUT_MS))
    return ms / 1000.0


def _cooldown_s() -> float:
    try:
        value = float(getattr(settings, "cache_cooldown_seconds", 30.0))
    except Exception:
        value = 30.0
    return value if value > 0 else 0.0


def _max_connections() -> int:
    try:
        value = int(getattr(settings, "cache_max_connections", 20))
    except Exception:
        value = 20
    return value if value > 0 else 20


# ---------------------------------------------------------------------------
# Key construction (tenant isolation lives here)
# ---------------------------------------------------------------------------
def _tenant_scope(tenant_id: Any) -> str:
    if tenant_id in (None, ""):
        return "global"
    return str(tenant_id)


def make_key(kind: str, tenant_id: Any = None, name: str = "") -> str:
    """Build a tenant-scoped cache key.

    ``nxcache:<tenant_scope>:<kind>[:<name>]`` — the tenant scope is always
    present so isolation is structural, not a caller convention.
    """
    parts = ["nxcache", _tenant_scope(tenant_id), str(kind)]
    if name:
        parts.append(str(name))
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------
def _note_failure(exc: BaseException) -> None:
    global _warned
    if _warned:
        return
    _warned = True
    log.warning(
        "cache: Redis unavailable — degrading to DB (%s: %s)",
        type(exc).__name__,
        exc,
    )


def _trip_breaker(exc: BaseException) -> None:
    """Open the breaker + log once. Skipped entirely while cooldown is 0."""
    global _breaker_until
    cooldown = _cooldown_s()
    if cooldown > 0:
        _breaker_until = time.monotonic() + cooldown
    _note_failure(exc)


def _breaker_open() -> bool:
    return time.monotonic() < _breaker_until


def _active() -> bool:
    return enabled() and not _breaker_open()


def _get_client() -> Any:
    global _pool, _client
    if _client is None:
        timeout_s = _timeout_s()
        _pool = _ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_s,
            socket_timeout=timeout_s,
            max_connections=_max_connections(),
        )
        _client = _aioredis.Redis(connection_pool=_pool)
    return _client


# ---------------------------------------------------------------------------
# Core operations — all never raise
# ---------------------------------------------------------------------------
async def get_json(key: str) -> Optional[Any]:
    """Return the decoded value, or ``None`` on miss / any failure."""
    if not _active():
        return None
    try:
        raw = await _get_client().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - must never propagate
        _trip_breaker(exc)
        return None


async def set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
    """Store a small JSON value. Returns ``True`` on write, ``False`` otherwise."""
    if not _active():
        return False
    try:
        t = int(ttl_seconds) if ttl_seconds is not None else ttl()
        if t <= 0:
            return False
        payload = json.dumps(value, default=str, separators=(",", ":"))
        await _get_client().setex(key, t, payload)
        return True
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(exc)
        return False


async def delete(*keys: str) -> int:
    """Best-effort delete. Returns number of keys removed (0 on any failure)."""
    if not _active() or not keys:
        return 0
    try:
        return int(await _get_client().delete(*keys))
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(exc)
        return 0


async def ping() -> bool:
    """Round-trip health probe (never raises)."""
    if not _active():
        return False
    try:
        return bool(await _get_client().ping())
    except Exception as exc:  # noqa: BLE001
        _trip_breaker(exc)
        return False


async def close() -> None:
    """Close the shared client/pool (best effort; safe if never used)."""
    global _pool, _client
    try:
        if _client is not None:
            await _client.aclose()
    except Exception:  # noqa: BLE001
        pass
    finally:
        _client = None
        _pool = None


def reset_breaker() -> None:
    """Testing/manual hook — clear the breaker so the next call retries Redis."""
    global _breaker_until, _warned
    _breaker_until = 0.0
    _warned = False

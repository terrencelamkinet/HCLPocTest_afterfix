"""
Redis-backed dashboard cache service for Penguin CRM.

Implements the Cache-Aside pattern:
  read through cache → miss → compute → store → return

Cache key pattern:  dash:{tenant_id}:{cache_key}

TTL tiers:
  - fast (60s)    — counts/lists that change frequently
  - medium (300s) — aggregates (sums, averages)
  - slow (1800s)  — historical data, reports
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Optional

from app.services.redis_service import get_redis


class DashboardCache:
    """Cache-Aside facade over Redis for CRM dashboard data."""

    # TTL tiers (seconds)
    TTL_FAST: int = 60          # counts, lists
    TTL_MEDIUM: int = 300       # aggregates
    TTL_SLOW: int = 1800        # historical

    __slots__ = ()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(tenant_id: str, cache_key: str) -> str:
        return f"dash:{tenant_id}:{cache_key}"

    @staticmethod
    def _make_pattern(tenant_id: str) -> str:
        return f"dash:{tenant_id}:*"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def get_or_compute(
        self,
        tenant_id: str,
        cache_key: str,
        ttl_seconds: int,
        compute_fn: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """Cache-Aside read: try cache first, compute on miss, store & return."""
        redis = await get_redis()
        key = self._make_key(tenant_id, cache_key)

        raw = await redis.get(key)
        if raw is not None:
            return json.loads(raw)

        value = await compute_fn()
        await redis.setex(key, ttl_seconds, json.dumps(value, default=str))
        return value

    async def set(
        self,
        tenant_id: str,
        cache_key: str,
        value: Any,
        ttl_seconds: int,
    ) -> None:
        """Write a value directly into the cache."""
        redis = await get_redis()
        key = self._make_key(tenant_id, cache_key)
        await redis.setex(key, ttl_seconds, json.dumps(value, default=str))

    async def get(
        self,
        tenant_id: str,
        cache_key: str,
    ) -> Optional[Any]:
        """Read from cache. Returns `None` on miss."""
        redis = await get_redis()
        key = self._make_key(tenant_id, cache_key)
        raw = await redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def invalidate(
        self,
        tenant_id: str,
        cache_key: Optional[str] = None,
    ) -> int:
        """
        Invalidate cached entries for a tenant.

        * If *cache_key* is provided → delete that single key.
        * If *cache_key* is ``None``    → SCAN for all ``dash:{tenant_id}:*``
          keys and delete them in bulk (atomic UNLINK).

        Returns the number of keys removed.
        """
        redis = await get_redis()

        if cache_key is not None:
            key = self._make_key(tenant_id, cache_key)
            removed = await redis.delete(key)
            return removed

        # Invalidate every key belonging to this tenant via SCAN + UNLINK.
        pattern = self._make_pattern(tenant_id)
        cursor = 0
        keys_to_delete: list[str] = []
        total_removed = 0

        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                keys_to_delete.extend(keys)
                if len(keys_to_delete) >= 500:
                    total_removed += await redis.unlink(*keys_to_delete)
                    keys_to_delete.clear()
            if cursor == 0:
                break

        if keys_to_delete:
            total_removed += await redis.unlink(*keys_to_delete)

        return total_removed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    async def close() -> None:
        """Close the underlying Redis connection if open."""
        redis = await get_redis()
        await redis.aclose()  # type: ignore[union-attr]


# Singleton convenience instance (reuses the shared redis connection)
dashboard_cache = DashboardCache()

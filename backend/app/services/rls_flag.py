"""RLS V2 feature-flag middleware.

Reads the RLS version from Redis per tenant and optionally enables
shadow logging when ``rls:version:{tenant_id} = v2_shadow``.

This middleware wraps ``get_tenant_session`` — it doesn't replace it.
"""

from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis

_redis: Optional[aioredis.Redis] = None


async def get_rls_version(tenant_id: str) -> str:
    """Return the active RLS version for *tenant_id*.

    Values
    ------
    ``"v1"`` (default)
        Old tenant-only policies.
    ``"v2_shadow"``
        V2 policies active in parallel — V2 violations are logged but
        V1 continues to grant access.
    ``"v2"``
        V2 policies enforced; V1 policies are dropped.

    The value is stored at Redis key ``rls:version:{tenant_id}``.
    If no value is set, returns ``"v1"``.
    """
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )

    raw = await _redis.get(f"rls:version:{tenant_id}")
    return raw if raw in ("v2_shadow", "v2") else "v1"


async def set_rls_version(tenant_id: str, version: str) -> None:
    """Set the RLS version for *tenant_id*."""
    if version not in ("v1", "v2_shadow", "v2"):
        raise ValueError(f"Invalid RLS version: {version}")

    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )

    if version == "v1":
        await _redis.delete(f"rls:version:{tenant_id}")
    else:
        await _redis.set(f"rls:version:{tenant_id}", version)


async def close_rls_client() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None

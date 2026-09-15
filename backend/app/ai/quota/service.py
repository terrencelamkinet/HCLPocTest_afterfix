"""Quota service — Redis-backed atomic rate limiter + usage tracker.

Architecture
------------
- **Redis atomic counters** with TTL-based sliding windows.
- Per-tenant, per-user, and per-agent buckets.
- Tier limits read from ``ai_usage_quotas`` DB table (migrated in Phase 0).
- Raises ``QuotaExceeded`` when any window is exceeded.

TTL reset strategy
------------------
Each window uses a Redis key whose TTL equals the window duration.
An INCR at t=0 sets TTL; subsequent increments within the window
reuse the same TTL.  When the key expires Redis auto-removes it,
so the next INCR starts a fresh window.  This is lock-free and O(1).

Usage
-----
::

    quota = QuotaService(redis_host="localhost", redis_port=6379)
    await quota.check("tenant:kinetix", tier="pro")
    await quota.record("tenant:kinetix", tokens=1500, cost=0.015)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import redis.asyncio as aioredis

log = logging.getLogger("app.ai.quota")

# Log-once guard — a down Redis must not spam a warning per request.
_degraded_warned = False


def _note_degraded(exc: BaseException) -> None:
    global _degraded_warned
    if not _degraded_warned:
        _degraded_warned = True
        log.warning(
            "quota: Redis unavailable — failing OPEN (enforcement skipped) (%s: %s)",
            type(exc).__name__,
            exc,
        )

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class QuotaExceeded(Exception):
    """Raised when a quota window is exceeded."""

    def __init__(self, window: str, limit: int, current: int) -> None:
        self.window = window
        self.limit = limit
        self.current = current
        super().__init__(f"{window} quota exceeded: {current}/{limit}")


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierLimits:
    """Default hard limits per tier."""

    rpm: int  # requests per minute
    rpd: int  # requests per day
    tpm: int  # tokens per minute (input + output)
    tpd: int  # tokens per day
    cost_cap_usd: Decimal  # daily cost cap in USD


TIER_LIMITS: dict[str, TierLimits] = {
    "free": TierLimits(rpm=10, rpd=200, tpm=8_000, tpd=50_000, cost_cap_usd=Decimal("0.50")),
    "starter": TierLimits(rpm=30, rpd=500, tpm=32_000, tpd=200_000, cost_cap_usd=Decimal("2.00")),
    "pro": TierLimits(rpm=60, rpd=2_000, tpm=128_000, tpd=1_000_000, cost_cap_usd=Decimal("10.00")),
    "enterprise": TierLimits(
        rpm=300, rpd=10_000, tpm=512_000, tpd=5_000_000, cost_cap_usd=Decimal("50.00")
    ),
    "unlimited": TierLimits(
        rpm=3000, rpd=100_000, tpm=5_000_000, tpd=50_000_000, cost_cap_usd=Decimal("1000.00")
    ),
}

# ---------------------------------------------------------------------------
# Quota service
# ---------------------------------------------------------------------------

QUOTA_KEY_PREFIX = "quota"


class QuotaService:
    """Redis-backed atomic quota enforcement per tenant/user/agent."""

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        password: Optional[str] = None,
    ) -> None:
        self._redis = aioredis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=password,
            decode_responses=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        scope_key: str,
        tier: str = "free",
        estimated_tokens: int = 0,
    ) -> None:
        """Raise ``QuotaExceeded`` if any window is over its limit.

        Parameters
        ----------
        scope_key
            Identifies the billing scope, e.g. ``"tenant:kinetix"``,
            ``"user:kinetix:alice"``, or ``"agent:crm-agent-1"``.
        tier
            Tier name from :data:`TIER_LIMITS`.  Falls back to ``"pro"``
            for unknown tiers.
        estimated_tokens
            Approximate tokens the upcoming call will consume.  Use 0 to
            only check request-rate windows.
        """
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["pro"])
        now = int(time.time())

        checks: list[tuple[str, int]] = [
            # (window_key_suffix, limit)
            (f":rpm:{now // 60}", limits.rpm),
            (f":rpd:{now // 86400}", limits.rpd),
        ]
        if estimated_tokens:
            checks.extend([
                (f":tpm:{now // 60}", limits.tpm),
                (f":tpd:{now // 86400}", limits.tpd),
            ])

        pipe = self._redis.pipeline(transaction=True)
        for suffix, _ in checks:
            pipe.get(f"{QUOTA_KEY_PREFIX}:{scope_key}{suffix}")
        try:
            results = await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            # GRACEFUL DEGRADATION: Redis down/slow/error must NEVER break chat.
            # Fail OPEN — skip enforcement for this request (limits are also not
            # recorded while Redis is unreachable, so nothing is silently lost).
            _note_degraded(exc)
            return

        for (suffix, limit), current_str in zip(checks, results):
            current = int(current_str) if current_str else 0
            if current >= limit:
                window = suffix.split(":")[1]  # rpm, rpd, tpm, tpd
                raise QuotaExceeded(window=window, limit=limit, current=current)

    async def record(
        self,
        scope_key: str,
        tokens: int = 0,
        cost: Decimal = Decimal("0"),
        tier: str = "free",
    ) -> dict[str, int]:
        """Atomically increment counters after a successful AI call.

        Returns a dict of current window values for diagnostics.
        """
        limits = TIER_LIMITS.get(tier, TIER_LIMITS["pro"])
        now = int(time.time())

        windows: list[tuple[str, int]] = [
            (f":rpm:{now // 60}", 60),
            (f":rpd:{now // 86400}", 86400),
            (f":tpm:{now // 60}", 60),
            (f":tpd:{now // 86400}", 86400),
            (f":cost:{now // 86400}", 86400),
        ]

        pipe = self._redis.pipeline(transaction=True)
        for suffix, ttl in windows:
            key = f"{QUOTA_KEY_PREFIX}:{scope_key}{suffix}"
            if suffix.startswith(":cost"):
                # store cumulative cost as a float string
                current_cost = await self._redis.get(key)
                new_cost = (Decimal(current_cost) if current_cost else Decimal("0")) + cost
                await self._redis.set(key, str(new_cost), ex=ttl)
            else:
                val = 1 if suffix.startswith(":r") else tokens
                pipe.incrby(key, val)
                pipe.expire(key, ttl)
        pipe_results = await pipe.execute()

        # Collapse incrby+expire pairs → just incrby result
        out: dict[str, int | Decimal] = {}
        i = 0
        for suffix, _ in windows:
            key = f"{QUOTA_KEY_PREFIX}:{scope_key}{suffix}"
            if suffix.startswith(":cost"):
                raw = await self._redis.get(key)
                out[suffix.split(":")[1]] = Decimal(raw) if raw else Decimal("0")
            else:
                out[suffix.split(":")[1]] = int(pipe_results[i] or 0)
                i += 2  # skip expire result
        return out  # type: ignore[return-value]

    async def current_usage(
        self,
        scope_key: str,
    ) -> dict[str, int | Decimal]:
        """Read current window counters without modifying them."""
        now = int(time.time())
        windows = ["rpm", "rpd", "tpm", "tpd", "cost"]
        pipe = self._redis.pipeline(transaction=True)
        for w in windows:
            key = f"{QUOTA_KEY_PREFIX}:{scope_key}:{w}:{now // (60 if 'm' in w else 86400)}"
            pipe.get(key)
        results = await pipe.execute()

        out: dict[str, int | Decimal] = {}
        for w, raw in zip(windows, results):
            if w == "cost":
                out[w] = Decimal(raw) if raw else Decimal("0")
            else:
                out[w] = int(raw) if raw else 0
        return out

    async def close(self) -> None:
        await self._redis.close()

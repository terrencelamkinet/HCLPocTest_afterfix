"""
Provider API key resolution — G08 獨立 API key 儲存（nexus_ai.provider_credentials）。

Keys are stored AES-256-GCM encrypted at rest (secret_crypto), tenant-scoped,
BYOK-enabled. This module is the single source of truth for provider keys:

  - async ``load_provider_key(provider, tenant_id)`` — decrypt from DB, cache
    (in-process + Redis), fall back to ``<PROVIDER>_API_KEY`` env.
  - sync ``cached_provider_key(provider)`` — read the in-process cache
    (populated by the async loader); safe for sync callers (e.g. namecard OCR)
    that run inside the same process after an async load happened.

Caching layers (all tenant-scoped — a tenant never sees another's key):
  1. in-process dict keyed by ``(tenant_scope, provider)`` — never expires,
     process-local.
  2. Redis short-TTL cache (``app.services.cache``) keyed by
     ``nxcache:<tenant_id>:provider_key:<provider>`` — shared across workers,
     ~60s TTL. Best-effort: if Redis is down/slow the call silently falls
     through to the DB (see cache.py).

Security: keys are decrypted in-process; the Redis layer (localhost-only) holds
the decrypted value for a short TTL. The DB remains the source of truth and the
env fallback preserves dev/self-hosted setups. Multi-tenant BYOK: when
tenant_id is given the lookup is scoped to that tenant; when omitted it takes
the newest active row (current deployments have a single provider key).
"""
from __future__ import annotations

import os

from app.services.secret_crypto import decrypt_secret

# (tenant_scope, provider) → decrypted key (memory-only cache, tenant-scoped)
_inproc: dict[tuple[str, str], str] = {}
# Legacy provider-only index: the most recently loaded key for a provider.
# Kept so sync callers without tenant context (``cached_provider_key``) behave
# exactly as before this change.
_legacy_by_provider: dict[str, str] = {}


def _scope(tenant_id) -> str:
    return str(tenant_id) if tenant_id not in (None, "") else "global"


def _remember(tenant_id, provider: str, key: str) -> None:
    _inproc[(_scope(tenant_id), provider)] = key
    _legacy_by_provider[provider] = key


def cached_provider_key(provider: str) -> str:
    """Sync read of the in-process cache (may be empty before async load)."""
    return _legacy_by_provider.get(provider, "")


async def load_provider_key(provider: str, tenant_id=None) -> str:
    """Load + decrypt a provider key from provider_credentials.

    Cache hits (in-process, then Redis) return immediately. Otherwise query the
    newest ACTIVE row (tenant-scoped when tenant_id given), decrypt, cache, and
    return. Falls back to ``<PROVIDER>_API_KEY`` env when the DB has no row.
    """
    cached = _inproc.get((_scope(tenant_id), provider))
    if cached:
        return cached

    # Shared Redis cache (best-effort — never raises, never blocks chat).
    from app.services import cache as _cache

    rkey = _cache.make_key("provider_key", tenant_id, provider)
    r_cached = await _cache.get_json(rkey)
    if isinstance(r_cached, dict):
        r_key = r_cached.get("key") or ""
        if r_key:
            _remember(tenant_id, provider, r_key)
            return r_key

    from sqlalchemy import select

    from app.db import async_session
    from app.models.ai.provider import ProviderCredential

    key = ""
    try:
        from sqlalchemy import text as _sa_text

        async with async_session() as db:
            # RLS: provider_credentials has FORCE RLS — set the tenant GUC
            # before querying, else 0 rows and callers silently fall back.
            if tenant_id is not None:
                await db.execute(
                    _sa_text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
            q = (
                select(ProviderCredential)
                .where(
                    ProviderCredential.provider == provider,
                    ProviderCredential.status == "active",
                )
                .order_by(ProviderCredential.created_at.desc())
            )
            if tenant_id is not None:
                q = q.where(ProviderCredential.tenant_id == tenant_id)
            row = (await db.execute(q.limit(1))).scalar_one_or_none()
            if row is not None and row.encrypted_api_key:
                key = decrypt_secret(row.encrypted_api_key)
    except Exception:
        key = ""  # never raise — callers fall back

    if key:
        _remember(tenant_id, provider, key)
        # Only positive DB results are cached (never the env fallback / a miss),
        # so a newly created row is never hidden for more than the TTL.
        await _cache.set_json(rkey, {"key": key})
        return key
    return os.environ.get(f"{provider.upper()}_API_KEY", "")

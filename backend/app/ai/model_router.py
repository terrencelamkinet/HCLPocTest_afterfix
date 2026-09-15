"""Model router — per-tenant model profile resolution + failover.

The enabled row in ``nexus_ai.model_profiles`` controls which provider/model
serves chat. Resolution order:

  1. An enabled profile (prefer ``profile_key = 'default'``) → use its
     ``primary_provider`` / ``primary_model``.
  2. No enabled profile (or a lookup error) → historical hard-coded default
     (deepseek / deepseek-chat). Chat behaviour is then EXACTLY as before.

Failover: if the primary provider/model raises (error, auth failure, timeout),
the call is retried ONCE on ``fallback_provider`` / ``fallback_model`` when set.
The failover is recorded as a ``nexus_ai.usage_events`` row (module
``chat_failover``) plus a warning log, so it is auditable.

Design notes
------------
* ``nexus_ai.model_profiles`` has RLS disabled, but we still wrap the read in a
  SAVEPOINT so a failure can never abort the request transaction (which would
  wipe the transaction-local ``app.tenant_id`` GUC the app relies on).
* No new infrastructure — the adapters are in-process; the timeout uses
  ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import get_provider

log = logging.getLogger("app.ai.model_router")

# Historical server defaults — used when no enabled profile exists.
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-chat"

# Per-attempt ceilings. A hung primary must not hang the request forever —
# we fail over instead.
PRIMARY_TIMEOUT_S = 60.0
FALLBACK_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class ModelSelection:
    """Resolved model profile for a single chat request."""

    provider: str
    model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    profile_key: Optional[str] = None

    @property
    def has_fallback(self) -> bool:
        return bool(self.fallback_provider and self.fallback_model)

    def describe(self) -> str:
        base = f"{self.provider}/{self.model}"
        if self.has_fallback:
            base += f" (fallback {self.fallback_provider}/{self.fallback_model})"
        return base


async def resolve_model_selection(
    db: AsyncSession,
    tenant_id: Any = None,
) -> ModelSelection:
    """Resolve the enabled per-tenant model profile.

    Always returns a usable selection — on any failure (missing table, DB
    hiccup, disabled profile) it degrades to the historical defaults so chat
    never breaks because of profile resolution.

    Backed by a short-TTL Redis cache (``app.services.cache``) so a large
    deployment does not SELECT ``nexus_ai.model_profiles`` on every request.
    The cache is tenant-scoped and best-effort: if Redis is unavailable the DB
    query below runs exactly as before.
    """
    from app.services import cache as _cache

    ckey = _cache.make_key("model_profile", tenant_id)
    cached = await _cache.get_json(ckey)
    if isinstance(cached, dict) and cached.get("provider") and cached.get("model"):
        log.debug("model profile cache hit: tenant=%s key=%s", tenant_id, cached.get("profile_key"))
        return _selection_from_payload(cached)

    row = None
    try:
        # SAVEPOINT: a failed read rolls back to here, leaving the outer
        # transaction (and its app.tenant_id GUC) intact.
        async with db.begin_nested():
            res = await db.execute(
                text(
                    """
                    SELECT profile_key, primary_provider, primary_model,
                           fallback_provider, fallback_model
                    FROM nexus_ai.model_profiles
                    WHERE is_enabled IS TRUE
                    ORDER BY (profile_key = 'default') DESC, profile_key
                    LIMIT 1
                    """
                )
            )
            row = res.first()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("model profile lookup failed, using defaults: %s", exc)
        row = None

    if not row:
        sel = ModelSelection(DEFAULT_PROVIDER, DEFAULT_MODEL)
        # TTL-bounded (default ~60s) so a newly enabled profile surfaces fast.
        await _cache.set_json(ckey, _selection_to_payload(sel))
        return sel

    provider = (row[1] or "").strip() or DEFAULT_PROVIDER
    model = (row[2] or "").strip() or DEFAULT_MODEL
    fb_provider = (row[3] or "").strip() or None
    fb_model = (row[4] or "").strip() or None
    sel = ModelSelection(
        provider=provider,
        model=model,
        fallback_provider=fb_provider,
        fallback_model=fb_model,
        profile_key=row[0],
    )
    # 2026-09-15 SAST：每 request 打 profile 細節係噪音（AppScan: log leakage）→ debug
    log.debug("model profile resolved: key=%s → %s", sel.profile_key, sel.describe())
    await _cache.set_json(ckey, _selection_to_payload(sel))
    return sel


def _selection_to_payload(sel: ModelSelection) -> dict[str, Any]:
    """Small JSON-serialisable form for the cache."""
    return {
        "provider": sel.provider,
        "model": sel.model,
        "fallback_provider": sel.fallback_provider,
        "fallback_model": sel.fallback_model,
        "profile_key": sel.profile_key,
    }


def _selection_from_payload(data: dict[str, Any]) -> ModelSelection:
    return ModelSelection(
        provider=str(data.get("provider") or DEFAULT_PROVIDER),
        model=str(data.get("model") or DEFAULT_MODEL),
        fallback_provider=data.get("fallback_provider") or None,
        fallback_model=data.get("fallback_model") or None,
        profile_key=data.get("profile_key") or None,
    )


async def _attempt_with_adapter(
    adapter: Any,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    tools: Optional[list[dict[str, Any]]],
    timeout_s: float,
) -> tuple[str, list[dict[str, Any]], Any]:
    """One non-streaming attempt against a single adapter/model."""
    if tools and hasattr(adapter, "chat_with_tools"):
        text_out, tool_calls, usage = await asyncio.wait_for(
            adapter.chat_with_tools(
                messages=messages, model=model,
                temperature=temperature, max_tokens=max_tokens, tools=tools,
            ),
            timeout=timeout_s,
        )
        return text_out, tool_calls or [], usage

    text_out, usage = await asyncio.wait_for(
        adapter.chat(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens,
        ),
        timeout=timeout_s,
    )
    return text_out, [], usage


async def record_failover(
    db: AsyncSession,
    ctx: Any,
    session_id: Any,
    selection: ModelSelection,
    exc: Exception,
) -> None:
    """Record that the primary failed and we degraded to the fallback.

    Best-effort: never let auditing break the chat request. Sets the tenant
    GUC itself (a mid-request commit may have wiped it).
    """
    log.warning(
        "primary model FAILED (%s/%s): %s — failing over to %s/%s",
        selection.provider, selection.model, exc,
        selection.fallback_provider, selection.fallback_model,
    )
    try:
        await db.execute(
            text(
                "SELECT set_config('app.tenant_id', :t, true), "
                "set_config('app.user_id', :u, true)"
            ),
            {"t": str(ctx.tenant_id), "u": str(ctx.user_id)},
        )
    except Exception:
        pass
    try:
        from app.models.ai import UsageEvent

        db.add(
            UsageEvent(
                session_id=session_id,
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                provider=selection.provider,
                model=selection.model,
                input_tokens=0,
                output_tokens=0,
                result_status="error",
                module="chat_failover",
                currency="USD",
            )
        )
    except Exception:
        pass


async def chat_with_fallback(
    db: AsyncSession,
    ctx: Any,
    session_id: Any,
    *,
    selection: ModelSelection,
    primary_adapter: Any,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    tools: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, list[dict[str, Any]], Any, bool]:
    """Run a chat call, trying the primary then ONCE on the fallback.

    Returns ``(text, tool_calls, usage_report, used_fallback)``. If both
    attempts fail the *primary* exception is re-raised so the caller's error
    handling (quota refund etc.) is unchanged.
    """
    try:
        text_out, tool_calls, usage = await _attempt_with_adapter(
            primary_adapter, selection.model, messages,
            temperature, max_tokens, tools, PRIMARY_TIMEOUT_S,
        )
        return text_out, tool_calls, usage, False
    except Exception as primary_exc:
        if not selection.has_fallback:
            raise

        await record_failover(db, ctx, session_id, selection, primary_exc)

        try:
            fb_adapter = get_provider(
                selection.fallback_provider,
                default_model=selection.fallback_model,
            )
        except Exception as build_exc:
            log.error("fallback provider %s unavailable: %s",
                      selection.fallback_provider, build_exc)
            raise primary_exc

        try:
            text_out, tool_calls, usage = await _attempt_with_adapter(
                fb_adapter, selection.fallback_model, messages,
                temperature, max_tokens, tools, FALLBACK_TIMEOUT_S,
            )
            return text_out, tool_calls, usage, True
        except Exception as fallback_exc:
            log.error("fallback model also failed: %s", fallback_exc)
            raise primary_exc
        finally:
            try:
                await fb_adapter.close()
            except Exception:
                pass

"""
Authorization guard for AI tool calls.

Validates that the calling agent is permitted to invoke a specific tool
and that all parameter-scoped IDs belong to the same tenant / workspace.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.session.context import AISessionContext
from app.ai.tool_registry import TOOL_REGISTRY
from app.models.crm_module_b import ModuleSetting


# ---------------------------------------------------------------------------
# Tenant AI edit permission (module_settings.ai.allow_edit)
# ---------------------------------------------------------------------------


async def _ai_edit_allowed(tenant_id: uuid.UUID, db: AsyncSession | None) -> bool:
    """Return True when the tenant has enabled AI editing (module_settings 'ai'.allow_edit).

    Falls back to the shared async session when no session is passed in.
    """
    if db is not None:
        result = await db.execute(
            select(ModuleSetting).where(
                ModuleSetting.tenant_id == tenant_id,
                ModuleSetting.module_key == "ai",
            )
        )
        obj = result.scalar_one_or_none()
        return bool(obj and (obj.settings or {}).get("allow_edit"))

    from app.db import async_session

    try:
        async with async_session() as s:
            result = await s.execute(
                select(ModuleSetting).where(
                    ModuleSetting.tenant_id == tenant_id,
                    ModuleSetting.module_key == "ai",
                )
            )
            obj = result.scalar_one_or_none()
            return bool(obj and (obj.settings or {}).get("allow_edit"))
    except Exception:
        return False


async def _agent_tool_allowed(
    agent_id: uuid.UUID,
    tool_key: str,
    tool_def: Any,
    db: AsyncSession | None,
) -> bool:
    """Return True when *agent_id* has a grant covering *tool_key* in ai_agent_permissions.

    A grant row matches when:
      - allowed_tool_key == tool_key (exact tool grant) OR '*' (module-level), AND
      - allowed_module == tool.module (exact) OR is a parent prefix of it
        (e.g. 'app.services.crm' covers 'app.services.crm.companies'), AND
      - can_read=True for read tools / can_write=True for write tools.
    Falls back to the shared async session when no session is passed in;
    DB errors return False-safe (caller falls through to remaining checks).
    """
    from sqlalchemy import text

    q = text(
        """
        SELECT can_read, can_write FROM nexus_ai.ai_agent_permissions
        WHERE agent_id = :aid
          AND (allowed_tool_key = :tk OR allowed_tool_key = '*')
          AND (:mod = allowed_module OR :mod LIKE allowed_module || '.%')
        """
    )

    async def _check(session: AsyncSession) -> bool:
        res = await session.execute(
            q, {"aid": str(agent_id), "tk": tool_key, "mod": tool_def.module}
        )
        for can_read, can_write in res.all():
            if tool_def.type == "read" and can_read:
                return True
            if tool_def.type == "write" and can_write:
                return True
        return False

    if db is not None:
        return await _check(db)

    from app.db import async_session

    try:
        async with async_session() as s:
            return await _check(s)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ScopeViolation(Exception):
    """Raised when an AI tool call violates tenant / workspace / permission scope."""

    def __init__(
        self,
        message: str,
        tool_key: str,
        reason: str,
        context: AISessionContext | None = None,
    ) -> None:
        self.tool_key = tool_key
        self.reason = reason
        self.context = context
        super().__init__(f"[{tool_key}] {message} (reason: {reason})")


# ---------------------------------------------------------------------------
# Authorisation logic
# ---------------------------------------------------------------------------

_KNOWN_ID_KEYS: set[str] = {
    "company_id",
    "contact_id",
    "project_id",
    "task_id",
    "deal_id",
    "touchpoint_id",
    "workspace_id",
    "tenant_id",
    "team_id",
    "user_id",
    "assignee_id",
    "owner_id",
    "membership_id",
    "agent_id",
    "session_id",
    "model_profile_id",
    "event_id",
    "provider_id",
    "credential_id",
}

# Data IDs that must resolve to a record inside the caller's tenant.
# Verified via RLS-scoped SELECT (rows outside the tenant are invisible),
# so a mismatch means the ID does not belong to this tenant.
_DATA_ID_TABLE_MAP: dict[str, str] = {
    "contact_id": "nexus_crm.contacts",
    "company_id": "nexus_crm.companies",
    "project_id": "nexus_crm.projects",
    "task_id": "nexus_crm.tasks",
    "deal_id": "nexus_crm.deals",
    "touchpoint_id": "nexus_crm.touchpoints",
    "namecard_id": "nexus_crm.name_cards",
}


def _extract_ids(params: dict[str, Any]) -> list[str]:
    """Extract all UUID-looking string values from *params* that match known ID keys."""
    ids: list[str] = []
    for key, value in params.items():
        if key in _KNOWN_ID_KEYS and isinstance(value, str):
            try:
                uuid.UUID(value)  # validate it's a real UUID
                ids.append(value)
            except ValueError:
                pass
        elif key in _KNOWN_ID_KEYS and isinstance(value, uuid.UUID):
            ids.append(str(value))
    return ids


async def _verify_data_ids_in_tenant(
    ctx: AISessionContext,
    tool_key: str,
    params: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Write-tool data-ID verification (network security).

    Every data ID in *params* (contact_id / company_id / project_id / …) must
    resolve to a record inside the caller's tenant. The SELECT runs under the
    request's RLS session (app.tenant_id set), so rows from other tenants are
    invisible — a miss means the ID does not belong to this tenant. Rejects
    cross-tenant writes before any draft/execute work happens.
    """
    from sqlalchemy import text

    for key, table in _DATA_ID_TABLE_MAP.items():
        raw = params.get(key)
        if raw is None:
            continue
        try:
            uuid.UUID(str(raw))
        except (ValueError, TypeError):
            continue  # non-UUID garbage → tool handler validation will catch
        try:
            result = await db.execute(
                text(f"SELECT 1 FROM {table} WHERE id = :rid"), {"rid": str(raw)}
            )
            if result.first() is None:
                raise ScopeViolation(
                    f"{key} {raw} does not exist in this tenant",
                    tool_key=tool_key,
                    reason="cross_tenant_data",
                    context=ctx,
                )
        except ScopeViolation:
            raise
        except Exception:
            pass  # table/query error → let RLS + tool handler decide


async def authorize_tool_call(
    ctx: AISessionContext,
    tool_key: str,
    params: dict[str, Any],
    db: AsyncSession | None = None,
) -> None:
    """Check that *ctx* is allowed to invoke *tool_key* with *params*.

    Validation steps (in order):
      1. Tool exists in registry
      2. Agent has a matching permission (``ai:tool:<tool_key>``)
      2.5. Write tools require tenant AI editing enabled (allow_edit)
      3. Cross-tenant check on any ID in *params*
      4. Cross-workspace check on any ID in *params*

    Raises ``ScopeViolation`` on the first failure.
    """
    # 1. Tool existence ------------------------------------------------------
    tool_def = TOOL_REGISTRY.get(tool_key)
    if tool_def is None:
        raise ScopeViolation(
            f"Unknown tool '{tool_key}'",
            tool_key=tool_key,
            reason="unknown_tool",
            context=ctx,
        )

    # 1.5. System-boundary check ---------------------------------------------
    # Principle: tenants may CRUD their own content (CRM data); the system
    # framework/content (config, settings, credentials, platform tables) must
    # never be modified by AI. AI tools may only target the tenant content
    # layer (app.services.crm.*) — anything outside it is out of bounds, even
    # if a future tool lands in TOOL_REGISTRY by mistake.
    if not tool_def.module.startswith("app.services.crm"):
        raise ScopeViolation(
            f"Tool '{tool_key}' targets system module '{tool_def.module}' — out of bounds",
            tool_key=tool_key,
            reason="system_module_out_of_bounds",
            context=ctx,
        )

    # 2. Agent permission ----------------------------------------------------
    # Agent-scoped check: when the session is bound to an agent (ai_agents),
    # the call must match a grant row in nexus_ai.ai_agent_permissions:
    #   - allowed_tool_key == tool_key (exact) OR '*' (module-level grant)
    #   - module match: allowed_module == tool.module OR is a parent prefix
    #   - read tools require can_read=True; write tools require can_write=True
    # No agent_id → user-direct session: rely on the tenant / workspace /
    # allow_edit / data-ID checks below (agent binding not yet wired).
    if ctx.agent_id is not None:
        if not await _agent_tool_allowed(ctx.agent_id, tool_key, tool_def, db):
            raise ScopeViolation(
                f"Agent {ctx.agent_id} is not allowed to call '{tool_key}'",
                tool_key=tool_key,
                reason="agent_permission_denied",
                context=ctx,
            )

    # 2.5. Write-tool gate — tenant must enable AI editing -------------------
    if tool_def.type == "write":
        if not await _ai_edit_allowed(ctx.tenant_id, db):
            raise ScopeViolation(
                "AI editing is disabled. Enable 'Allow AI to edit' in AI Apps settings.",
                tool_key=tool_key,
                reason="ai_edit_disabled",
                context=ctx,
            )

    # 3. Cross-tenant check --------------------------------------------------
    extracted_ids = _extract_ids(params)
    # In a real system this would query a tenant_scoped_ids table.
    # For now we short-circuit: any tenant_id param must match ctx.tenant_id.
    raw_tenant = params.get("tenant_id")
    if raw_tenant is not None:
        if str(raw_tenant) != str(ctx.tenant_id):
            raise ScopeViolation(
                f"tenant_id mismatch: param={raw_tenant} != ctx={ctx.tenant_id}",
                tool_key=tool_key,
                reason="cross_tenant",
                context=ctx,
            )

    # 4. Cross-workspace check -----------------------------------------------
    raw_workspace = params.get("workspace_id")
    if raw_workspace is not None:
        if str(raw_workspace) != str(ctx.workspace_id):
            raise ScopeViolation(
                f"workspace_id mismatch: param={raw_workspace} != ctx={ctx.workspace_id}",
                tool_key=tool_key,
                reason="cross_workspace",
                context=ctx,
            )

    # 5. Data-ID tenant verification (write tools only — network security)
    #    contact_id / company_id / project_id / … must resolve inside the
    #    caller's tenant; cross-tenant writes are rejected before execution.
    if tool_def.type == "write" and db is not None:
        await _verify_data_ids_in_tenant(ctx, tool_key, params, db)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


async def log_audit(
    ctx: AISessionContext,
    event_type: str,
    detail: dict[str, Any] | str = "",
) -> None:
    """Write an audit event to the database.  Silently skips if table missing."""
    try:
        import json

        from app.db import async_session
        from sqlalchemy import text

        det = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)

        async with async_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO nexus_ai.ai_audit_log
                        (tenant_id, user_id, session_id, event_type, detail)
                    VALUES (:tid, :uid, :sid, :evt, CAST(:det AS jsonb))
                    """
                ),
                {
                    "tid": str(ctx.tenant_id),
                    "uid": str(ctx.user_id),
                    "sid": str(ctx.session_id),
                    "evt": event_type,
                    "det": det,
                },
            )
            await db.commit()
    except Exception:
        pass  # table may not exist yet

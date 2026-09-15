"""Admin console DB layer — 2026-09-09.

- Independent async engine connecting as nexus_admin (BYPASSRLS role, direct 5432).
  NEVER shares the main gg_fighter pool: RLS sessions must not leak cross-tenant.
- require_superadmin: allowlist (JWT email) + DB role check (defence in depth).
- Router file: routers/admin.py  |  Spec: docs/admin-complete-spec.md
"""
from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_admin_engine = None
_admin_sessionmaker = None


def _get_admin_sessionmaker() -> async_sessionmaker:
    global _admin_engine, _admin_sessionmaker
    if _admin_sessionmaker is None:
        if not settings.nexus_admin_database_url:
            raise RuntimeError("NEXUS_ADMIN_DATABASE_URL not configured — admin console disabled")
        _admin_engine = create_async_engine(
            settings.nexus_admin_database_url,
            echo=False,
            # asyncpg prepared-statement cache fix — same as app/db.py root fix
            connect_args={"prepared_statement_cache_size": 0},
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=5,
            pool_recycle=1800,
        )
        _admin_sessionmaker = async_sessionmaker(_admin_engine, class_=AsyncSession, expire_on_commit=False)
    return _admin_sessionmaker


def _jwt_email(request: Request) -> str:
    """Read email claim straight from the bearer JWT (middleware only sets ids)."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        from app.services.auth_service import decode_token
        payload = decode_token(auth.split(" ", 1)[1].strip()) or {}
    except Exception:
        payload = {}
    email = payload.get("email", "")
    if not email:
        raise HTTPException(401, "Invalid token")
    return email


async def require_superadmin(request: Request) -> str:
    """Allowlist by email (config, comma-separated) + DB role check (nexus_auth_users.role == 'admin')."""
    email = _jwt_email(request)
    allowlist = [e.strip() for e in (settings.nexus_admin_emails or "").split(",") if e.strip()]
    if allowlist and email not in allowlist:
        raise HTTPException(403, "Admin only")
    # DB double-check — role from DB (JWT role can be stale)
    try:
        async with _get_admin_sessionmaker()() as s:
            row = (
                await s.execute(
                    text("SELECT role FROM nexus_auth.nexus_auth_users WHERE email = :em"),
                    {"em": email},
                )
            ).first()
            if not row or row.role != "admin":
                raise HTTPException(403, "Admin role required")
    except HTTPException:
        raise
    except Exception:
        # DB unavailable — allowlist alone still gates (don't hard-fail on DB hiccup)
        pass
    return email


async def get_admin_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — RLS-bypass session (nexus_admin role). Admin paths only."""
    await require_superadmin(request)
    sm = _get_admin_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

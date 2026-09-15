from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    # 2026-09-11: echo=settings.debug（debug=True）令 sqlalchemy.engine 逐條 SQL
    # log 一行 → journal 洪水（2 分鐘 ~10k 行，grep 都 time out）。SQL echo 唔係
    # 產品需要嘅嘢，永久關掉；app 自己嘅 INFO log 不受影響（見 main.py）。
    echo=False,
    # Root fix for asyncpg prepared-statement cache type-collision bug
    # ("invalid input syntax for type uuid: \"\"") — disables server-side
    # statement caching entirely. Each execution re-prepares with correct
    # param types. Negligible overhead vs. correctness at 50k scale.
    connect_args={"prepared_statement_cache_size": 0},
    pool_pre_ping=True,          # drop stale pooled connections (pg restart / pgbouncer)
    pool_size=10,                # per-process pool — with N workers × PgBouncer this
    max_overflow=20,             # stays well within PgBouncer's server pool
    pool_recycle=1800,           # 30min recycle — avoids long-idle conn kill
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

import logging

logger = logging.getLogger(__name__)


async def get_db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            tid = request.state.tenant_id
            uid = request.state.user_id
            wid = getattr(request.state, "workspace_id", "")
            tids = getattr(request.state, "team_ids", "")

            if tid:
                # 2026-09-07 T4 defence（Terrence: 「不要再錯和遺失數據」）:
                # tenant 重建/刪除後，舊 JWT 嘅 tenant_id claim 指向空 tenant → RLS 靜默 0 data
                # （Caleb 案例: 6c5843c2-2f0f → b51d — 舊 token 令成個 CRM 對用戶「冇數據」）。
                # 明確 reject（401）好過靜默遺失 — 用戶重新登入即攞到新 tenant。
                try:
                    t_exists = (
                        await session.execute(
                            text("SELECT 1 FROM nexus_auth.nexus_auth_tenants WHERE id = :tid"),
                            {"tid": str(tid)},
                        )
                    ).first()
                    if not t_exists:
                        raise HTTPException(
                            status_code=401,
                            detail="Session tenant no longer exists — please sign in again",
                        )
                except HTTPException:
                    raise
                except Exception:
                    pass  # DB hiccup — 唔好為咗 check 整死正常 request
                conn = await session.connection()
                # transaction-scoped set_config (3rd arg=true): 
                # ensures no cross-tenant leak when conn returns to pool
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tid)},
                )
                if uid:
                    await conn.execute(
                        text("SELECT set_config('app.user_id', :uid, true)"),
                        {"uid": str(uid)},
                    )
                # Resolve workspace_id if middleware didn't already provide one
                if not wid:
                    wid_row = await conn.execute(
                        text(
                            """
                            SELECT id FROM nexus_auth.workspaces
                            WHERE tenant_id = :tid
                            ORDER BY created_at ASC
                            LIMIT 1
                            """
                        ),
                        {"tid": str(tid)},
                    )
                    wid = wid_row.scalar_one_or_none()
                    if not wid:
                        # 2026-09-11 fix（用戶回報：公司／任務建立 HTTP 500）：
                        # tenant 冇任何 workspace row → wid 一路係 None →
                        # request.state.workspace_id 冇 set → 所有「需要 workspace_id
                        # (NOT NULL)」嘅寫入（companies / contacts / tasks / projects /
                        # notes）撞 NotNullViolationError → 500。
                        # ⚠️ GET 唔需要 workspace_id，所以 app 表面完全正常，只有「建立」死，
                        # 極難察覺（實測有 36+ 個 tenant 中招）。
                        # 表本身有 is_system_generated / workspace_type='default' 設計，
                        # 就係為咗呢種情況 → 補一個 system-generated Default Workspace。
                        # 遷移 021 已 backfill 現有 tenant + GRANT INSERT 俾 nexus_admin。
                        try:
                            ins = await conn.execute(
                                text(
                                    """
                                    INSERT INTO nexus_auth.workspaces
                                        (tenant_id, name, is_system_generated)
                                    VALUES (:tid, 'Default Workspace', true)
                                    RETURNING id
                                    """
                                ),
                                {"tid": str(tid)},
                            )
                            wid = ins.scalar_one_or_none()
                            logger.warning(
                                "tenant %s had no workspace — created Default Workspace %s "
                                "(writes would otherwise 500 on NOT NULL workspace_id)",
                                tid, wid,
                            )
                        except Exception as exc:  # 權限／競態 → 唔好連 GET 都整死
                            logger.error("cannot bootstrap workspace for tenant %s: %s", tid, exc)
                    if wid:
                        request.state.workspace_id = wid
                if wid:
                    await conn.execute(
                        text("SELECT set_config('app.workspace_id', :wid, true)"),
                        {"wid": str(wid)},
                    )
                if tids:
                    await conn.execute(
                        text("SELECT set_config('app.team_ids', :tids, true)"),
                        {"tids": str(tids)},
                    )
                # Set single team_id from first team (or default) for RLS V2 team-scope checks
                if tids:
                    first_team = str(tids).split(",")[0].strip().strip("['").strip("']")
                    if first_team:
                        await conn.execute(
                            text("SELECT set_config('app.team_id', :tid, true)"),
                            {"tid": first_team},
                       )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

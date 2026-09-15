import asyncio
from app.db import engine, async_session
from app.models import Tenant, TenantMember, User
from sqlalchemy import select

async def setup():
    tid = "00000000-0000-0000-0000-000000000001"
    async with async_session() as session:
        # Create tenant using ORM
        r = await session.execute(select(Tenant).where(Tenant.id == tid))
        tenant = r.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(
                id=tid,
                name="Kinetix",
                subdomain="kinetix",
                settings={}
            )
            session.add(tenant)
            await session.flush()
            print("Tenant: Kinetix")
        else:
            print("Tenant exists")

        # Create membership
        r = await session.execute(select(User).where(User.email == "terrence_lam@kinetix.com.hk"))
        user = r.scalar_one_or_none()
        if user:
            r2 = await session.execute(
                select(TenantMember).where(
                    TenantMember.user_id == user.id,
                    TenantMember.tenant_id == tid
                )
            )
            if not r2.scalar_one_or_none():
                tm = TenantMember(user_id=user.id, tenant_id=tid, role="admin")
                session.add(tm)
                await session.flush()
                print("Membership created")
        
        await session.commit()
        print("Setup complete")
    await engine.dispose()

asyncio.run(setup())

#!/usr/bin/env python3
"""G08 RLS hardening — Phase D: add WITH CHECK to every policy missing it.
Detects qual style (::uuid cast vs ::text) and mirrors it in WITH CHECK.
Run as postgres superuser. Idempotent.
"""
import asyncio
import sys

from sqlalchemy import text
from app.db import async_session


async def main() -> None:
    async with async_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT tablename, policyname, qual "
                    "FROM pg_policies WHERE schemaname='nexus_crm' "
                    "AND with_check IS NULL ORDER BY tablename"
                )
            )
        ).fetchall()
        print(f"policies missing WITH CHECK: {len(rows)}")
        done = 0
        for tablename, policyname, qual in rows:
            qual = qual or ""
            if "::uuid" in qual:
                check_expr = "(tenant_id = (current_setting('app.tenant_id'::text, true))::uuid)"
            else:
                check_expr = "(tenant_id::text = current_setting('app.tenant_id'::text, true))"
            sql = (
                f"ALTER POLICY {policyname} ON nexus_crm.{tablename} "
                f"WITH CHECK ({check_expr})"
            )
            try:
                await s.execute(text(sql))
                done += 1
                print(f"  + {tablename}.{policyname}")
            except Exception as e:  # noqa: BLE001
                print(f"  ! {tablename}.{policyname}: {str(e)[:120]}")
        await s.commit()
        print(f"✅ WITH CHECK added to {done} policies")


asyncio.run(main())

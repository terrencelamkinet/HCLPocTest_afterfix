#!/usr/bin/env python3
"""G08 RLS hardening migration — Phase 1: nexus_crm tenant data tables.
Run as postgres superuser (bypasses RLS for DDL). Idempotent.
"""
import asyncio
import sys

from sqlalchemy import text
from app.db import async_session

# B 類: tenant data tables missing RLS (bootstrap tables EXCLUDED — see KB)
TENANT_DATA_TABLES = [
    "ai_agent_log",
    "dashboard_layouts",
    "departments",
    "im_delivery_prefs",
    "module_settings",
    "namecard_tags",
    "nexus_integrations",
    "notification_preferences",
    "notifications",
    "push_log",
    "roles",
    "task_categories",
    "task_lists",
    "teams",
    "tenant_module_settings",
    "touchpoint_participants",
    "user_field_options",
]

# C 類: RLS enabled but 0 policies → silent deny (quotations HAS data = active bug)
SILENT_DENY_TABLES = [
    "ai_enrichment_jobs_legacy",
    "ai_forecasts_legacy",
    "ai_meeting_briefs_legacy",
    "ai_recommendations_legacy",
    "ai_relationship_scores_legacy",
    "credit_control_rules",
    "department_targets",
    "dispatch_queue",
    "dispatch_rules",
    "quotations",
    "rate_requests",
    "shipments",
    "stakeholder_maps",
    "trade_lanes",
    "user_targets",
    "workflow_apps",
]

POLICY_TMPL = """
CREATE POLICY tenant_isolation ON {schema}.{tbl}
  FOR ALL
  USING (tenant_id::text = current_setting('app.tenant_id'::text, true))
  WITH CHECK (tenant_id::text = current_setting('app.tenant_id'::text, true));
"""


async def ensure_policy(s, schema: str, tbl: str, force: bool) -> None:
    """Add tenant_isolation policy if missing; enable+force RLS."""
    # check existing policy
    r = await s.execute(
        text("SELECT count(*) FROM pg_policies WHERE schemaname=:sc AND tablename=:t AND policyname='tenant_isolation'"),
        {"sc": schema, "t": tbl},
    )
    if r.scalar() == 0:
        await s.execute(text(POLICY_TMPL.format(schema=schema, tbl=tbl)))
        print(f"  + policy {schema}.{tbl}")
    await s.execute(text(f'ALTER TABLE {schema}.{tbl} ENABLE ROW LEVEL SECURITY'))
    if force:
        await s.execute(text(f'ALTER TABLE {schema}.{tbl} FORCE ROW LEVEL SECURITY'))
    print(f"  ~ RLS enabled{f' + FORCE' if force else ''} on {schema}.{tbl}")


async def main() -> None:
    async with async_session() as s:
        # DDL is transactional in PG — single commit at end; rollback on error
        try:
            print("=== B: tenant data tables (RLS + FORCE) ===")
            for tbl in TENANT_DATA_TABLES:
                await ensure_policy(s, "nexus_crm", tbl, force=True)

            print("\n=== C: silent-deny tables (RLS + policy, no FORCE — keep owner access) ===")
            for tbl in SILENT_DENY_TABLES:
                await ensure_policy(s, "nexus_crm", tbl, force=False)

            await s.commit()
            print("\n✅ Phase 1 committed")
        except Exception as e:
            await s.rollback()
            print(f"\n❌ ROLLED BACK: {e}")
            sys.exit(1)


asyncio.run(main())

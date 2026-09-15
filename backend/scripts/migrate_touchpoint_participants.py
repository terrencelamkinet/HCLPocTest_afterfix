"""
Migration: Create touchpoint_participants junction table and migrate existing contact_id data.

Run from project root:
    python -m backend.scripts.migrate_touchpoint_participants
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, MetaData, Table, Column, String, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import inspect

from app.config import settings

SYNC_URL = settings.database_url.replace("+asyncpg", "")


def run():
    engine = create_engine(SYNC_URL, echo=True)
    insp = inspect(engine)

    with engine.begin() as conn:
        # Create schema if it doesn't exist
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS nexus_crm"))

        # Check if referenced tables/schemas exist
        has_auth_schema = "nexus_auth" in insp.get_schema_names()
        has_crm_schema = "nexus_crm" in insp.get_schema_names()

        if has_crm_schema and has_auth_schema:
            # Full FK constraints
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS nexus_crm.touchpoint_participants (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL REFERENCES nexus_auth.nexus_auth_tenants(id) ON DELETE CASCADE,
                    touchpoint_id UUID NOT NULL REFERENCES nexus_crm.touchpoints(id) ON DELETE CASCADE,
                    contact_id UUID NOT NULL REFERENCES nexus_crm.contacts(id) ON DELETE CASCADE
                )
            """))
            # Migrate existing data
            if "touchpoints" in insp.get_table_names(schema="nexus_crm"):
                result = conn.execute(
                    text("""
                        INSERT INTO nexus_crm.touchpoint_participants (id, tenant_id, touchpoint_id, contact_id)
                        SELECT gen_random_uuid(), tenant_id, id, contact_id
                        FROM nexus_crm.touchpoints
                        WHERE contact_id IS NOT NULL
                        ON CONFLICT DO NOTHING
                    """)
                )
                print(f"Migrated {result.rowcount} touchpoint participants.")
        else:
            # Create table without FK constraints (schemas don't exist yet locally)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS nexus_crm.touchpoint_participants (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    touchpoint_id UUID NOT NULL,
                    contact_id UUID NOT NULL
                )
            """))
            print("Created touchpoint_participants table (without FK constraints — schemas not found).")

    print("Migration complete.")


if __name__ == "__main__":
    run()

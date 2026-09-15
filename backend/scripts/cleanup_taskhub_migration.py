#!/usr/bin/env python3
"""Remove duplicate rows created by migrate_taskhub_to_nexus.py (2026-08-01).

G08 nexus_crm DB already had its own data (notion_import) — the migration
created duplicates. This removes only the rows with deterministic uuid5 ids
(migration-generated) / source='taskhub_migration'.
"""
import os
import uuid

import psycopg2
import psycopg2.extras

psycopg2.extras.register_uuid()

KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _load_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    _load_env()
    src = psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("PG_FIGHTER_USER", "gg_fighter"),
        password=os.environ.get("PG_FIGHTER_PASSWORD") or os.environ.get("PG_PASSWORD"),
        dbname="task_hub",
    )
    dst = psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("PG_FIGHTER_USER", "gg_fighter"),
        password=os.environ.get("PG_FIGHTER_PASSWORD") or os.environ.get("PG_PASSWORD"),
        dbname="nexus_crm",
    )
    src.autocommit = True
    cur = src.cursor()
    w = dst.cursor()
    w.execute("SELECT set_config('app.tenant_id', %s, false)", (KINETIX_TENANT,))

    # compute migration ids from source
    cur.execute("SELECT company_id FROM nexus_companies")
    comp_ids = [uuid.uuid5(NS, f"nexus-company:{r[0]}") for r in cur.fetchall()]
    cur.execute("SELECT contact_id FROM nexus_contacts")
    cont_ids = [uuid.uuid5(NS, f"nexus-contact:{r[0]}") for r in cur.fetchall()]
    cur.execute("SELECT project_id FROM nexus_projects")
    proj_ids = [uuid.uuid5(NS, f"nexus-project:{r[0]}") for r in cur.fetchall()]
    cur.execute("SELECT id FROM tasks WHERE status IN ('active','in_progress')")
    task_ids = [uuid.uuid5(NS, f"nexus-task:{r[0]}") for r in cur.fetchall()]

    stats = {}
    for table, ids in [("tasks", task_ids), ("projects", proj_ids),
                       ("contacts", cont_ids), ("companies", comp_ids)]:
        if not ids:
            continue
        w.execute(f"DELETE FROM nexus_crm.{table} WHERE id = ANY(%s)", (ids,))
        stats[table] = w.rowcount
    # contacts also by source marker (belt & braces)
    w.execute("DELETE FROM nexus_crm.contacts WHERE source = 'taskhub_migration'")
    stats["contacts_source"] = w.rowcount
    dst.commit()

    w.execute("SELECT set_config('app.tenant_id', %s, false)", (KINETIX_TENANT,))
    w.execute(
        "SELECT (SELECT count(*) FROM nexus_crm.companies), "
        "(SELECT count(*) FROM nexus_crm.contacts), "
        "(SELECT count(*) FROM nexus_crm.projects), "
        "(SELECT count(*) FROM nexus_crm.tasks)"
    )
    print("deleted:", stats)
    print("remaining:", w.fetchone())
    cur.close(); w.close(); src.close(); dst.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Migrate task_hub CRM data → G08 nexus_crm DB (one-way, idempotent).

治根方案 (2026-08-01): G08 係獨立 project，唔准 runtime 讀 Hermes data。
呢個 script 將真 CRM data 正式 import 入 G08 自己個 nexus_crm DB，令 G08
自給自足。

Sources (task_hub DB):
- nexus_companies (100) → nexus_crm.companies
- nexus_contacts  (199) → nexus_crm.contacts   (company_id remap, 可空)
- nexus_projects  (54/62 with company) → nexus_crm.projects (project_code auto)
- tasks active/in_progress (9) → nexus_crm.tasks (active→pending mapping)

RLS: set_config('app.tenant_id', <Kinetix>, false) 喺寫入前設定。
Idempotent: 用 uuid5 由 source id 派生穩定 UUID，ON CONFLICT (id) DO UPDATE。

Run: python3 migrate_taskhub_to_nexus.py
"""
import json
import os
import uuid

import psycopg2
import psycopg2.extras

psycopg2.extras.register_uuid()

KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
WORKSPACE_ID = "33a46d5e-46f5-48b5-921e-da5855d5a0b9"
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace


def _load_env():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _conn(db: str):
    _load_env()
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("PG_FIGHTER_USER", "gg_fighter"),
        password=os.environ.get("PG_FIGHTER_PASSWORD") or os.environ.get("PG_PASSWORD"),
        dbname=db,
    )


def cid(source: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"nexus-company:{source}")


def cid_contact(source: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"nexus-contact:{source}")


def pid(source: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"nexus-project:{source}")


def tid(source: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"nexus-task:{source}")


def main() -> int:
    src = _conn("task_hub")
    dst = _conn("nexus_crm")
    src.autocommit = True

    cur = src.cursor()
    w = dst.cursor()

    # RLS gate — session scoped, must be set before any write
    w.execute("SELECT set_config('app.tenant_id', %s, false)", (KINETIX_TENANT,))

    stats = {"companies": 0, "contacts": 0, "projects": 0, "tasks": 0}

    # ── 1. Companies ──
    cur.execute(
        "SELECT company_id, name, category, industry, website, linkedin, health_score, "
        "last_touch_date, ai_summary, name_aliases, properties, cached_ts "
        "FROM nexus_companies WHERE name IS NOT NULL AND name != ''"
    )
    company_map: dict[str, uuid.UUID] = {}
    for r in cur.fetchall():
        c_id = cid(r[0])
        company_map[r[0]] = c_id
        aliases = r[9] or []
        props = r[10] or {}
        w.execute(
            """INSERT INTO nexus_crm.companies
               (id, tenant_id, workspace_id, name, category, industry, website,
                linkedin_url, relationship_health_score, last_touchpoint_at,
                notes, tags, custom_fields, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 category=EXCLUDED.category, industry=EXCLUDED.industry,
                 website=EXCLUDED.website, linkedin_url=EXCLUDED.linkedin_url,
                 relationship_health_score=EXCLUDED.relationship_health_score,
                 last_touchpoint_at=EXCLUDED.last_touchpoint_at,
                 notes=EXCLUDED.notes, tags=EXCLUDED.tags,
                 custom_fields=EXCLUDED.custom_fields, updated_at=EXCLUDED.updated_at""",
            (
                c_id, uuid.UUID(KINETIX_TENANT), uuid.UUID(WORKSPACE_ID),
                r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                r[8], aliases, json.dumps(props, ensure_ascii=False), r[11], r[11],
            ),
        )
        stats["companies"] += 1

    # ── 2. Contacts ──
    cur.execute(
        "SELECT contact_id, name, chinese_name, company_id, job_title, email, phone, "
        "health_score, last_touch_date, ai_profile_memo, namecard_url, properties, cached_ts "
        "FROM nexus_contacts WHERE name IS NOT NULL AND name != ''"
    )
    for r in cur.fetchall():
        c_id = cid_contact(r[0])
        comp = company_map.get(r[3]) if r[3] else None
        props = r[11] or {}
        custom = dict(props)
        if r[6]:
            custom.setdefault("phone", r[6])
        w.execute(
            """INSERT INTO nexus_crm.contacts
               (id, tenant_id, workspace_id, company_id, name, chinese_name, job_title,
                email, phone, linkedin_url, notes, namecard_path, source,
                custom_fields, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 company_id=EXCLUDED.company_id, chinese_name=EXCLUDED.chinese_name,
                 job_title=EXCLUDED.job_title, email=EXCLUDED.email, phone=EXCLUDED.phone,
                 notes=EXCLUDED.notes, custom_fields=EXCLUDED.custom_fields,
                 updated_at=EXCLUDED.updated_at""",
            (
                c_id, uuid.UUID(KINETIX_TENANT), uuid.UUID(WORKSPACE_ID), comp,
                r[1], r[2], r[4], r[5], r[6],
                props.get("linkedin") if isinstance(props, dict) else None,
                r[9], r[10], "taskhub_migration",
                json.dumps(custom, ensure_ascii=False), r[12], r[12],
            ),
        )
        stats["contacts"] += 1

    # ── 3. Projects (only with company link) ──
    cur.execute(
        "SELECT project_id, name, company_id, project_type, stage, deal_value, "
        "expected_close, stage_entered_at, risk_level, ai_next_action, properties, cached_ts "
        "FROM nexus_projects WHERE company_id IS NOT NULL AND company_id != ''"
    )
    for r in cur.fetchall():
        comp = company_map.get(r[2])
        if comp is None:
            continue
        p_id = pid(r[0])
        w.execute(
            """INSERT INTO nexus_crm.projects
               (id, tenant_id, workspace_id, project_code, name, company_id,
                status, priority, description, budget_amount, deadline, start_date,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 company_id=EXCLUDED.company_id, status=EXCLUDED.status,
                 priority=EXCLUDED.priority, description=EXCLUDED.description,
                 budget_amount=EXCLUDED.budget_amount, deadline=EXCLUDED.deadline,
                 updated_at=EXCLUDED.updated_at""",
            (
                p_id, uuid.UUID(KINETIX_TENANT), uuid.UUID(WORKSPACE_ID),
                f"PJ-{str(p_id)[:8].upper()}", r[1], comp,
                r[4], r[8], r[9], r[5], r[6], r[7],
                r[11], r[11],
            ),
        )
        stats["projects"] += 1

    # ── 4. Tasks (active/in_progress only; active→pending for G08 filter) ──
    cur.execute(
        "SELECT id, title, priority, status, due_date, project, notes, created_at, updated_at "
        "FROM tasks WHERE status IN ('active','in_progress') ORDER BY due_date NULLS LAST"
    )
    for r in cur.fetchall():
        t_id = tid(str(r[0]))
        status = "pending" if r[3] == "active" else r[3]
        w.execute(
            """INSERT INTO nexus_crm.tasks
               (id, tenant_id, workspace_id, title, priority, status, due_date,
                description, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 priority=EXCLUDED.priority, status=EXCLUDED.status,
                 due_date=EXCLUDED.due_date, description=EXCLUDED.description,
                 updated_at=EXCLUDED.updated_at""",
            (
                t_id, uuid.UUID(KINETIX_TENANT), uuid.UUID(WORKSPACE_ID),
                r[1], r[2] or "P3", status, r[4], r[6], r[7], r[8],
            ),
        )
        stats["tasks"] += 1

    dst.commit()

    # ── Verify ──
    v = dst.cursor()
    v.execute("SELECT set_config('app.tenant_id', %s, false)", (KINETIX_TENANT,))
    v.execute(
        "SELECT (SELECT count(*) FROM nexus_crm.companies), "
        "(SELECT count(*) FROM nexus_crm.contacts), "
        "(SELECT count(*) FROM nexus_crm.projects), "
        "(SELECT count(*) FROM nexus_crm.tasks)"
    )
    counts = v.fetchone()

    print(f"migrated: {stats}")
    print(f"verified (nexus_crm, Kinetix tenant): companies={counts[0]} contacts={counts[1]} projects={counts[2]} tasks={counts[3]}")
    cur.close(); w.close(); v.close()
    src.close(); dst.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

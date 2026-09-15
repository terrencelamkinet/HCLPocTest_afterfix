"""
Migrate Notion staging data → NEXUS CRM tables.
Order: Companies → Contacts → Projects → Tasks + Custom Fields

Usage:
    python3 migrate_staging_to_nexus.py
"""
import json, os, sys, uuid
import psycopg2
from psycopg2.extras import execute_values

from _dbcred import dsn_kwargs as _dsn  # noqa: E402  (2026-09-15 SAST：唔再 hardcode)
PG_DSN = _dsn()
TENANT_ID = "00000000-0000-0000-0000-000000000001"
WORKSPACE_ID = "33a46d5e-46f5-48b5-921e-da5855d5a0b9"  # Kinetix Default Workspace

conn = psycopg2.connect(PG_DSN)
conn.autocommit = False
cur = conn.cursor()

# ════════════════════════════════════════════
# SAFETY GUARD — never double-migrate.
# Abort if nexus_crm already has data (prevents duplicate rows on re-run).
# ════════════════════════════════════════════
cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_ID,))
for table in ("companies", "contacts", "tasks"):
    cur.execute(f"SELECT COUNT(*) FROM nexus_crm.{table}")
    row = cur.fetchone()
    n = int(row[0]) if row else 0
    if n > 0:
        print(f"ABORT: nexus_crm.{table} already has {n} rows — migration already done?")
        print("Run only when nexus_crm is empty. Exiting without changes.")
        sys.exit(1)
print("✓ nexus_crm is empty — safe to migrate")

# Track Notion→CRM UUID mapping for relation resolution
id_map = {"companies": {}, "contacts": {}, "projects": {}, "tasks": {}}
errors = []

def log(msg):
    print(f"  {msg}")

def set_tenant():
    cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_ID,))

set_tenant()

def gen_uuid():
    return str(uuid.uuid4())

def safe_str(v):
    if v is None: return None
    return str(v)[:500]

# ════════════════════════════════════════════
# 1. COMPANIES
# ════════════════════════════════════════════
log("Migrating companies...")

cur.execute("SELECT id FROM notion_staging.companies ORDER BY name")
stg_companies = cur.fetchall()
log(f"  {len(stg_companies)} in staging")

inserted = 0
for row in stg_companies:
    stg_id = row[0]
    # Fetch full row
    cur.execute("SELECT * FROM notion_staging.companies WHERE id = %s", (stg_id,))
    c = cur.fetchone()
    if not c: continue
    
    # Map columns
    desc = [d[0] for d in cur.description]
    d = dict(zip(desc, c))
    
    new_id = gen_uuid()
    
    category = d.get("category")
    # Normalize category: Vendor/Distributor → Vendor (CRM only has single select)
    if category == "Vendor/Distributor":
        category = "Vendor"
    
    try:
        cur.execute("""
            INSERT INTO nexus_crm.companies (id, tenant_id, workspace_id, name, website, linkedin_url, address, ceo_name, category, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, (
            new_id, TENANT_ID, WORKSPACE_ID,
            safe_str(d.get("name")),
            safe_str(d.get("website")),
            safe_str(d.get("linkedin")),
            safe_str(d.get("address")),
            safe_str(d.get("ceo")),
            category,
            f"Migrated from Notion. Source ID: {d['id']}"
        ))
        
        # Industry join table
        industries = d.get("industry")
        if industries and isinstance(industries, (list, str)):
            if isinstance(industries, str):
                industries = json.loads(industries)
            for ind in industries:
                if ind:
                    cur.execute("INSERT INTO nexus_crm.company_industries (company_id, industry_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                              (new_id, ind))
        
        # Country join table
        countries = d.get("country")
        if countries and isinstance(countries, (list, str)):
            if isinstance(countries, str):
                countries = json.loads(countries)
            for cnt in countries:
                if cnt:
                    cc = cnt[:10]  # VARCHAR(10) limit
                    cur.execute("INSERT INTO nexus_crm.company_countries (company_id, country_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                              (new_id, cc))
        
        id_map["companies"][str(d["id"])] = new_id
        inserted += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        set_tenant()
        errors.append(f"Company {d.get('name', 'unnamed')}: {e}")
        log(f"  ✗ {d.get('name', 'unnamed')}: {e}")

log(f"  ✓ {inserted} companies inserted ({len(stg_companies) - inserted} skipped)")

# ════════════════════════════════════════════
# 2. CONTACTS
# ════════════════════════════════════════════
log("\nMigrating contacts...")

cur.execute("SELECT id, client_name FROM notion_staging.contacts ORDER BY client_name")
stg_contacts = cur.fetchall()
log(f"  {len(stg_contacts)} in staging")

inserted = 0
for row in stg_contacts:
    stg_id = row[0]
    cur.execute("SELECT * FROM notion_staging.contacts WHERE id = %s", (stg_id,))
    c = cur.fetchone()
    if not c: continue
    
    desc = [d[0] for d in cur.description]
    d = dict(zip(desc, c))
    
    new_id = gen_uuid()
    
    # Resolve company_id from companies_rel (first linked company)
    company_id = None
    companies_rel = d.get("companies_rel")
    if companies_rel:
        if isinstance(companies_rel, str):
            companies_rel = json.loads(companies_rel)
        if companies_rel and len(companies_rel) > 0:
            notion_company_id = str(companies_rel[0])
            company_id = id_map["companies"].get(notion_company_id)
            if not company_id:
                log(f"  ⚠ Contact {d.get('client_name')}: company {notion_company_id[:8]} not found in CRM")
    
    # Map type/grade
    contact_type = d.get("contact_type")
    grade = d.get("grade")
    tag = d.get("tag")
    
    try:
        cur.execute("""
            INSERT INTO nexus_crm.contacts (id, tenant_id, workspace_id, company_id, name, chinese_name, nick_name, email, phone, office_phone, job_title, department, linkedin_url, address, notes, contact_type, grade, source, status, namecard_path, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, (
            new_id, TENANT_ID, WORKSPACE_ID, company_id,
            safe_str(d.get("client_name")),
            safe_str(d.get("chinese_name")),
            safe_str(d.get("nick_name")),
            d.get("email"),
            d.get("phone"),
            d.get("office"),
            safe_str(d.get("title")),
            safe_str(d.get("department")),
            d.get("linkedin"),
            safe_str(d.get("address")),
            safe_str(d.get("notes")),
            contact_type,
            grade,
            "notion_import",
            "lead" if not tag else "active",
            d.get("name_card_url"),
        ))
        
        id_map["contacts"][str(d["id"])] = new_id
        inserted += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        errors.append(f"Contact {d.get('client_name')}: {e}")
        log(f"  ✗ {d.get('client_name')}: {e}")

log(f"  ✓ {inserted} contacts inserted ({len(stg_contacts) - inserted} skipped)")

# ════════════════════════════════════════════
# 3. PROJECTS
# ════════════════════════════════════════════
log("\nMigrating projects...")

# Find Kinetix as fallback company for projects without company link
cur.execute("SELECT id FROM nexus_crm.companies WHERE name ILIKE '%kinetix%'")
kinetix_row = cur.fetchone()
kinetix_id = kinetix_row[0] if kinetix_row else None
log(f"  Fallback company ID: {kinetix_id}")

# Get project stages from CRM
cur.execute("SELECT id, stage_name FROM nexus_crm.project_stages WHERE tenant_id = %s", (TENANT_ID,))
crm_stages = {r[1]: r[0] for r in cur.fetchall()}

# If no stages exist, create them
if not crm_stages:
    stage_names = [
        "First Touch", "Review Existing Environment", "Quotation",
        "Solution Presentation", "PoC", "RFQ/Tender", "Tender Presentation",
        "Award", "Project Start", "Project Closing", "Planning"
    ]
    for i, sname in enumerate(stage_names):
        sid = gen_uuid()
        cur.execute("INSERT INTO nexus_crm.project_stages (id, tenant_id, stage_key, stage_name, stage_order) VALUES (%s, %s, %s, %s, %s)",
                   (sid, TENANT_ID, sname.lower().replace(" ", "_"), sname, i))
        crm_stages[sname] = sid
    conn.commit()
    log(f"  Created {len(stage_names)} project stages")

cur.execute("SELECT id, project_name FROM notion_staging.projects ORDER BY project_name")
stg_projects = cur.fetchall()
log(f"  {len(stg_projects)} in staging")

inserted = 0
for row in stg_projects:
    stg_id = row[0]
    cur.execute("SELECT * FROM notion_staging.projects WHERE id = %s", (stg_id,))
    c = cur.fetchone()
    if not c: continue
    
    desc = [d[0] for d in cur.description]
    d = dict(zip(desc, c))
    
    new_id = gen_uuid()
    
    # Resolve company
    company_id = None
    if d.get("company_rel"):
        company_id = id_map["companies"].get(str(d["company_rel"]))
    
    # Resolve stage
    stage_id = crm_stages.get(d.get("stage"))
    
    # Map priority
    priority_map = {"Low": "low", "Medium": "medium", "High": "high", "Urgent": "urgent"}
    priority = priority_map.get(d.get("priority"), "medium")
    
    # Map status
    status_map = {"Not started": "pending", "In progress": "in_progress", "Pending": "pending", "Done": "done", "Canceled": "cancelled"}
    status = status_map.get(d.get("status"), "pending")
    
    start = d.get("start_date")
    deadline = d.get("deadline")
    
    try:
        cur.execute("""
            INSERT INTO nexus_crm.projects (id, tenant_id, workspace_id, project_code, name, company_id, stage_id, status, priority, description, start_date, deadline, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, (
            new_id, TENANT_ID, WORKSPACE_ID,
            f"PRJ-{d['id'][:8].upper()}",
            safe_str(d.get("project_name")),
            company_id or kinetix_id,
            stage_id,
            status,
            priority,
            safe_str(d.get("description")),
            start,
            deadline,
        ))
        
        # Project contacts (Related Client)
        related_clients = d.get("related_client")
        if related_clients:
            if isinstance(related_clients, str):
                related_clients = json.loads(related_clients)
            for rc_id in related_clients:
                crm_contact_id = id_map["contacts"].get(str(rc_id))
                if crm_contact_id:
                    cur.execute("""
                        INSERT INTO nexus_crm.project_contacts (project_id, contact_id, relation_role)
                        VALUES (%s, %s, 'Related Client') ON CONFLICT DO NOTHING
                    """, (new_id, crm_contact_id))
        
        id_map["projects"][str(d["id"])] = new_id
        inserted += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        errors.append(f"Project {d.get('project_name')}: {e}")
        log(f"  ✗ {d.get('project_name')}: {e}")

log(f"  ✓ {inserted} projects inserted ({len(stg_projects) - inserted} skipped)")

# ════════════════════════════════════════════
# 4. TASKS + Custom Fields
# ════════════════════════════════════════════
log("\nMigrating tasks...")

# Get custom field definition IDs
cur.execute("""
    SELECT field_key, id FROM nexus_crm.custom_field_definitions 
    WHERE tenant_id = %s AND module_name = 'tasks'
""", (TENANT_ID,))
def_map = {r[0]: r[1] for r in cur.fetchall()}
log(f"  {len(def_map)} custom field definitions loaded")

cur.execute("SELECT id, name FROM notion_staging.tasks ORDER BY name")
stg_tasks = cur.fetchall()
log(f"  {len(stg_tasks)} in staging")

inserted = 0
for row in stg_tasks:
    stg_id = row[0]
    cur.execute("SELECT * FROM notion_staging.tasks WHERE id = %s", (stg_id,))
    c = cur.fetchone()
    if not c: continue
    
    desc = [d[0] for d in cur.description]
    d = dict(zip(desc, c))
    
    new_id = gen_uuid()
    
    # Map status
    status_map = {
        "Not started": "pending", "Pending": "pending", "In progress": "in_progress",
        "Blocked": "pending", "Done": "done", "Cancelled": "cancelled"
    }
    status = status_map.get(d.get("status"), "pending")
    
    # Native area
    area = d.get("area")
    
    # Resolve company from project
    company_id = None
    project_rel = d.get("project_rel")
    if project_rel:
        crm_proj_id = id_map["projects"].get(str(project_rel))
        if crm_proj_id:
            cur.execute("SELECT company_id FROM nexus_crm.projects WHERE id = %s", (crm_proj_id,))
            r = cur.fetchone()
            if r:
                company_id = r[0]
    
    due = d.get("due_date")
    
    try:
        cur.execute("""
            INSERT INTO nexus_crm.tasks (id, tenant_id, workspace_id, title, description, due_date, priority, status, area, recurring, company_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, (
            new_id, TENANT_ID, WORKSPACE_ID,
            safe_str(d.get("name")),
            safe_str(d.get("notes")),
            due,
            "medium",  # default CRM priority
            status,
            area,
            d.get("recurring") or False,
            company_id,
        ))
        
        # Insert custom field values
        cf_values = {}
        
        # Notion priority (Eisenhower)
        notion_priority = d.get("priority") or d.get("quadrant")
        if notion_priority:
            cf_values["notion_priority"] = notion_priority
        
        # Area detail (same as native area, but in custom fields too)
        if area:
            cf_values["area_detail"] = area
        
        # Delegate
        if d.get("delegate"):
            cf_values["delegate"] = d["delegate"]
        
        # Do Date
        if d.get("do_date"):
            cf_values["do_date"] = d["do_date"]
        
        # Done checkbox
        cf_values["done_checkbox"] = "true" if d.get("done_checkbox") else "false"
        
        # Notion page ID
        cf_values["notion_page_id"] = str(d["id"])
        
        # Project ref
        if project_rel:
            cf_values["project_ref"] = str(project_rel)
        
        # Parent task
        if d.get("parent_task_rel"):
            cf_values["parent_notion_id"] = str(d["parent_task_rel"])
        
        # Follow-up day (auto-derive from area)
        if area and "follow_up_day" not in cf_values:
            day_map = {"💼 Work": "Monday", "📚 Learning": "Monday", "🏠 Personal": "Saturday", "✝️ Jesus": "Monday"}
            cf_values["follow_up_day"] = day_map.get(area, "Monday")
        
        for field_key, val in cf_values.items():
            def_id = def_map.get(field_key)
            if not def_id:
                continue
            # Determine value type
            if field_key in ("do_date",):
                cur.execute("""
                    INSERT INTO nexus_crm.custom_field_values (tenant_id, definition_id, record_id, value_date, module_name)
                    VALUES (%s, %s, %s, %s::date, 'tasks')
                    ON CONFLICT ON CONSTRAINT uq_custom_field_values_def_record
                    DO UPDATE SET value_date = EXCLUDED.value_date, updated_at = now()
                """, (TENANT_ID, def_id, new_id, val))
            elif field_key in ("done_checkbox",):
                is_true = val.lower() in ("true", "1", "yes")
                cur.execute("""
                    INSERT INTO nexus_crm.custom_field_values (tenant_id, definition_id, record_id, value_boolean, module_name)
                    VALUES (%s, %s, %s, %s, 'tasks')
                    ON CONFLICT ON CONSTRAINT uq_custom_field_values_def_record
                    DO UPDATE SET value_boolean = EXCLUDED.value_boolean, updated_at = now()
                """, (TENANT_ID, def_id, new_id, is_true))
            else:
                cur.execute("""
                    INSERT INTO nexus_crm.custom_field_values (tenant_id, definition_id, record_id, value_text, module_name)
                    VALUES (%s, %s, %s, %s, 'tasks')
                    ON CONFLICT ON CONSTRAINT uq_custom_field_values_def_record
                    DO UPDATE SET value_text = EXCLUDED.value_text, updated_at = now()
                """, (TENANT_ID, def_id, new_id, safe_str(val)))
        
        id_map["tasks"][str(d["id"])] = new_id
        inserted += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        errors.append(f"Task {d.get('name')}: {e}")
        log(f"  ✗ {d.get('name')}: {e}")

log(f"  ✓ {inserted} tasks inserted ({len(stg_tasks) - inserted} skipped)")

# ════════════════════════════════════════════
# 5. VERIFY
# ════════════════════════════════════════════
log("\n═══ VERIFICATION ═══")
cur.execute("SELECT 'companies', count(*) FROM nexus_crm.companies UNION ALL SELECT 'contacts', count(*) FROM nexus_crm.contacts UNION ALL SELECT 'projects', count(*) FROM nexus_crm.projects UNION ALL SELECT 'tasks', count(*) FROM nexus_crm.tasks UNION ALL SELECT 'custom_field_values', count(*) FROM nexus_crm.custom_field_values UNION ALL SELECT 'company_industries', count(*) FROM nexus_crm.company_industries UNION ALL SELECT 'company_countries', count(*) FROM nexus_crm.company_countries")
for r in cur.fetchall():
    status = "⚠️" if r[1] == 0 else "✅"
    log(f"  {status} {r[0]}: {r[1]}")

if errors:
    log(f"\n⚠️ {len(errors)} errors during migration:")
    for e in errors[:10]:
        log(f"  ✗ {e}")
    if len(errors) > 10:
        log(f"  ... and {len(errors) - 10} more")

conn.close()
print("\n✅ Migration complete")

"""
Pull all Notion CRM data into notion_staging tables (nexus_crm PG).
Row-by-row insert to avoid psycopg2 JSONB %s issues.
Usage: python3 pull_notion_to_staging.py
"""
import json, os, sys, time
import requests, psycopg2

NOTION_KEY = open(os.path.expanduser("~/.config/notion/api_key")).read().strip()
HEADERS = {"Authorization": f"Bearer {NOTION_KEY}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
from _dbcred import dsn_kwargs as _dsn  # noqa: E402  (2026-09-15 SAST：唔再 hardcode)
PG_DSN = _dsn()

DB_IDS = {
    "companies": "2a2783d5-93e7-81fb-84a2-e3cd479bd1e7",
    "contacts":  "2a2783d5-93e7-8150-b31f-d1e3ab923d5c",
    "projects":  "2a2783d5-93e7-81c8-931d-fae7807342eb",
    "tasks":     "c5d6a00c-b4ab-40e5-ae83-505facd37be0",
}

def notion_prop(prop):
    if prop is None: return None
    t = prop.get("type", ""); val = prop.get(t, {})
    if t == "title": return "".join([s.get("plain_text","") for s in val]) or None
    if t in ("rich_text",): return "".join([s.get("plain_text","") for s in val]) or None
    if t == "email": return val or None
    if t in ("phone_number",): return val or None
    if t == "url": return val or None
    if t == "select": return val.get("name") if val else None
    if t == "multi_select": return [o.get("name") for o in val] if val else []
    if t == "status": return val.get("name") if val else None
    if t == "date":
        return val.get("start") if val and val.get("start") else None
    if t == "checkbox": return val if val is not None else False
    if t == "number": return val
    if t == "files":
        if val and len(val) > 0:
            f = val[0]
            return f.get("external",{}).get("url") or f.get("file",{}).get("url") or None
        return None
    if t == "relation": return [r.get("id") for r in val] if val else []
    return None

def fetch_all(db_id):
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor: body["start_cursor"] = cursor
        resp = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json=body, timeout=30)
        if resp.status_code == 503: time.sleep(3); continue
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"): break
        cursor = data.get("next_cursor")
    return pages

def insert_batch(cur, table, cols, rows):
    """Row-by-row upsert with JSONB handling."""
    placeholders = ", ".join([f"%({c})s" for c in cols])
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c != "id"])
    updates += ", imported_at = now()"
    sql = f"""
        INSERT INTO notion_staging.{table} ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {updates}
    """
    for r in rows:
        cur.execute(sql, {c: json.dumps(r[c]) if isinstance(r[c], (list, dict)) else r[c] for c in cols})

# --- Company ---
def pull_companies(conn):
    pages = fetch_all(DB_IDS["companies"]); print(f"  {len(pages)} companies")
    rows = []
    for p in pages:
        prop = p.get("properties", {})
        c = [notion_prop(prop.get(k)) for k in ("Contacts","Using Products","Proposed Products","Sales","Projects")]
        rows.append({
            "id": p["id"],
            "raw_data": json.dumps(p),
            "name": notion_prop(prop.get("Name")),
            "website": notion_prop(prop.get("Website")),
            "linkedin": notion_prop(prop.get("Linkedin")),
            "address": notion_prop(prop.get("Address")),
            "ceo": notion_prop(prop.get("CEO")),
            "category": notion_prop(prop.get("Category")),
            "industry": notion_prop(prop.get("Industry")) or [],
            "country": notion_prop(prop.get("Country")) or [],
            "logo_url": notion_prop(prop.get("Logo")),
            "distributor_partners": notion_prop(prop.get("Distributor Partners")) or [],
            "contacts_rel": c[0] or [],
            "using_products": c[1] or [],
            "proposed_products": c[2] or [],
            "sales_rel": c[3] or [],
            "projects_rel": c[4] or [],
            "contact_point": notion_prop(prop.get("Contact Point")),
        })
    with conn.cursor() as cur:
        insert_batch(cur, "companies", [
            "id","raw_data","name","website","linkedin","address","ceo","category",
            "industry","country","logo_url","distributor_partners","contacts_rel",
            "using_products","proposed_products","sales_rel","projects_rel","contact_point",
        ], rows)
    conn.commit(); print(f"  ✓ {len(rows)} companies inserted")

# --- Contact ---
def pull_contacts(conn):
    pages = fetch_all(DB_IDS["contacts"]); print(f"  {len(pages)} contacts")
    rows = []
    for p in pages:
        prop = p.get("properties", {})
        rows.append({
            "id": p["id"],
            "raw_data": json.dumps(p),
            "client_name": notion_prop(prop.get("Client Name")),
            "chinese_name": notion_prop(prop.get("Chinese Name")),
            "nick_name": notion_prop(prop.get("Nick Name")),
            "email": notion_prop(prop.get("Email")),
            "phone": notion_prop(prop.get("Phone")),
            "office": notion_prop(prop.get("Office")),
            "title": notion_prop(prop.get("Title")),
            "department": notion_prop(prop.get("Department")),
            "linkedin": notion_prop(prop.get("LinkedIn")),
            "address": notion_prop(prop.get("Address")),
            "notes": notion_prop(prop.get("Notes")),
            "grade": notion_prop(prop.get("Grade")),
            "tag": notion_prop(prop.get("Tag")),
            "contact_type": notion_prop(prop.get("Type")),
            "companies_rel": notion_prop(prop.get("Companies")) or [],
            "projects_rel": notion_prop(prop.get("Projects")) or [],
            "touchpoints_rel": notion_prop(prop.get("Touch Points")) or [],
            "name_card_url": notion_prop(prop.get("Name Card")),
            "no_field": notion_prop(prop.get("No.")) or [],
        })
    with conn.cursor() as cur:
        insert_batch(cur, "contacts", [
            "id","raw_data","client_name","chinese_name","nick_name","email","phone",
            "office","title","department","linkedin","address","notes","grade","tag",
            "contact_type","companies_rel","projects_rel","touchpoints_rel","name_card_url","no_field",
        ], rows)
    conn.commit(); print(f"  ✓ {len(rows)} contacts inserted")

# --- Project ---
def pull_projects(conn):
    pages = fetch_all(DB_IDS["projects"]); print(f"  {len(pages)} projects")
    rows = []
    for p in pages:
        prop = p.get("properties", {})
        company_rel = notion_prop(prop.get("Company")) or []
        rows.append({
            "id": p["id"],
            "raw_data": json.dumps(p),
            "project_name": notion_prop(prop.get("Project Name")),
            "description": notion_prop(prop.get("Description")),
            "stage": notion_prop(prop.get("Stage")),
            "stage_status": notion_prop(prop.get("Stage Status")),
            "status": notion_prop(prop.get("Status")),
            "priority": notion_prop(prop.get("Priority")),
            "start_date": notion_prop(prop.get("Start Date")),
            "deadline": notion_prop(prop.get("Deadline")),
            "company_rel": company_rel[0] if company_rel else None,
            "related_client": notion_prop(prop.get("Related Client")) or [],
            "vendor_distrib": notion_prop(prop.get("Vendor/Distributor")) or [],
            "products_rel": notion_prop(prop.get("Products")) or [],
            "sales_rel": notion_prop(prop.get("Sales")) or [],
            "linked_tasks": notion_prop(prop.get("Linked Tasks")) or [],
        })
    with conn.cursor() as cur:
        insert_batch(cur, "projects", [
            "id","raw_data","project_name","description","stage","stage_status",
            "status","priority","start_date","deadline","company_rel",
            "related_client","vendor_distrib","products_rel","sales_rel","linked_tasks",
        ], rows)
    conn.commit(); print(f"  ✓ {len(rows)} projects inserted")

# --- Task ---
def pull_tasks(conn):
    pages = fetch_all(DB_IDS["tasks"]); print(f"  {len(pages)} tasks")
    rows = []
    for p in pages:
        prop = p.get("properties", {})
        project_rel = notion_prop(prop.get("Project")) or []
        parent_rel = notion_prop(prop.get("Parent task")) or []
        due = notion_prop(prop.get("Due Date"))
        do = notion_prop(prop.get("Do Date"))
        rows.append({
            "id": p["id"],
            "raw_data": json.dumps(p),
            "name": notion_prop(prop.get("Name")),
            "status": notion_prop(prop.get("Status")),
            "priority": notion_prop(prop.get("Priority")),
            "quadrant": notion_prop(prop.get("Quadrant")),
            "area": notion_prop(prop.get("Area")),
            "notes": notion_prop(prop.get("Notes")),
            "due_date": due[:10] if due else None,
            "do_date": do[:10] if do else None,
            "delegate": notion_prop(prop.get("Delegate")),
            "recurring": notion_prop(prop.get("Recurring")) or False,
            "done_checkbox": notion_prop(prop.get("✅ Done")) or False,
            "project_rel": project_rel[0] if project_rel else None,
            "parent_task_rel": parent_rel[0] if parent_rel else None,
        })
    with conn.cursor() as cur:
        insert_batch(cur, "tasks", [
            "id","raw_data","name","status","priority","quadrant","area","notes",
            "due_date","do_date","delegate","recurring","done_checkbox",
            "project_rel","parent_task_rel",
        ], rows)
    conn.commit(); print(f"  ✓ {len(rows)} tasks inserted")

def main():
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = False
    print("Fetching Notion data...")
    print("\n1. Companies..."); pull_companies(conn)
    print("\n2. Contacts..."); pull_contacts(conn)
    print("\n3. Projects..."); pull_projects(conn)
    print("\n4. Tasks..."); pull_tasks(conn)
    conn.close()
    print("\n✅ Done! Verify:")
    print("  SELECT 'companies', count(*) FROM notion_staging.companies")
    print("  UNION ALL SELECT 'contacts', count(*) FROM notion_staging.contacts")
    print("  UNION ALL SELECT 'projects', count(*) FROM notion_staging.projects")
    print("  UNION ALL SELECT 'tasks', count(*) FROM notion_staging.tasks")

if __name__ == "__main__":
    main()

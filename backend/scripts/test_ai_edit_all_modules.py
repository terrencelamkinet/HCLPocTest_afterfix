"""Systematic test: AI edit capability for every CRM module.

Tests each module (contact/company/project/task/namecard) and every editable
field via draft → execute → DB verify, using the testing user/tenant data.
Also verifies name-fallback resolution and the invalid-target guard.

Run: cd backend && venv/bin/python scripts/test_ai_edit_all_modules.py
"""
import asyncio
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import text

sys.path.insert(0, ".")
from app.ai.tool_registry import (
    _update_company_draft,
    _update_contact_draft,
    _update_namecard_draft,
    _update_project_draft,
    _update_task_draft,
)
from app.db import async_session

TENANT = "feadc447-6c20-4499-9d0c-87b16709d46d"
WS = "2cf88959-eb58-4146-8eec-f45131438c62"
USER = "00000000-0000-0000-0000-000000000000"


@dataclass
class Ctx:
    tenant_id: str = TENANT
    workspace_id: str = WS
    user_id: str = USER


async def set_rls(db):
    conn = await db.connection()
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT})


async def fetch(db, sql, **kw):
    r = await db.execute(text(sql), kw)
    row = r.fetchone()
    if row is None:
        return None
    return tuple(str(v) if isinstance(v, uuid.UUID) else v for v in row)


async def test_update(db, handler, id_param, record_id, field, new_value, ctx):
    """Draft + execute a single-field update via the confirm path, verify DB."""
    await set_rls(db)  # commit resets transaction-scoped RLS context
    params = {id_param: record_id, field: new_value}
    draft = await handler(ctx, params, db, mode="draft")
    if not draft.get("validated"):
        return False, f"draft failed: {draft.get('errors')}"
    if draft.get("changes", {}).get(field) != new_value:
        return False, f"draft changes mismatch: {draft.get('changes')}"
    preview = {
        "action": draft["action"],
        id_param: draft[id_param],
        "current": draft.get("current"),
        "changes": draft["changes"],
        "validated": True,
    }
    result = await handler(ctx, preview, db, mode="execute")
    if result.get("errors"):
        await db.rollback()
        return False, f"execute failed: {result.get('errors')}"
    await db.commit()
    return True, None


async def main():
    ctx = Ctx()
    results = {}
    async with async_session() as db:
        await set_rls(db)

        # --- fixtures (testing user data) ---
        uid_row = await fetch(db, "SELECT id FROM nexus_auth.nexus_auth_users WHERE email='fulltest@test.com'")
        uid = uid_row[0]
        # contact
        await set_rls(db)
        c = await fetch(
            db,
            """INSERT INTO nexus_crm.contacts (tenant_id, workspace_id, name, email, phone, owner_id, created_at, updated_at)
               VALUES (:t, :w, 'AI 測試聯絡人', 'ai.contact@test.com', '+852 9000 0001', :u, now(), now()) RETURNING id""",
            t=TENANT, w=WS, u=uid,
        )
        contact_id = c[0]
        await db.commit()
        # company
        await set_rls(db)
        co = await fetch(
            db,
            """INSERT INTO nexus_crm.companies (tenant_id, workspace_id, name, domain, industry, phone, status, owner_id, created_at, updated_at)
               VALUES (:t, :w, 'AI 測試公司', 'ai-company.test.com', 'IT', '+852 9000 0002', 'active', :u, now(), now()) RETURNING id""",
            t=TENANT, w=WS, u=uid,
        )
        company_id = co[0]
        await db.commit()
        # project
        await set_rls(db)
        pr = await fetch(
            db,
            """INSERT INTO nexus_crm.projects (tenant_id, workspace_id, name, project_code, status, priority, company_id, created_at, updated_at)
               VALUES (:t, :w, 'AI 測試項目', 'AI-PROJ-001', 'active', 'high', :co, now(), now()) RETURNING id""",
            t=TENANT, w=WS, co=company_id,
        )
        project_id = pr[0]
        await db.commit()
        # task
        await set_rls(db)
        tk = await fetch(
            db,
            """INSERT INTO nexus_crm.tasks (tenant_id, workspace_id, title, description, priority, status, created_by, created_at, updated_at)
               VALUES (:t, :w, 'AI 測試任務', 'test desc', 'medium', 'pending', :u, now(), now()) RETURNING id""",
            t=TENANT, w=WS, u=uid,
        )
        task_id = tk[0]
        await db.commit()
        # namecard
        await set_rls(db)
        nc = await fetch(
            db,
            """INSERT INTO nexus_crm.name_cards (tenant_id, contact_id, status, dedup_status, created_at, updated_at)
               VALUES (:t, :c, 'processed', 'none', now(), now()) RETURNING id""",
            t=TENANT, c=contact_id,
        )
        namecard_id = nc[0]
        await db.commit()

        print(f"fixtures: contact={contact_id} company={company_id} project={project_id} task={task_id} namecard={namecard_id}")

        # --- contact fields ---
        for f, v in [("name", "AI 測試聯絡人 v2"), ("email", "ai.contact.v2@test.com"), ("phone", "+852 9111 1111"), ("notes", "聯絡人 notes 測試")]:
            ok, err = await test_update(db, _update_contact_draft, "contact_id", contact_id, f, v, ctx)
            results[f"contact.{f}"] = (ok, err)

        # --- company fields ---
        for f, v in [
            ("name", "AI 測試公司 v2"), ("domain", "ai-company-v2.test.com"), ("industry", "FinTech"),
            ("phone", "+852 9222 2222"), ("address", "香港中環"), ("website", "https://ai-company.test.com"),
            ("notes", "公司 notes 測試"), ("ceo_name", "陳大文"), ("status", "inactive"),
        ]:
            ok, err = await test_update(db, _update_company_draft, "company_id", company_id, f, v, ctx)
            results[f"company.{f}"] = (ok, err)

        # --- project fields ---
        for f, v in [
            ("name", "AI 測試項目 v2"), ("project_code", "AI-PROJ-002"), ("status", "completed"),
            ("priority", "low"), ("description", "項目描述測試"),
        ]:
            ok, err = await test_update(db, _update_project_draft, "project_id", project_id, f, v, ctx)
            results[f"project.{f}"] = (ok, err)
        ok, err = await test_update(db, _update_project_draft, "project_id", project_id, "budget_amount", 123456.78, ctx)
        results["project.budget_amount"] = (ok, err)
        ok, err = await test_update(db, _update_project_draft, "project_id", project_id, "deadline", "2026-12-31", ctx)
        results["project.deadline"] = (ok, err)

        # --- task fields ---
        for f, v in [
            ("title", "AI 測試任務 v2"), ("description", "任務描述測試"), ("priority", "urgent"), ("status", "in_progress"),
        ]:
            ok, err = await test_update(db, _update_task_draft, "task_id", task_id, f, v, ctx)
            results[f"task.{f}"] = (ok, err)
        ok, err = await test_update(db, _update_task_draft, "task_id", task_id, "due_date", "2026-12-31", ctx)
        results["task.due_date"] = (ok, err)
        ok, err = await test_update(db, _update_task_draft, "task_id", task_id, "is_important", True, ctx)
        results["task.is_important"] = (ok, err)

        # --- namecard fields ---
        for f, v in [("status", "reviewed"), ("dedup_status", "merged")]:
            ok, err = await test_update(db, _update_namecard_draft, "namecard_id", namecard_id, f, v, ctx)
            results[f"namecard.{f}"] = (ok, err)

        # --- name fallback (no UUID) ---
        await set_rls(db)
        draft = await _update_company_draft(ctx, {"company_id": "AI 測試公司 v2", "notes": "fallback 測試"}, db, mode="draft")
        results["company.name_fallback"] = (draft.get("validated") is True and draft["company_id"] == company_id, draft.get("errors"))
        await db.rollback()

        # --- guard: invalid id must not execute ---
        draft = await _update_project_draft(ctx, {"project_id": "唔係UUID", "name": "x"}, db, mode="draft")
        results["project.guard"] = (draft.get("validated") is False, draft.get("errors"))

        # --- verify every field in DB ---
        await set_rls(db)
        checks = [
            ("contact", contact_id, "SELECT name, email, phone, notes FROM nexus_crm.contacts WHERE id=:id",
             {"name": "AI 測試聯絡人 v2", "email": "ai.contact.v2@test.com", "phone": "+852 9111 1111", "notes": "聯絡人 notes 測試"}),
            ("company", company_id, "SELECT name, domain, industry, phone, address, website, notes, ceo_name, status FROM nexus_crm.companies WHERE id=:id",
             {"name": "AI 測試公司 v2", "domain": "ai-company-v2.test.com", "industry": "FinTech", "phone": "+852 9222 2222", "address": "香港中環", "website": "https://ai-company.test.com", "notes": "公司 notes 測試", "ceo_name": "陳大文", "status": "inactive"}),
            ("project", project_id, "SELECT name, project_code, status, priority, description, budget_amount, deadline FROM nexus_crm.projects WHERE id=:id",
             {"name": "AI 測試項目 v2", "project_code": "AI-PROJ-002", "status": "completed", "priority": "low", "description": "項目描述測試", "budget_amount": 123456.78, "deadline": "2026-12-31"}),
            ("task", task_id, "SELECT title, description, priority, status, due_date, is_important FROM nexus_crm.tasks WHERE id=:id",
             {"title": "AI 測試任務 v2", "description": "任務描述測試", "priority": "urgent", "status": "in_progress", "due_date": "2026-12-31", "is_important": True}),
            ("namecard", namecard_id, "SELECT status, dedup_status FROM nexus_crm.name_cards WHERE id=:id",
             {"status": "reviewed", "dedup_status": "merged"}),
        ]
        for module, rid, sql, expected in checks:
            row = await fetch(db, sql, id=rid)
            for i, (col, exp) in enumerate(expected.items()):
                got = row[i]
                try:
                    if isinstance(exp, float):
                        ok = abs(float(got) - exp) < 0.01
                    elif isinstance(exp, str):
                        ok = str(got) == exp or got == exp
                    else:
                        ok = got == exp
                except (TypeError, ValueError):
                    ok = False
                results[f"db.{module}.{col}"] = (ok, f"got={got!r} expected={exp!r}")

        # --- cleanup fixtures ---
        await set_rls(db)
        await db.execute(text("DELETE FROM nexus_crm.name_cards WHERE id=:id"), {"id": namecard_id})
        await db.execute(text("DELETE FROM nexus_crm.tasks WHERE id=:id"), {"id": task_id})
        await db.execute(text("DELETE FROM nexus_crm.projects WHERE id=:id"), {"id": project_id})
        await db.execute(text("DELETE FROM nexus_crm.companies WHERE id=:id"), {"id": company_id})
        await db.execute(text("DELETE FROM nexus_crm.contacts WHERE id=:id"), {"id": contact_id})
        await db.commit()

    print("\n" + "=" * 60)
    fails = 0
    for k, (ok, err) in sorted(results.items()):
        mark = "✅" if ok else "❌"
        print(f"  {mark} {k}" + ("" if ok else f"  ← {err}"))
        if not ok:
            fails += 1
    print("=" * 60)
    print(f"TOTAL: {len(results) - fails}/{len(results)} PASS" + ("  *** ALL PASS ***" if fails == 0 else f"  ({fails} FAILED)"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())

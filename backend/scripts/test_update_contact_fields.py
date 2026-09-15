"""Systematic test: every editable field of update_contact_draft.

Tests each field (name/email/phone/notes) via draft mode (validation/resolve)
then execute mode (real write), verifying the DB after each.  Also verifies
that an invalid target is NOT marked executed (confirm guard).

Run: cd backend && venv/bin/python scripts/test_update_contact_fields.py
"""
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import text

sys.path.insert(0, ".")
from app.ai.tool_registry import _update_contact_draft
from app.db import async_session

TENANT = "feadc447-6c20-4499-9d0c-87b16709d46d"
CONTACT_ID = "f45c0bb9-5e15-462d-95f7-f476e9a25ae9"  # AI Edit 測試客戶
ORIGINAL = {
    "name": "AI Edit 測試客戶",
    "email": "aiedit.test@example.com",
    "phone": "+852 9333 3333",
    "notes": None,
}


@dataclass
class Ctx:
    tenant_id: str = TENANT
    workspace_id: str = "2cf88959-eb58-4146-8eec-f45131438c62"
    user_id: str = "00000000-0000-0000-0000-000000000000"


async def get_contact(db):
    await set_rls(db)  # commit resets transaction-scoped RLS context
    r = await db.execute(
        text("SELECT name, email, phone, notes FROM nexus_crm.contacts WHERE id=:id"),
        {"id": CONTACT_ID},
    )
    row = r.fetchone()
    return {"name": row[0], "email": row[1], "phone": row[2], "notes": row[3]}


async def set_rls(db):
    conn = await db.connection()
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": TENANT})


async def test_field(db, field: str, new_value: str, ctx) -> bool:
    """Draft + execute a single-field update, verify DB reflects it."""
    print(f"\n=== FIELD: {field} → {new_value!r} ===")
    params = {"contact_id": CONTACT_ID, field: new_value}

    # 1. draft mode — should validate
    draft = await _update_contact_draft(ctx, params, db, mode="draft")
    ok = draft.get("validated") is True and draft.get("changes", {}).get(field) == new_value
    print(f"  draft: validated={draft.get('validated')} changes={draft.get('changes')}")
    if not ok:
        print(f"  ✗ DRAFT FAILED: {draft.get('errors')}")
        await db.rollback()
        return False

    # 2. execute mode via the confirm path: params IS the preview dict
    preview = {
        "action": "update_contact",
        "contact_id": draft["contact_id"],
        "current": draft.get("current"),
        "changes": draft["changes"],
        "validated": True,
    }
    result = await _update_contact_draft(ctx, preview, db, mode="execute")
    if result.get("errors"):
        print(f"  ✗ EXECUTE FAILED: {result.get('errors')}")
        await db.rollback()
        return False
    await db.commit()
    print(f"  execute: changes={result.get('changes')}")

    # 3. verify DB
    after = await get_contact(db)
    print(f"  DB after: {after}")
    if after[field] != new_value:
        print(f"  ✗ DB MISMATCH: {field} = {after[field]!r} (expected {new_value!r})")
        return False
    print(f"  ✅ {field} update verified in DB")
    return True


async def test_name_fallback(db, ctx) -> bool:
    """AI sometimes passes name/email instead of UUID — fallback must resolve."""
    print("\n=== FALLBACK: resolve by NAME ===")
    draft = await _update_contact_draft(
        ctx, {"contact_id": "AI Edit 測試客戶", "phone": "+852 9555 5555"}, db, mode="draft"
    )
    ok = draft.get("validated") is True and draft["contact_id"] == CONTACT_ID
    print(f"  name→uuid: validated={draft.get('validated')} resolved={draft.get('contact_id')}")
    if not ok:
        print(f"  ✗ NAME FALLBACK FAILED: {draft.get('errors')}")
        await db.rollback()
        return False

    print("=== FALLBACK: resolve by EMAIL ===")
    draft2 = await _update_contact_draft(
        ctx, {"contact_id": "aiedit.test@example.com", "notes": "email-resolve test"}, db, mode="draft"
    )
    ok2 = draft2.get("validated") is True and draft2["contact_id"] == CONTACT_ID
    print(f"  email→uuid: validated={draft2.get('validated')} resolved={draft2.get('contact_id')}")
    if not ok2:
        print(f"  ✗ EMAIL FALLBACK FAILED: {draft2.get('errors')}")
        await db.rollback()
        return False

    # execute the email-resolve draft so notes lands in DB
    preview = {
        "action": "update_contact",
        "contact_id": draft2["contact_id"],
        "current": draft2.get("current"),
        "changes": draft2["changes"],
        "validated": True,
    }
    await _update_contact_draft(ctx, preview, db, mode="execute")
    await db.commit()
    after = await get_contact(db)
    print(f"  DB notes after email-resolve: {after['notes']!r}")
    return after["notes"] == "email-resolve test"


async def test_invalid_target_rejected(db, ctx) -> bool:
    """Confirm of an invalid target must NOT mark executed (guard)."""
    print("\n=== GUARD: invalid contact_id must not execute ===")
    params = {"contact_id": "請提供聯絡人 UUID", "email": "x@y.com"}
    draft = await _update_contact_draft(ctx, params, db, mode="draft")
    print(f"  draft: validated={draft.get('validated')} errors={draft.get('errors')}")
    if draft.get("validated"):
        print("  ✗ draft unexpectedly validated")
        await db.rollback()
        return False

    # execute with the same bad params (simulating confirm on a bad action)
    result = await _update_contact_draft(ctx, params, db, mode="execute")
    has_errors = bool(result.get("errors"))
    print(f"  execute: errors={result.get('errors')}")
    await db.rollback()
    return has_errors


async def main() -> None:
    ctx = Ctx()
    async with async_session() as db:
        await set_rls(db)
        before = await get_contact(db)
        print("BEFORE:", before)

        results = {}
        # Every editable field
        results["name"] = await test_field(db, "name", "AI Edit 測試客戶 v2", ctx)
        results["email"] = await test_field(db, "email", "v2.aiedit@example.com", ctx)
        results["phone"] = await test_field(db, "phone", "+852 9777 7777", ctx)
        results["notes"] = await test_field(db, "notes", "呢個係測試 notes 內容", ctx)

        # Multiple fields in one call (name + email together)
        print("\n=== MULTI-FIELD: name + email + phone ===")
        multi = await _update_contact_draft(
            ctx,
            {"contact_id": CONTACT_ID, "name": "AI Edit 測試客戶", "email": "aiedit.test@example.com", "phone": "+852 9333 3333"},
            db,
            mode="draft",
        )
        print(f"  draft: validated={multi.get('validated')} changes={multi.get('changes')}")
        mp = {
            "action": "update_contact",
            "contact_id": multi["contact_id"],
            "current": multi.get("current"),
            "changes": multi["changes"],
            "validated": True,
        }
        await _update_contact_draft(ctx, mp, db, mode="execute")
        await db.commit()
        after_multi = await get_contact(db)
        results["multi"] = after_multi["name"] == "AI Edit 測試客戶" and after_multi["email"] == "aiedit.test@example.com" and after_multi["phone"] == "+852 9333 3333"
        print(f"  DB after multi: {after_multi}")

        # Fallbacks
        results["name_fallback"] = await test_name_fallback(db, ctx)
        results["guard"] = await test_invalid_target_rejected(db, ctx)

        print("\n" + "=" * 50)
        print("RESULTS:")
        all_ok = True
        for k, v in results.items():
            print(f"  {'✅' if v else '❌'} {k}")
            all_ok = all_ok and v
        print("=" * 50)
        print("ALL PASS" if all_ok else "SOME FAILED")
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())

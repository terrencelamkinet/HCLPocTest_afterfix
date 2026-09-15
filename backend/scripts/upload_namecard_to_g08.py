#!/usr/bin/env python3
"""IM → G08 Name Card upload helper.

Detects whether an image is a namecard (quick tesseract scan), then uploads
it to G08's name-card pipeline (OCR → auto create/link Contact & Company).

Usage:
  python3 upload_namecard_to_g08.py --detect /path/to/image.jpg
  python3 upload_namecard_to_g08.py --upload /path/to/image.jpg

Exit codes: 0 = success, 1 = not a namecard (detect mode), 2 = error
"""
import sys, os, json, subprocess, tempfile, uuid
from pathlib import Path

# --- Constants -----------------------------------------------------------
KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
TERRENCE_USER = "a77d12c5-c02f-4335-88b2-1f293a74fe6f"
API_BASE = os.environ.get("G08_API_BASE", "http://localhost:8001")
BACKEND_DIR = Path(__file__).resolve().parents[1]

# Use the server's OCR module so script + API share identical logic
sys.path.insert(0, str(BACKEND_DIR))
from app.services.namecard_ocr import ocr_image as ocr_text  # noqa: E402
KEY_PATH = BACKEND_DIR / "keys" / "private.pem"

# Namecard signature patterns (lowercase)
NAMECARD_HINTS = [
    r"@",           # email
    r"\btel[:.]?\s*\d", r"\bphone[:.]?\s*\d", r"\bmob[:.]?\s*\d",  # phone
    r"\+?\d{8,}",   # 8+ digit phone-like
    r"\b(limited|ltd|inc|corp|company|公司|集團|科技|国际|國際)\b",
    r"\b(www\.|http|https)\b",
    r"\b(manager|director|sales|engineer|consultant|officer|總監|經理|主任)\b",
]

NAMECARD_EXCLUDE = [  # things that look like text but are NOT namecards
    "screenshot", "截圖", "whatsapp", "telegram", "instagram", "facebook",
]


def make_token() -> str:
    """Short-lived internal JWT (same pattern as telegram_inbound)."""
    from datetime import datetime, timezone, timedelta
    from jose import jwt
    payload = {
        "sub": TERRENCE_USER,
        "email": "im-bridge@internal",
        "role": "admin",
        "tenant_id": KINETIX_TENANT,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=2),
    }
    return jwt.encode(payload, KEY_PATH.read_text(), algorithm="RS256")


def is_namecard(text: str) -> bool:
    """Heuristic: namecards have email/phone + company/job signals."""
    import re
    low = text.lower()
    if len(low.strip()) < 15:
        return False
    if any(x in low for x in NAMECARD_EXCLUDE):
        return False
    hits = sum(1 for pat in NAMECARD_HINTS if re.search(pat, low))
    has_email_or_phone = bool(re.search(r"@", low)) or bool(re.search(r"\btel[:.]?\s*\d|\+?\d{8,}", low))
    has_org = bool(re.search(r"\b(limited|ltd|inc|公司|集團|科技)\b", low)) or bool(
        re.search(r"\b(manager|director|sales|engineer|consultant|總監|經理|主任)\b", low))
    return has_email_or_phone and has_org and hits >= 2


def upload(image_path: str) -> dict:
    import httpx
    token = make_token()
    with open(image_path, "rb") as f:
        r = httpx.post(
            f"{API_BASE}/api/v1/crm/name-cards/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (Path(image_path).name, f, "image/*")},
            timeout=90,
        )
    if r.status_code != 201:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    d = r.json()
    contact = d.get("contact") or {}
    parsed = d.get("parsed_data") or {}
    review_cands = d.get("review_candidates") or []
    return {
        "ok": True,
        "status": d.get("status", "unknown"),
        "name_card_id": str(d.get("id", "")),
        "dedup_status": d.get("dedup_status") or parsed.get("dedup_status") or "",
        "contact_name": contact.get("name") or parsed.get("name"),
        "email": contact.get("email") or parsed.get("email"),
        "company": contact.get("company_name") or parsed.get("company"),
        "title": parsed.get("title"),
        "context_note": parsed.get("context_note", ""),
        "context_match": parsed.get("context_match", ""),
        "review_candidates": [{
            "contact_id": c.get("contact_id"),
            "confidence": c.get("confidence"),
            "reason": c.get("reason", ""),
            "name": c.get("name"), "email": c.get("email"),
            "phone": c.get("phone"), "company": c.get("company"),
            "title": c.get("title"),
        } for c in review_cands],
    }


def resolve(name_card_id: str, action: str) -> dict:
    """User decision on a review-status card: overwrite | keep_both."""
    import httpx
    if action not in ("overwrite", "keep_both"):
        return {"ok": False, "error": f"action must be overwrite|keep_both, got {action}"}
    token = make_token()
    r = httpx.post(
        f"{API_BASE}/api/v1/crm/name-cards/{name_card_id}/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": action},
        timeout=60,
    )
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    d = r.json()
    return {
        "ok": True,
        "status": d.get("status", "unknown"),
        "name_card_id": str(d.get("id", "")),
        "contact_name": (d.get("parsed_data") or {}).get("name"),
        "action": action,
    }


def main():
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "--resolve":
        card_id, action = args[1], args[2]
        print(json.dumps(resolve(card_id, action)))
        sys.exit(0)
    if len(args) < 2 or args[0] not in ("--detect", "--upload"):
        print(json.dumps({"ok": False, "error": "usage: upload_namecard_to_g08.py --detect|--upload <image> | --resolve <card_id> <overwrite|keep_both>"}))
        sys.exit(2)
    mode, img = args[0], args[1]
    if not os.path.isfile(img):
        print(json.dumps({"ok": False, "error": f"file not found: {img}"}))
        sys.exit(2)

    text = ocr_text(img)
    card = is_namecard(text)

    if mode == "--detect":
        print(json.dumps({
            "ok": True,
            "is_namecard": card,
            "ocr_preview": " ".join(text.split())[:300],
        }))
        sys.exit(0 if card else 1)

    # --upload
    if not card:
        print(json.dumps({"ok": False, "is_namecard": False,
                          "error": "Image does not look like a namecard (OCR found no card signature)"}))
        sys.exit(1)
    print(json.dumps(upload(img)))


if __name__ == "__main__":
    main()

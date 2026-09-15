"""Tests: @mention → note_links 抽取層（spec §6/§7/§15）

純函數測試，唔需要 DB —— 對應 AI_AGENT_CRM_JSON_PostgreSQL_Configuration_Guide:
  §15-3  同一 object 被 @ 3 次 → 一行 + mention_count = 3
  §15-6  rename 後 label 要更新，objectId 關係不變
  §15-7  壞 JSON／未知 node type 要 reject（呢度 = 抽唔到就唔好 raise）
"""

from app.services.note_mentions import MENTION_ENTITY_TABLES, extract_mentions


def _chip(entity_type: str, entity_id: str, label: str) -> str:
    return (
        f'<span data-record-mention="true" data-entity-type="{entity_type}"'
        f' data-entity-id="{entity_id}" data-label="{label}" class="nxe-mention">@{label}</span>'
    )


CONTACT = "2153c94f-d488-4121-abf9-18b4f4da282d"
COMPANY = "75be68a5-1aa3-47c3-93cb-008e26809199"


def test_empty_and_none_input():
    assert extract_mentions(None) == []
    assert extract_mentions("") == []
    assert extract_mentions("<p>純文字，冇 mention</p>") == []


def test_single_mention():
    html = f"<p>傾咗 {_chip('contact', CONTACT, 'Terrence')} 嘅事</p>"
    rows = extract_mentions(html)
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "contact"
    assert rows[0]["entity_id"] == CONTACT
    assert rows[0]["label"] == "Terrence"
    assert rows[0]["mention_count"] == 1


def test_same_object_three_times_collapses_to_one_row():
    """spec §15-3"""
    html = "<p>" + _chip("contact", CONTACT, "Terrence") * 3 + "</p>"
    rows = extract_mentions(html)
    assert len(rows) == 1
    assert rows[0]["mention_count"] == 3


def test_multiple_objects_and_types():
    html = (
        "<p>" + _chip("contact", CONTACT, "Terrence")
        + " 喺 " + _chip("company", COMPANY, "Terrence_PRO")
        + " 做嘢，" + _chip("contact", CONTACT, "Terrence") + "</p>"
    )
    rows = extract_mentions(html)
    by_key = {(r["entity_type"], r["entity_id"]): r for r in rows}
    assert len(rows) == 2
    assert by_key[("contact", CONTACT)]["mention_count"] == 2
    assert by_key[("company", COMPANY)]["mention_count"] == 1


def test_label_follows_latest_non_empty_value():
    """spec §15-6：rename 後 label 更新（objectId 不變）"""
    html = "<p>" + _chip("contact", CONTACT, "舊名") + _chip("contact", CONTACT, "新名") + "</p>"
    rows = extract_mentions(html)
    assert len(rows) == 1
    assert rows[0]["label"] == "新名"
    assert rows[0]["mention_count"] == 2


def test_malformed_and_hostile_html_never_raises():
    """spec §15-7：壞 HTML 唔可以令存筆記爆"""
    assert extract_mentions("<p><span data-record-mention") == []
    assert extract_mentions("</span></p><script>alert(1)</script>") == []
    # 亂 attribute 都要抽到 entity_type/entity_id（label 可以係空）
    rows = extract_mentions('<span data-record-mention data-entity-type="contact" data-entity-id="' + CONTACT + '">')
    assert len(rows) == 1 and rows[0]["label"] == ""


def test_skips_chip_without_id_or_type():
    assert extract_mentions('<span data-record-mention data-entity-type="contact"></span>') == []
    assert extract_mentions(f'<span data-record-mention data-entity-id="{CONTACT}"></span>') == []
    # 非 span（或者冇 data-record-mention）一律唔算
    assert extract_mentions(f'<div data-record-mention data-entity-type="contact" data-entity-id="{CONTACT}"></div>') == []


def test_unknown_entity_type_is_extracted_but_listed_in_allowlist_gate():
    """抽出嚟先（俾 sync 判斷），未知 type 唔應該被白名單污染"""
    rows = extract_mentions(_chip("unknown_thing", CONTACT, "X"))
    assert len(rows) == 1
    assert "unknown_thing" not in MENTION_ENTITY_TABLES


def test_allowlist_covers_mention_picker_types():
    """mention picker（/crm/search types）嘅 5 個 type 一定要支援"""
    for t in ("contact", "company", "project", "task", "touchpoint"):
        assert t in MENTION_ENTITY_TABLES

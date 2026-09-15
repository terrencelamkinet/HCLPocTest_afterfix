"""Notes V2 — @mention → nexus_crm.note_links 同步（server-side 唯一真相）

設計原則跟 AI_AGENT_CRM_JSON_PostgreSQL_Configuration_Guide §5.4 / §7 / §15：

1. **Link 一定由 server 驗證過嘅 canonical content 推導** —— 唔信 client 送嘅
   links array（就算前端已經有 extractRecordMentions，server 都要自己抽一次）。
2. **每個 reference 都要驗**：entity_type 白名單 → UUID 合法 → 同 tenant 存在 → 未刪。
3. **同一個 transaction 內做完**：抽 → 驗 → 刪走唔再存在嘅 → upsert 現有嘅。
   （caller 負責 commit / rollback，本 module 唔會自己 commit。）
4. **只刪 source='mention'** —— 人手加 link（+Link record）／AI suggestion 確認嘅
   'manual' row 永久保留，唔會被自動 sync 洗走。

實測背景（2026-09-13）：note_links 表存在但 count = 0 —— @mention 一直只係畫 chip，
冇建立過任何關係。呢個 module 就係補呢個缺口。
"""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)

# mention 支援嘅 entity type → 對應表。
# 同 crm.py 嘅 _NOTE_LINK_TYPES 一致（contact/company/project/task/touchpoint 由
# /crm/search mention picker 出；deal/note 由人手 +Link 出）。
MENTION_ENTITY_TABLES: dict[str, str] = {
    "contact": "contacts",
    "company": "companies",
    "project": "projects",
    "task": "tasks",
    "touchpoint": "touchpoints",
    "deal": "deals",
    "note": "notes",
}

# 有 deleted_at 欄嘅表（soft delete）→ 驗證時要多一個條件。
_TABLES_WITH_DELETED_AT = {"notes"}

# 一次性檢查：note_links 有冇 migration 030 加嘅欄（source / mention_count）。
# 未跑 migration 嘅環境（例如 prod 未 apply）→ sync 靜默跳過，**唔會令存筆記 500**。
# 每次改動 schema 前呢種「向後兼容」係必須：code 可以先行，schema 後補。
_READY: bool | None = None


async def mentions_ready(db: Any) -> bool:
    """migration 030 嘅欄位（source / mention_count）存唔存在。

    未存在 → 呼叫方應該跳過 mention 相關嘅寫入（唔好阻住存筆記）。
    """
    global _READY
    if _READY is not None:
        return _READY
    try:
        rows = (await db.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'nexus_crm' AND table_name = 'note_links'"
            "   AND column_name IN ('source', 'mention_count')"
        ))).scalars().all()
        _READY = len(set(rows)) == 2
    except Exception:  # noqa: BLE001
        logger.exception("note_mentions: column check failed")
        return False
    if not _READY:
        logger.warning(
            "note_mentions: migration 030_note_link_mentions.sql 未套用 → "
            "@mention 同步暫時停用（筆記照存，只係唔會建 link）"
        )
    return _READY


class _MentionHTMLParser(HTMLParser):
    """抽 <span data-record-mention data-entity-type data-entity-id data-label>。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "span":
            return
        a = dict(attrs)
        if "data-record-mention" not in a:
            return
        et = (a.get("data-entity-type") or "").strip().lower()
        eid = (a.get("data-entity-id") or "").strip()
        if et and eid:
            self.rows.append({
                "entity_type": et,
                "entity_id": eid,
                "label": (a.get("data-label") or "").strip(),
            })


def extract_mentions(html: str | None) -> list[dict[str, Any]]:
    """由筆記 HTML 抽 @mention，同一 object 去重並數出現次數。

    Returns: [{"entity_type","entity_id","label","mention_count"}, ...]
    壞 HTML 唔會 raise（fail-open：筆記內容照存，只係抽唔到 link）。
    """
    if not html:
        return []
    parser = _MentionHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — 壞 HTML 唔應該拖冧 save
        logger.warning("note_mentions: HTML parse failed, skip link extraction")
        return []

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in parser.rows:
        key = (row["entity_type"], row["entity_id"])
        if key in merged:
            merged[key]["mention_count"] += 1
            if row["label"]:  # 用最新一次非空 label（rename 後 canonical 化）
                merged[key]["label"] = row["label"]
        else:
            merged[key] = {**row, "mention_count": 1}
    return list(merged.values())


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def _validate_refs(
    db: Any, tenant_id: Any, mentions: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """驗 mention 指向嘅 object：type 白名單 → UUID → 同 tenant 存在 → 未刪。

    Returns: (valid_rows, rejected_reasons)
    """
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []

    for m in mentions:
        et, eid = m["entity_type"], m["entity_id"]
        table = MENTION_ENTITY_TABLES.get(et)
        if not table:
            rejected.append(f"unsupported_type:{et}")
            continue
        if not _is_uuid(eid):
            rejected.append(f"bad_uuid:{et}:{eid[:36]}")
            continue

        # RLS 都會再擋一層（app.tenant_id），呢度嘅 tenant_id 條件係第二重保險。
        sql = (
            f"SELECT 1 FROM nexus_crm.{table}"
            " WHERE tenant_id = :t AND id = :i"
            + (" AND deleted_at IS NULL" if table in _TABLES_WITH_DELETED_AT else "")
            + " LIMIT 1"
        )
        try:
            hit = (await db.execute(
                text(sql), {"t": str(tenant_id), "i": eid}
            )).first()
        except Exception:  # noqa: BLE001 — 單一 type query 失敗唔應該阻住個 save
            logger.exception("note_mentions: validate query failed for %s", table)
            rejected.append(f"validate_error:{et}")
            continue
        if hit:
            valid.append(m)
        else:
            rejected.append(f"not_found_or_other_tenant:{et}:{eid}")
    return valid, rejected


async def sync_note_mentions(
    db: Any,
    *,
    tenant_id: Any,
    note_id: Any,
    html: str | None,
) -> dict[str, int]:
    """由 note content 抽 @mention 並同步 note_links（caller 嘅 transaction 內行）。

    Returns: {"added","updated","removed","rejected","mentions"} 方便測試／log。
    """
    summary = {"added": 0, "updated": 0, "removed": 0, "rejected": 0, "mentions": 0}

    # 向後兼容：migration 未跑（例如 prod 未 apply）→ 靜默跳過，唔好阻住存筆記。
    if not await mentions_ready(db):
        return summary

    mentions = extract_mentions(html)
    summary["mentions"] = len(mentions)
    valid, rejected = await _validate_refs(db, tenant_id, mentions)
    summary["rejected"] = len(rejected)
    if rejected:
        logger.info("note_mentions: note=%s rejected=%s", note_id, rejected)
    if not valid:
        # 冇有效 mention 都要清走之前抽落嘅（用戶可能啱啱刪晒所有 @）
        pass

    keep = {(m["entity_type"], m["entity_id"]) for m in valid}

    # ── 1. 刪走唔再 mention 嘅（只限 source='mention'）──
    existing = (await db.execute(
        text(
            "SELECT id::text AS id, entity_type, entity_id::text AS entity_id"
            " FROM nexus_crm.note_links"
            " WHERE note_id = :n AND source = 'mention'"
        ),
        {"n": str(note_id)},
    )).mappings().all()
    stale_ids = [
        r["id"] for r in existing
        if (r["entity_type"], r["entity_id"]) not in keep
    ]
    if stale_ids:
        await db.execute(
            text("DELETE FROM nexus_crm.note_links WHERE id = ANY(:ids)"),
            {"ids": stale_ids},
        )
        summary["removed"] = len(stale_ids)

    # ── 2. upsert 現有嘅 ──
    existing_keys = {(r["entity_type"], r["entity_id"]) for r in existing}
    for m in valid:
        await db.execute(
            text(
                "INSERT INTO nexus_crm.note_links"
                " (tenant_id, note_id, entity_type, entity_id, label, source, mention_count)"
                " VALUES (:t, :n, :et, :eid, :label, 'mention', :cnt)"
                " ON CONFLICT (note_id, entity_type, entity_id) DO UPDATE"
                "   SET label = EXCLUDED.label,"
                "       mention_count = EXCLUDED.mention_count,"
                "       source = CASE WHEN nexus_crm.note_links.source = 'manual'"
                "                     THEN 'manual' ELSE 'mention' END"
            ),
            {
                "t": str(tenant_id),
                "n": str(note_id),
                "et": m["entity_type"],
                "eid": m["entity_id"],
                "label": m["label"] or None,
                "cnt": m["mention_count"],
            },
        )
        if (m["entity_type"], m["entity_id"]) in existing_keys:
            summary["updated"] += 1
        else:
            summary["added"] += 1

    return summary

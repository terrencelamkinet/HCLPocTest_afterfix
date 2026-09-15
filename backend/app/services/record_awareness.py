"""Record Awareness scanner — 掃描新加 CRM records 缺漏，生成 AI 主動提問。

缺漏偵測規則（最近 RECORD_SCAN_DAYS 日新加嘅 records）：
1. Contact 冇電話又冇 email     → 「補聯絡資料」
2. Company 冇電話又冇網址       → 「補公司資料」
3. Touchpoint 冇 description     → 「寫低重點」
4. Project 冇 deadline           → 「設死線」

Dedup：同 context_id + 同 source + 已存在 → 唔重複生成。
同 calendar_awareness 共用 pending_ai_questions 表，context_type 區分
（contact | company | touchpoint | project），source 前綴 record_。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai.pending_question import PendingAIQuestion
from app.models.crm import Company, Contact, Project, Touchpoint

log = logging.getLogger(__name__)

RECORD_SCAN_DAYS = 7
RECORD_PENDING_LIMIT = 6
# 新加入但可能係系統種子/範例 — 跳過，避免問廢問題
SKIP_NAME_HINTS = ("sample", "test", "demo", "範例", "測試", "樣本")


def _is_skip(name: str | None) -> bool:
    if not name:
        return False
    low = name.lower()
    return any(h in low for h in SKIP_NAME_HINTS)


async def scan_record_gaps(
    db: AsyncSession,
    user_id,
    tenant_id,
) -> list[PendingAIQuestion]:
    """掃描最近 7 日新加嘅 CRM records 缺漏，生成 pending questions（有 dedup）。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=RECORD_SCAN_DAYS)

    existing = (
        await db.execute(
            select(PendingAIQuestion).where(
                PendingAIQuestion.tenant_id == tenant_id,
                PendingAIQuestion.user_id == user_id,
            )
        )
    ).scalars().all()
    existing_keys = {
        (q.context_type, str(q.context_id), q.source) for q in existing
    }

    created: list[PendingAIQuestion] = []
    # ⚠️ quota 只計 pending rows — answered/dismissed 唔應該佔額（2026-08-28 修正）
    pending_count = sum(1 for q in existing if q.status == "pending")

    def _add(ctype: str, cid, ctitle: str, question: str, answers: list[str], source: str):
        nonlocal pending_count
        if pending_count >= RECORD_PENDING_LIMIT:
            return
        key = (ctype, str(cid), source)
        if key in existing_keys:
            return
        q = PendingAIQuestion(
            user_id=user_id,
            tenant_id=tenant_id,
            question=question,
            context_type=ctype,
            context_id=cid,
            context_title=ctitle,
            suggested_answers=answers,
            source=source,
        )
        db.add(q)
        created.append(q)
        existing_keys.add(key)
        pending_count += 1

    # ── 1. Contacts — 新加，冇電話又冇 email ──
    contacts = (
        await db.execute(
            select(Contact)
            .where(
                Contact.tenant_id == tenant_id,
                Contact.created_at >= since,
                or_(Contact.owner_id == user_id, Contact.owner_id.is_(None)),
            )
            .order_by(Contact.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    for c in contacts:
        name = (c.name or "").strip()
        if _is_skip(name):
            continue
        has_phone = bool((c.phone or "").strip() or (c.numbers or []))
        has_email = bool((c.email or "").strip())
        if has_phone and has_email:
            continue
        missing, answers = [], []
        if not has_phone:
            missing.append("電話")
            answers.append("加電話：")
        if not has_email:
            missing.append("email")
            answers.append("加 email：")
        answers.append("唔使")
        _add(
            "contact", c.id, name,
            f"《{name}》新加入但冇{'同'.join(missing)}，要補齊嗎？",
            answers,
            "record_contact_contact",
        )

    # ── 2. Companies — 新加，冇電話又冇網址 ──
    companies = (
        await db.execute(
            select(Company)
            .where(
                Company.tenant_id == tenant_id,
                Company.created_at >= since,
                or_(Company.owner_id == user_id, Company.owner_id.is_(None)),
            )
            .order_by(Company.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    for co in companies:
        name = (co.name or "").strip()
        if _is_skip(name):
            continue
        missing, answers = [], []
        if not (co.phone or "").strip():
            missing.append("電話")
            answers.append("加電話：")
        if not (co.website or "").strip():
            missing.append("網址")
            answers.append("加網址：")
        if not missing:
            continue
        answers.append("唔使")
        _add(
            "company", co.id, name,
            f"《{name}》新加入但冇{'同'.join(missing)}，要補嗎？",
            answers,
            "record_company_profile",
        )

    # ── 3. Touchpoints — 新加，冇 description/notes ──
    touchpoints = (
        await db.execute(
            select(Touchpoint)
            .where(
                Touchpoint.tenant_id == tenant_id,
                Touchpoint.created_at >= since,
                or_(Touchpoint.created_by == user_id, Touchpoint.created_by.is_(None)),
            )
            .order_by(Touchpoint.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    for tp in touchpoints:
        title = (tp.title or "").strip()
        if _is_skip(title) or (tp.description or "").strip():
            continue
        _add(
            "touchpoint", tp.id, title,
            f"《{title}》touchpoint 冇記錄重點，要寫低嗎？",
            ["加備註：", "唔使"],
            "record_touchpoint_notes",
        )

    # ── 4. Projects — 新加，冇 deadline ──
    projects = (
        await db.execute(
            select(Project)
            .where(
                Project.tenant_id == tenant_id,
                Project.created_at >= since,
                or_(
                    Project.sales_owner_id == user_id,
                    Project.project_manager_id == user_id,
                    Project.sales_owner_id.is_(None),
                    Project.project_manager_id.is_(None),
                ),
            )
            .order_by(Project.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    for p in projects:
        name = (p.name or "").strip()
        if _is_skip(name) or p.deadline is not None:
            continue
        _add(
            "project", p.id, name,
            f"《{name}》新 project 未設 deadline，要加嗎？",
            ["加 deadline：", "唔使"],
            "record_project_deadline",
        )

    if created:
        await db.flush()
        log.info("record_awareness: created %d pending questions for user %s", len(created), user_id)
    return created

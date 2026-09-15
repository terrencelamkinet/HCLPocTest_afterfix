"""Calendar Awareness scanner — 掃描日程缺漏，生成 AI 主動提問。

缺漏偵測規則（針對未來 7 日嘅 calendar events）：
1. meeting 冇 location          → 「《title》未設地點，要加嗎？」
2. meeting 冇 description       → 「《title》冇 agenda，要寫低準備事項嗎？」
3. 時間重疊（同日兩個 event 撞） → 衝突提示（補 briefing 唔覆蓋嘅時段）

Dedup：同 context_id + 同 source + status=pending 已存在 → 唔重複生成。
每人最多 PENDING_LIMIT 條未回覆問題。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai.pending_question import PendingAIQuestion
from app.models.crm import ProjectCalendarEvent, Touchpoint

log = logging.getLogger(__name__)

PENDING_LIMIT = 5
SCAN_DAYS = 7
MEETING_TYPES = ("meeting", "milestone", "reminder")
# 假期/私人 events 唔需要問地點/agenda（AL、年假、生日、假期等）
SKIP_TITLE_HINTS = ("annual leave", "al ", "年假", "假期", "leave", "holiday", "birthday", "放假")
# 見面活動 hint — 呢啲 event 有機會要記錄 touchpoint（meeting/拜訪/飯局等）
MEETING_HINTS = (
    "meeting", "會議", "見面", "拜訪", "visit", "onsite", "briefing", "workshop",
    "lunch", "dinner", "聚會", "party", "discussion", "presentation", "傾", "review",
)


async def scan_calendar_gaps(
    db: AsyncSession,
    user_id,
    tenant_id,
) -> list[PendingAIQuestion]:
    """掃描用戶未來 7 日嘅日程缺漏，生成 pending questions（有 dedup）。"""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=SCAN_DAYS)

    events = (
        await db.execute(
            select(ProjectCalendarEvent)
            .where(
                ProjectCalendarEvent.tenant_id == tenant_id,
                ProjectCalendarEvent.owner_user_id == user_id,
                ProjectCalendarEvent.start >= now,
                ProjectCalendarEvent.start <= horizon,
            )
            .order_by(ProjectCalendarEvent.start)
        )
    ).scalars().all()

    if not events:
        return []

    # 現有問題（dedup 用 — 唔理 status：一條 event 一個問題只問一次）
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

    def _fmt_dt(dt) -> str:
        local = cast(datetime, dt).astimezone()
        return local.strftime("%m月%d日 %H:%M")

    for ev in events:
        if pending_count >= PENDING_LIMIT:
            break
        etype = (ev.event_type or "").lower()
        if etype not in MEETING_TYPES:
            continue
        title = (ev.title or "").strip()
        if any(h in title.lower() for h in SKIP_TITLE_HINTS):
            continue
        key = ("calendar", str(ev.id), "calendar_gap")
        if key in existing_keys:
            continue

        # 1. 冇 location
        if not (ev.location or "").strip():
            q = PendingAIQuestion(
                user_id=user_id,
                tenant_id=tenant_id,
                question=f"《{ev.title}》（{_fmt_dt(ev.start)}）未設地點，要加嗎？",
                context_type="calendar",
                context_id=ev.id,
                context_title=ev.title,
                suggested_answers=["加地點：辦公室", "加地點：客戶公司", "唔使"],
                source="calendar_gap",
            )
            db.add(q)
            created.append(q)
            existing_keys.add(key)
            pending_count += 1
            if pending_count >= PENDING_LIMIT:
                break

        # 2. 冇 description（agenda）
        if not (ev.description or "").strip():
            key2 = ("calendar", str(ev.id), "calendar_agenda")
            if key2 in existing_keys:
                continue
            q = PendingAIQuestion(
                user_id=user_id,
                tenant_id=tenant_id,
                question=f"《{ev.title}》（{_fmt_dt(ev.start)}）冇 agenda，要寫低準備事項嗎？",
                context_type="calendar",
                context_id=ev.id,
                context_title=ev.title,
                # v7.06: 帶「：」結尾 — frontend 會開 inline input 預填前綴
                suggested_answers=["寫低 agenda：", "唔使"],
                source="calendar_agenda",
            )
            db.add(q)
            created.append(q)
            existing_keys.add(key2)
            pending_count += 1

        # 3. 見面活動（meeting/拜訪/飯局）→ 問加入 Touchpoint 記錄聯繫人
        #    （v7.07 — 用戶要求：見 calendar 有新 event 就判斷係咪見面活動）
        key3 = ("calendar", str(ev.id), "event_touchpoint")
        if key3 not in existing_keys and pending_count < PENDING_LIMIT:
            is_meeting = etype == "meeting" or any(h in title.lower() for h in MEETING_HINTS)
            if is_meeting:
                # 已有同名 touchpoint（title 近似）→ 唔重複問
                has_tp = (
                    await db.execute(
                        select(Touchpoint.id)
                        .where(
                            Touchpoint.tenant_id == tenant_id,
                            Touchpoint.title.ilike(f"%{title}%"),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not has_tp:
                    q = PendingAIQuestion(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        question=f"《{ev.title}》（{_fmt_dt(ev.start)}）係見面活動，要加入 Touchpoint 同記錄聯繫人嗎？",
                        context_type="calendar",
                        context_id=ev.id,
                        context_title=ev.title,
                        suggested_answers=["加入 Touchpoint", "唔使"],
                        source="event_touchpoint",
                    )
                    db.add(q)
                    created.append(q)
                    existing_keys.add(key3)
                    pending_count += 1

    if created:
        await db.flush()
        log.info("calendar_awareness: created %d pending questions for user %s", len(created), user_id)
    return created


async def list_pending(
    db: AsyncSession,
    user_id,
    tenant_id,
    force_scan: bool = True,
) -> list[PendingAIQuestion]:
    """攞 pending questions（可選先掃描一次再攞 — calendar + record 缺漏）。"""
    # ⚠️ caller（get_pending_questions 嘅 _get_or_create）可能 commit 過 — GUC 係
    # transaction-local，commit 後消失。CRM + nexus_ai 表都係 FORCE RLS，先 re-set 先
    # scan/select（2026-08-28 實測：唔 set 會靜默 0 rows）
    await db.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
        {"t": str(tenant_id), "u": str(user_id)},
    )
    if force_scan:
        try:
            await scan_calendar_gaps(db, user_id, tenant_id)
            from app.services.record_awareness import scan_record_gaps
            await scan_record_gaps(db, user_id, tenant_id)
            await db.commit()
            # ⚠️ commit 後 transaction-local GUC 消失 — pending_ai_questions 係 FORCE RLS
            #（nexus_ai schema, user_isolation policy 要 app.user_id + app.tenant_id）
            # 唔 re-set 嘅話下面 select 會靜默 0 rows（2026-08-28 實測）
            await db.execute(
                text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
                {"t": str(tenant_id), "u": str(user_id)},
            )
        except Exception:
            log.exception("awareness scan failed — fallback to existing rows")
            await db.rollback()

    rows = (
        await db.execute(
            select(PendingAIQuestion)
            .where(
                PendingAIQuestion.tenant_id == tenant_id,
                PendingAIQuestion.user_id == user_id,
                PendingAIQuestion.status == "pending",
            )
            .order_by(PendingAIQuestion.created_at)
            .limit(PENDING_LIMIT + 5)
        )
    ).scalars().all()
    return list(rows)

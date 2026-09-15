"""AI Secretary Settings — per-user assistant preferences + channel credentials."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, SmallInteger, Text, DateTime, Time
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db import Base

DEFAULT_MODULES = ["weather", "today_tasks", "meetings", "project_status", "hot_leads", "stale_deals"]

# 每個 module 嘅深層選項預設值（spec: BRIEFING-MODULES-DEEP-OPTIONS.md）
# 冇設定嘅用戶（modules 係 string[] 舊格式）→ 全部用呢度嘅 default
DEFAULT_MODULE_OPTIONS: dict[str, dict] = {
    "weather": {"region": ["all_hk"], "unit": "celsius"},
    "today_tasks": {"scope": "both", "sort": "priority"},
    "meetings": {"range": "today_tomorrow", "type": "all"},
    "project_status": {"ownership": "mine", "count": "8"},
    "hot_leads": {"threshold": "70", "sort": "amount"},
    "stale_deals": {"days": "14", "sort": "staleness"},
    "overdue_followup": {"days": "7", "contact_type": "all"},
    "unread_messages": {"sources": ["gmail", "outlook"], "count": "8"},
    "birthday_reminders": {"range": "week", "type": "all"},
    "quote_tracking": {"statuses": ["draft", "sent", "expiring"], "sort": "valid_until"},
    "invoice_reminders": {"statuses": ["pending", "sent", "overdue"]},
    "team_updates": {"scope": "my_teams", "task_status": "all"},
    "calendar_conflicts": {"range": "today"},
    "news_industry": {"topics": ["tech", "finance", "logistics", "retail"], "lang": "both"},
    "traffic_commute": {"origin": "", "destination": "", "mode": "public", "mtr_line": "", "mtr_station": ""},
    "email_draft_review": {"status": "pending_review"},
    "sales_kpi": {"period": "month"},
    "customer_sentiment": {"days": "30", "show": "all"},
    "expense_reminders": {"status": "pending"},
    "personal_reminders": {"range": "today"},
    "bible_reading": {
        "book_selection": "ot_nt_mixed", "plan": "one_year",
        "chapters_per_push": "1", "push_time_mode": "greeting", "time_of_day": "morning",
        "translation": "cuv", "reminder": "enabled",
        "start_book": "創世記", "start_chapter": 1,
        "end_book": "啟示錄", "end_chapter": 0,
    },
}


def normalize_modules(value) -> dict[str, dict]:
    """向後兼容：modules 欄位可能係舊 string[] 或者新 dict 格式。

    - string[]（舊）: ["weather", "today_tasks"] → {"weather": {defaults}, ...}
    - dict（新）:     {"weather": {"region": [...]}} → 原樣（缺嘅 key 補 default）
    - None:          → {}
    """
    if value is None:
        return {}
    if isinstance(value, list):
        out: dict[str, dict] = {}
        for m in value:
            if isinstance(m, str):
                out[m] = dict(DEFAULT_MODULE_OPTIONS.get(m, {}))
        return out
    if isinstance(value, dict):
        out = {}
        for key, opts in value.items():
            if opts is None:
                opts = {}
            merged = dict(DEFAULT_MODULE_OPTIONS.get(key, {}))
            if isinstance(opts, dict):
                merged.update(opts)
            out[key] = merged
        return out
    return {}


def module_keys(value) -> list[str]:
    """Extract enabled module keys regardless of storage format."""
    return list(normalize_modules(value).keys())


DEFAULT_WORKDAYS = ["mon", "tue", "wed", "thu", "fri"]
DEFAULT_CHANNELS = {
    "whatsapp": {"connected": False, "enabled": False},
    "telegram": {"connected": False, "enabled": False},
    "email": {"connected": False, "enabled": False},
    "sms": {"connected": False, "enabled": False},
}
DEFAULT_GREETING_SLOTS = [
    {"key": "morning", "emoji": "🌅", "start": "07:00"},
    {"key": "afternoon", "emoji": "☀️", "start": "12:00"},
    {"key": "evening", "emoji": "🌆", "start": "18:00"},
    {"key": "lateNight", "emoji": "🌙", "start": "00:00"},
]

VALID_TONES = ("professional", "friendly", "direct", "encouraging", "formal")
VALID_LANGS = ("zh-HK", "zh-TW", "en")
VALID_CHANNELS = ("whatsapp", "telegram", "email", "sms")


class SecretarySettings(Base):
    """One row per user — replaces nexus-secretary-settings / nexus-working-hours / nexus-greeting-slots."""

    __tablename__ = "ai_secretary_settings"
    __table_args__ = {"schema": "nexus_ai"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    modules = Column(JSONB, default=lambda: list(DEFAULT_MODULES), nullable=False)
    workdays = Column(JSONB, default=lambda: list(DEFAULT_WORKDAYS), nullable=False)
    weekend_mute = Column(Boolean, default=True, nullable=False)
    strict_silence = Column(Boolean, default=True, nullable=False)
    calendar_awareness = Column(Boolean, default=True, nullable=False)
    tone = Column(String(20), default="professional", nullable=False)
    instructions = Column(Text, default="", nullable=False)
    lang_pref = Column(String(10), default="zh-HK", nullable=False)
    detail_level = Column(SmallInteger, default=2, nullable=False)
    channels = Column(JSONB, default=lambda: dict(DEFAULT_CHANNELS), nullable=False)

    work_start = Column(Time, default=lambda: _time("09:00"), nullable=False)
    work_end = Column(Time, default=lambda: _time("18:00"), nullable=False)
    greeting_slots = Column(JSONB, default=lambda: [dict(s) for s in DEFAULT_GREETING_SLOTS], nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ChannelCredential(Base):
    """Per-user OAuth tokens for messaging channels (reserved; encrypted at app level)."""

    __tablename__ = "ai_channel_credentials"
    __table_args__ = {"schema": "nexus_ai"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    access_token = Column(Text, default="")
    refresh_token = Column(Text, default="")
    external_id = Column(String(255), default="")
    connected_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _time(hhmm: str):
    h, m = hhmm.split(":")
    from datetime import time as dtime
    return dtime(int(h), int(m))

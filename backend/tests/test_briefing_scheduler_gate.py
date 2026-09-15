"""L2 unit tests for Daily Briefing scheduler — channel gate (IMDeliveryPref)
+ weekend_mute + quiet_hours + slot_off + PushLog audit.

Covers:
  - B: scheduler reads IMDeliveryPref as channel gate (enabled / slots / disabled)
  - C: weekend_mute actually mutes on Sat/Sun
  - quiet_hours window handling (incl. overnight 22:00-08:00)
  - missing pref row = Default ON (frictionless onboarding)
  - PushLog audit row written for every skip reason
"""
import asyncio
import pytest
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

sys.path.insert(0, "backend")

from app.services import briefing_scheduler as bs  # noqa: E402

HKT = timezone(timedelta(hours=8))
USER = NS(user_id="u1", tenant_id="t1")
_WED = datetime(2026, 9, 9, 10, 0, tzinfo=HKT)  # Wednesday 10:00 — 非週末、非 quiet hours


@pytest.fixture(autouse=True)
def _freeze_weekday(monkeypatch):
    """全部 gate test 固定喺星期三 10:00 HKT。

    原本 test 靠真實 _now_hkt()，令 weekend_mute 嘅結果取決於「跑 test 嗰日」
    （星期六跑就週末 mute）→ 非確定性。2026-09-12 修。
    個別 test（星期六 / quiet hours）自己再 override。
    """
    monkeypatch.setattr(bs, "_now_hkt", lambda: _WED)


def _pref(channel: str, **kw) -> NS:
    base = dict(
        enabled=True,
        slots={"morning": True, "noon": True, "evening": True},
        weekend_mute=True,
        quiet_hours={"start": "22:00", "end": "08:00"},
    )
    base.update(kw)
    return NS(tenant_id="t1", user_id="u1", channel=channel, **base)


ENABLED_CHANNELS = {
    "whatsapp": {"enabled": True, "connected": True},
    "telegram": {"enabled": True, "connected": True},
}


class _FakeDB:
    """AsyncSession double: delegates pref lookup by table name in SQL.

    SPEC v2 T6.1（2026-09-06 用戶拍板）：gate 嘅**單一 source of truth** 係
    ai_secretary_settings（channels + weekend_mute + workdays）。
    im_delivery_prefs 只保留 mapping，唔再係 gate（舊雙 source bug：
    UI 改 settings 但 gate 讀 prefs → 用戶設定冇效，9/6 實錘）。
    """

    def __init__(self, pref=None, existing_briefing=False, channels=None,
                 weekend_mute=True, workdays=None):
        self.pref = pref
        self.existing_briefing = existing_briefing
        # channels=None → SecretarySettings row missing (→ default all disabled)
        self.settings_channels = channels
        self.settings_weekend_mute = weekend_mute
        self.settings_workdays = workdays
        self.logs = []

    async def execute(self, stmt):
        sql = str(stmt)
        if "secretary_settings" in sql:
            if self.settings_channels is not None:
                s = NS(channels=self.settings_channels,
                       weekend_mute=self.settings_weekend_mute,
                       workdays=self.settings_workdays)
                return NS(scalar_one_or_none=lambda: s)
            return NS(scalar_one_or_none=lambda: None)
        if "im_delivery_prefs" in sql:
            val = self.pref
        elif "generated_briefings" in sql:
            val = 1 if self.existing_briefing else None
        else:
            val = None  # e.g. whatsapp_mappings / telegram_bot_mappings
        return NS(scalar_one_or_none=lambda: val)

    def add(self, o):
        self.logs.append(o)


def _run(coro):
    return asyncio.run(coro)


# ---- B: channel gate ----（2026-09-04 用戶 rule：冇 enable channel → 唔 push）
def test_no_settings_row_means_disabled():
    """新 rule：冇 settings row（新用戶未設定）→ DEFAULT_CHANNELS 全 disabled → 唔 push。

    舊行為（frictionless default ON）已由用戶 rule 取代：冇 enable TG/WA 就唔生成
    IM push，淨係 portal briefing。生成 gate 喺 SecretarySettings.channels。
    """
    db = _FakeDB(None)
    assert _run(bs._channel_gate(db, USER, "whatsapp", "morning")) == "disabled"


def test_channel_enabled_in_settings_allows():
    """用戶喺 AI app enable 咗 whatsapp → allow（IMDeliveryPref missing 都照推）"""
    db = _FakeDB(None)
    db.settings_channels = {"whatsapp": {"enabled": True, "connected": True}}
    assert _run(bs._channel_gate(db, USER, "whatsapp", "morning")) == ""


def test_channel_disabled_in_settings_blocks():
    """用戶喺 AI app 明確 disable 咗 telegram → disabled（即使 IMDeliveryPref ON）"""
    db = _FakeDB(_pref("telegram", enabled=True))
    db.settings_channels = {"telegram": {"enabled": False, "connected": True}}
    assert _run(bs._channel_gate(db, USER, "telegram", "morning")) == "disabled"


def test_pref_enabled_flag_is_not_a_gate():
    """SPEC v2 T6.1（2026-09-06 用戶拍板）：im_delivery_prefs.enabled 唔再係 gate。

    舊行為（pref enabled=False → "disabled"）已被單一 source of truth 取代：
    gate 只認 ai_secretary_settings.channels。呢個 test 鎖住新契約，
    防止有人重新引入雙 source（9/6 實錘：UI 改 settings 但 gate 讀 prefs → 設定冇效）。
    """
    db = _FakeDB(_pref("telegram", enabled=False), channels=ENABLED_CHANNELS)
    assert _run(bs._channel_gate(db, USER, "telegram", "morning")) == ""


def test_pref_slots_are_not_a_gate():
    """slot_off 已由 _channel_gate 移走（slot 判斷喺 generator 層）。

    prefs.slots 全 off 都唔會擋 gate — 同上面一樣鎖住「gate 只讀 settings」。
    """
    db = _FakeDB(_pref("whatsapp", slots={"morning": False, "noon": False, "evening": False}),
                 channels=ENABLED_CHANNELS)
    assert _run(bs._channel_gate(db, USER, "whatsapp", "evening")) == ""
    assert _run(bs._channel_gate(db, USER, "whatsapp", "lateNight")) == ""


# ---- C: weekend_mute ----
def test_weekend_mute_on_saturday():
    """weekend_mute 讀 ai_secretary_settings（唔再讀 im_delivery_prefs）。"""
    sat = datetime(2026, 8, 8, 10, 0, tzinfo=HKT)  # 2026-08-08 is Saturday
    assert bs._hkt_weekend(sat) is True
    db = _FakeDB(None, channels=ENABLED_CHANNELS, weekend_mute=True)
    orig = bs._now_hkt
    bs._now_hkt = lambda: sat
    try:
        assert _run(bs._channel_gate(db, USER, "whatsapp", "morning")) == "weekend_mute"
    finally:
        bs._now_hkt = orig


def test_weekday_not_muted_though_weekend_mute_on():
    """對照組：settings weekend_mute=True，但跑喺星期三（autouse 固定）→ 唔擋。"""
    db = _FakeDB(None, channels=ENABLED_CHANNELS, weekend_mute=True)
    assert _run(bs._channel_gate(db, USER, "whatsapp", "morning")) == ""


def test_workdays_include_saturday_means_no_mute():
    """settings.workdays 含 sat → 星期六照推（workdays 覆蓋硬性週末判斷）。"""
    sat = datetime(2026, 8, 8, 10, 0, tzinfo=HKT)
    db = _FakeDB(None, channels=ENABLED_CHANNELS, weekend_mute=True,
                 workdays=["mon", "tue", "wed", "thu", "fri", "sat"])
    orig = bs._now_hkt
    bs._now_hkt = lambda: sat
    try:
        assert _run(bs._channel_gate(db, USER, "whatsapp", "morning")) == ""
    finally:
        bs._now_hkt = orig


def test_weekend_mute_off_on_weekday():
    mon = datetime(2026, 8, 10, 10, 0, tzinfo=HKT)  # Monday
    assert bs._hkt_weekend(mon) is False


# ---- quiet_hours ----
def test_quiet_hours_overnight_blocks():
    now = datetime(2026, 8, 10, 23, 30, tzinfo=HKT)
    assert bs._in_quiet_hours(now, {"start": "22:00", "end": "08:00"}) is True


def test_quiet_hours_midday_allows():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=HKT)
    assert bs._in_quiet_hours(now, {"start": "22:00", "end": "08:00"}) is False


# ---- PushLog audit ----
def test_push_writes_skipped_log_for_disabled():
    """channels 冇 enable whatsapp → gate "disabled" → PushLog 記 skipped（audit）。"""
    db = _FakeDB(None, channels={"whatsapp": {"enabled": False, "connected": True}})
    ret = _run(bs._push_whatsapp(db, USER, "morning", "hi"))
    assert ret == "skipped"
    assert len(db.logs) == 1
    assert db.logs[0].status == "skipped"
    assert db.logs[0].reason == "disabled"


def test_all_pass_not_a_gate_block_just_no_mapping():
    """channels enabled + weekend_mute=False（星期三）→ gate 唔擋；
    淨係因為冇 whatsapp mapping 而 skipped，PushLog 唔應該有 gate reason。"""
    db = _FakeDB(None, channels=ENABLED_CHANNELS, weekend_mute=False)
    ret = _run(bs._push_whatsapp(db, USER, "morning", "hi"))
    assert ret == "skipped"  # no mapping → skipped, but NOT a gate block
    assert all(l.reason not in ("weekend_mute", "quiet_hours", "disabled") for l in db.logs)


# ---- T0.1: _already_processed（2026-09-04 dedup 語意擴展）----
class _PushLogDB:
    """Fake DB returning a PushLog row when the dedup query matches."""

    def __init__(self, matched: bool):
        self.matched = matched
        self.logs = []

    async def execute(self, stmt):
        return NS(scalar_one_or_none=lambda: NS(id="x") if self.matched else None)

    def add(self, o):
        self.logs.append(o)


def _mk_log(status: str):
    return NS(id="x", user_id="u1", slot="evening", status=status,
              sent_at=datetime(2026, 9, 3, 18, 0, tzinfo=HKT))


def test_already_processed_true_when_sent():
    """sent 記錄 → 已處理（舊行為保留）"""
    db = _PushLogDB(True)
    now = datetime(2026, 9, 3, 18, 15, tzinfo=HKT)
    assert _run(bs._already_processed(db, "u1", "evening", now)) is True


def test_already_processed_true_when_skipped():
    """skipped（gate 擋）→ 已處理 — 唔可以令下 tick regenerate（T0.1 核心）"""
    db = _PushLogDB(True)
    now = datetime(2026, 9, 3, 18, 30, tzinfo=HKT)
    assert _run(bs._already_processed(db, "u1", "evening", now)) is True


def test_already_processed_false_when_no_record():
    """全日冇記錄 → 未處理（第一次 tick 應該 generate）"""
    db = _PushLogDB(False)
    now = datetime(2026, 9, 3, 18, 0, tzinfo=HKT)
    assert _run(bs._already_processed(db, "u1", "evening", now)) is False


# ---- T0.1: generate_briefing dedup guard（generator 層，雙入口共用）----
class _CountingDB:
    """Counts generated_briefings queries — proves guard ran or not."""

    def __init__(self, existing: bool):
        self.existing = existing
        self.guard_queries = 0

    async def execute(self, stmt, *a, **kw):
        sql = str(stmt)
        if "generated_briefings" in sql:
            self.guard_queries += 1
            return NS(scalar_one_or_none=lambda: 1 if self.existing else None)
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def add(self, o):
        raise AssertionError("should not reach store")


def test_generate_briefing_guard_skips_when_exists():
    """今日該 slot 已存在 full briefing → 唔再生成（status=already_exists）"""
    from app.services.briefing_generator import generate_briefing
    import uuid as _uuid

    db = _CountingDB(existing=True)
    r = _run(generate_briefing(
        db, _uuid.uuid4(), _uuid.uuid4(), "evening",
    ))
    assert r["status"] == "already_exists"
    assert r["content"] == ""
    assert db.guard_queries == 1  # guard 行咗一次，之後冇再碰 DB


def test_generate_briefing_guard_absent_for_bible_only():
    """bible-only（only_modules 有值）唔行 guard — 唔誤擋 custom push"""
    from app.services.briefing_generator import generate_briefing
    import uuid as _uuid

    db = _CountingDB(existing=True)
    # only_modules 有值 → guard block 完全 skip → 第一下 DB 接觸係
    # _load_settings（secretary_settings 表），唔係 generated_briefings
    try:
        _run(generate_briefing(
            db, _uuid.uuid4(), _uuid.uuid4(), "morning",
            only_modules=["bible_reading"],
        ))
        raise AssertionError("should have raised on unexpected SQL")
    except AssertionError as e:
        assert "secretary_settings" in str(e) or "unexpected SQL" in str(e)
    assert db.guard_queries == 0  # guard 冇被觸發 ✅


# ---- T1.1: MODULE_CATEGORY v3（6 類骨架）+ MODULE_PRIORITY 完整性 ----
def test_module_category_v3_complete():
    """每個 module 有歸屬分類，冇 module 重複歸兩類（v2 6 類骨架）"""
    from app.services.briefing_generator import MODULE_CATEGORY, MODULE_TAGS

    valid_cats = {"notifications", "reminders", "schedule", "tasks_projects", "info", "bible"}
    assert set(MODULE_CATEGORY.values()) <= valid_cats
    # MODULE_TAGS 有 tag 嘅 module 全部有歸屬（tag 表 = 全部已知 module）
    for m in MODULE_TAGS:
        assert m in MODULE_CATEGORY, f"{m} 冇歸屬分類"
    # 冇 module 重複歸兩類（dict 天生唔重複 key — 呢個 check 保證冇 typo duplicate）
    assert len(MODULE_CATEGORY) == len(set(MODULE_CATEGORY.keys()))
    # v2 新分類有 module 入駐
    assert "meetings" in MODULE_CATEGORY and MODULE_CATEGORY["meetings"] == "schedule"
    assert "project_status" in MODULE_CATEGORY and MODULE_CATEGORY["project_status"] == "tasks_projects"
    assert "news_industry" in MODULE_CATEGORY and MODULE_CATEGORY["news_industry"] == "info"


def test_module_priority_complete():
    """每個 module 有 default P 級（bible 除外）；P 級只可以係 P0-P3"""
    from app.services.briefing_generator import MODULE_CATEGORY, MODULE_PRIORITY

    valid_p = {"P0", "P1", "P2", "P3"}
    for m, cat in MODULE_CATEGORY.items():
        if cat == "bible":
            continue  # 靈修唔受優先級影響
        assert m in MODULE_PRIORITY, f"{m} 冇 default P 級"
        assert MODULE_PRIORITY[m] in valid_p
    # bible 唔應該有 priority
    assert "bible_reading" not in MODULE_PRIORITY


# ---- T1.4: push 合併（schedule + tasks_projects → 5 條 message）----
class _PushDB:
    """Fake DB for _push_telegram: returns telegram mapping, no credentials."""

    def __init__(self):
        self.logs = []

    async def execute(self, stmt, *a, **kw):
        sql = str(stmt)
        if "telegram_mappings" in sql:
            return NS(scalar_one_or_none=lambda: NS(chat_id="123", bot_token="tok"))
        return NS(scalar_one_or_none=lambda: None)  # credentials / prefs etc.

    def add(self, o):
        self.logs.append(o)


def test_push_merges_schedule_and_tasks_into_5_messages():
    """T1.4: 6 類 → 5 條 message — schedule+tasks_projects 合併 header「📅📋 行程與待辦」"""
    cats = {
        "notifications": "⚠️ 衝突",
        "reminders": "🌦️ 天氣",
        "schedule": "📅 10:00 HKMA PoC\n📅 11:30 CS1466433",
        "tasks_projects": "✅ 今日完成\n📋 Tasks Summary\n🔴 返還圖書",
        "info": "📰 新聞",
        "bible": "📖 靈修",
    }
    sent = []

    async def fake_send(token, chat_id, styled):
        sent.append(styled)
        return {"ok": True}

    db = _PushDB()
    user = NS(user_id="u1", tenant_id="t1")

    orig_gate = bs._channel_gate
    orig_now = bs._now_hkt
    orig_send = bs.telegram_service.send_message
    bs._channel_gate = AsyncMock(return_value="")
    bs._now_hkt = lambda: datetime(2026, 9, 4, 5, 0, tzinfo=HKT)
    bs.telegram_service.send_message = fake_send
    try:
        status = _run(bs._push_telegram(db, user, "morning", "full content", cats))
        assert status == "sent"
        assert len(sent) == 5, f"expected 5 messages, got {len(sent)}"
        # 合併嗰條 header 係「📅📋 行程與待辦」
        merged_msgs = [s for s in sent if "行程與待辦" in s.split("\n")[0]]
        assert len(merged_msgs) == 1, "should have exactly 1 merged 📅📋 message"
        m = merged_msgs[0]
        assert "10:00 HKMA" in m and "返還圖書" in m, "merged msg should contain both schedule + tasks content"
    finally:
        bs._channel_gate = orig_gate
        bs._now_hkt = orig_now
        bs.telegram_service.send_message = orig_send


def test_push_no_merge_when_only_tasks():
    """得一類（tasks_projects 冇 schedule）→ 照原 label「📋 待辦/項目」"""
    cats = {
        "notifications": "⚠️ 衝突",
        "tasks_projects": "✅ 今日完成\n🔴 返還圖書",
        "info": "📰 新聞",
    }
    sent = []

    async def fake_send(token, chat_id, styled):
        sent.append(styled)
        return {"ok": True}

    db = _PushDB()
    user = NS(user_id="u1", tenant_id="t1")
    orig_gate, orig_now, orig_send = bs._channel_gate, bs._now_hkt, bs.telegram_service.send_message
    bs._channel_gate = AsyncMock(return_value="")
    bs._now_hkt = lambda: datetime(2026, 9, 4, 5, 0, tzinfo=HKT)
    bs.telegram_service.send_message = fake_send
    try:
        status = _run(bs._push_telegram(db, user, "morning", "full", cats))
        assert status == "sent"
        assert len(sent) == 3  # notifications + tasks_projects + info
        assert any("待辦/項目" in s.split("\n")[0] for s in sent)
        assert not any("行程與待辦" in s.split("\n")[0] for s in sent)
    finally:
        bs._channel_gate, bs._now_hkt, bs.telegram_service.send_message = orig_gate, orig_now, orig_send


# ---- T2.1: compute_p_level 邊界測試 ----
def test_p_level_task_boundaries():
    from app.ai.briefing_sources import compute_p_level
    from datetime import date as _date
    today = datetime(2026, 9, 4, 12, 0, tzinfo=HKT)

    def d(offset):
        return (datetime(2026, 9, 4, 0, 0, tzinfo=HKT) + timedelta(days=offset)).date()

    # overdue > 7 → P0
    assert compute_p_level("task", d(-8), today) == "P0"
    # overdue 7 或以下 → P1
    assert compute_p_level("task", d(-7), today) == "P1"
    assert compute_p_level("task", d(0), today) == "P1"   # 今日到期
    assert compute_p_level("task", d(1), today) == "P2"   # 聽日
    assert compute_p_level("task", d(30), today) == "P2"  # 未來
    assert compute_p_level("task", None, today) == "P3"   # 冇日期


def test_p_level_project_and_invoice_boundaries():
    from app.ai.briefing_sources import compute_p_level
    today = datetime(2026, 9, 4, 12, 0, tzinfo=HKT)

    def d(offset):
        return (datetime(2026, 9, 4, 0, 0, tzinfo=HKT) + timedelta(days=offset)).date()

    # project: overdue > 90 → P3
    assert compute_p_level("project", d(-91), today) == "P3"
    assert compute_p_level("project", d(-90), today) == "P2"
    assert compute_p_level("project", d(0), today) == "P2"
    assert compute_p_level("project", d(1), today) == "P1"  # 聽日 deadline
    assert compute_p_level("project", None, today) == "P3"
    # invoice: 到期 ≤3 日（含已過期）→ P0
    assert compute_p_level("invoice", d(0), today) == "P0"
    assert compute_p_level("invoice", d(-2), today) == "P0"
    assert compute_p_level("invoice", d(3), today) == "P0"
    assert compute_p_level("invoice", d(4), today) == "P1"
    assert compute_p_level("invoice", None, today) == "P3"

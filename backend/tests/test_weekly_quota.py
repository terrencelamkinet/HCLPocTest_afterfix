"""L2 unit tests for weekly AI usage quota (SPEC: docs/ai-usage-quota-SPEC.md).

Covers:
  - weekly period key (ISO week, HKT Monday boundary)
  - tenant plan get/set (settings JSONB, default free)
  - atomic reserve (INSERT-on-conflict + conditional UPDATE RETURNING)
  - QuotaExceeded at limit (free = 50/week)
  - pro = unlimited (-1) never blocks
  - refund after failed call
  - current usage readout
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

HKT = timezone(timedelta(hours=8))
TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fake DB — dispatches on SQL fragment
# ---------------------------------------------------------------------------
class _FakeDB:
    """AsyncSession double. Scriptable per-statement responses."""

    def __init__(self):
        self.responses: dict[str, object] = {}
        self.executed: list[str] = []
        self._reserve_pending: list[object] = []

    async def execute(self, stmt, *args, **kw):
        sql = str(stmt)
        self.executed.append(sql)
        if "INSERT INTO nexus_ai.ai_usage_quotas" in sql:
            # first half of reserve: INSERT ON CONFLICT DO NOTHING
            return NS(returns_rows=False, rowcount=0)
        if "UPDATE nexus_ai.ai_usage_quotas" in sql and "requests_used = requests_used + 1" in sql:
            return NS(scalar_one_or_none=lambda: self._reserve_pending.pop(0) if self._reserve_pending else None)
        if "UPDATE nexus_ai.ai_usage_quotas" in sql and "requests_used - 1" in sql:
            return NS(rowcount=1)
        if "nexus_auth_tenants" in sql and "UPDATE" in sql:
            return NS(rowcount=1)
        if "FROM nexus_auth.nexus_auth_tenants" in sql:
            return NS(scalar_one_or_none=lambda: self.responses.get("plan"))
        if "FROM nexus_ai.ai_usage_quotas" in sql:
            return NS(scalar_one_or_none=lambda: self.responses.get("used"))
        raise AssertionError(f"unexpected SQL: {sql[:100]}")

    def add(self, o):
        pass


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Period key (HKT, ISO week)
# ---------------------------------------------------------------------------
def test_period_key_monday_boundary():
    from app.ai.quota.weekly import weekly_period_key

    # 2026-09-07 is a Monday (HKT) → ISO week 37 of 2026
    mon = datetime(2026, 9, 7, 0, 1, tzinfo=HKT)
    assert weekly_period_key(mon) == "2026-W37"
    # Sunday 2026-09-06 still week 36
    sun = datetime(2026, 9, 6, 23, 59, tzinfo=HKT)
    assert weekly_period_key(sun) == "2026-W36"


def test_reset_at_next_monday():
    from app.ai.quota.weekly import reset_at

    # Wed 2026-09-09 → next Monday 2026-09-14
    wed = datetime(2026, 9, 9, 15, 0, tzinfo=HKT)
    assert str(reset_at(wed)) == "2026-09-14"
    # Monday itself → reset already passed → next week Monday
    mon = datetime(2026, 9, 7, 10, 0, tzinfo=HKT)
    assert str(reset_at(mon)) == "2026-09-14"


# ---------------------------------------------------------------------------
# Tenant plan
# ---------------------------------------------------------------------------
def test_plan_defaults_to_free():
    from app.ai.quota.weekly import get_tenant_plan

    db = _FakeDB()
    db.responses["plan"] = None  # settings has no plan
    assert _run(get_tenant_plan(db, TENANT)) == "free"


def test_get_plan_pro():
    from app.ai.quota.weekly import get_tenant_plan

    db = _FakeDB()
    db.responses["plan"] = "pro"
    assert _run(get_tenant_plan(db, TENANT)) == "pro"


def test_set_plan_updates_settings():
    from app.ai.quota.weekly import set_tenant_plan

    db = _FakeDB()
    _run(set_tenant_plan(db, TENANT, "pro"))
    sql = db.executed[-1]
    assert "jsonb_set" in sql and "nexus_auth.nexus_auth_tenants" in sql and ":plan_val" in sql
    # settings column 係 json type — 必須 cast jsonb（regression：真 DB type error）
    assert "settings::jsonb" in sql and "::json" in sql


def test_plan_limits():
    from app.ai.quota.weekly import plan_limit

    assert plan_limit("free") == 50
    assert plan_limit("pro") == -1  # unlimited
    assert plan_limit("unknown-plan") == 50  # unknown → free default


# ---------------------------------------------------------------------------
# Reserve / refund
# ---------------------------------------------------------------------------
def test_reserve_first_call_creates_and_increments():
    """New period: INSERT no-op + UPDATE returns used=1 → no exception."""
    from app.ai.quota.weekly import reserve_request

    db = _FakeDB()
    db.reserve_results = [1]  # one successful reserve
    # reserve() pops from _reserve_pending; wire it up
    db._reserve_pending = [1]
    _run(reserve_request(db, TENANT, USER))  # should not raise
    # executed INSERT then UPDATE
    assert any("INSERT INTO nexus_ai.ai_usage_quotas" in s for s in db.executed)
    assert any("RETURNING requests_used" in s for s in db.executed)


def test_reserve_at_limit_raises():
    """used=50/50 → UPDATE returns 0 rows → QuotaExceededError."""
    from app.ai.quota.weekly import reserve_request, QuotaExceededError

    db = _FakeDB()
    db._reserve_pending = [None]  # UPDATE matched 0 rows
    db.responses["used"] = 50  # _current_used reads 50/50 after failed reserve
    with pytest.raises(QuotaExceededError) as ei:
        _run(reserve_request(db, TENANT, USER))
    assert ei.value.used == 50 and ei.value.limit == 50


def test_enforce_returns_none_when_available():
    """Quota 未用晒 → reserve 成功 → None（caller 可以 call LLM）"""
    from app.ai.quota.weekly import enforce_weekly_quota

    db = _FakeDB()
    db._reserve_pending = [1]
    out = _run(enforce_weekly_quota(db, TENANT, USER))
    assert out is None


def test_enforce_returns_message_when_exceeded():
    """用晒 → block dict：message 含 50/50 + 重置日 + 升級 CTA（Q8B）"""
    from app.ai.quota.weekly import enforce_weekly_quota

    db = _FakeDB()
    db._reserve_pending = [None]  # reserve matched 0 rows
    db.responses["used"] = 50
    out = _run(enforce_weekly_quota(db, TENANT, USER))
    assert out is not None
    assert out["error"] == "weekly_quota_exceeded"
    assert "50/50" in out["message"] and "重置" in out["message"]
    assert "升級 Pro" in out["message"]  # CTA placeholder
    assert out["used"] == 50 and out["limit"] == 50
    assert out["reset_on"]  # e.g. 2026-09-07


def test_refund_decrements():
    from app.ai.quota.weekly import refund_request

    db = _FakeDB()
    _run(refund_request(db, TENANT, USER))
    assert any("requests_used - 1" in s for s in db.executed)


def test_current_usage_readout():
    from app.ai.quota.weekly import current_usage

    db = _FakeDB()
    db.responses["used"] = 12  # SELECT requests_used scalar
    out = _run(current_usage(db, TENANT, USER))
    assert out["used"] == 12 and out["limit"] == 50
    assert out["period_key"].startswith("2026-W") and out["plan"] == "free"
    assert "reset_on" in out

"""Prompt eval — 紅燈先行（migration 027 未上之前應該 fail）。

契約：
 1. `render_prompt` 填 variable；**缺 variable 唔准爆**（留返 `{placeholder}`）—— eval
    用嘅 case 可能冇提供全部 variable，唔應該因為咁而 crash
 2. 斷言五種：contains / not_contains / regex / json_valid / max_chars
 3. `run_eval` 要：render → call LLM（**可注入**）→ 逐條評分 → 落庫（run + cases）→ 出 scorecard
 4. 失敗嘅 case 一定要有 reason（唔可以靜默紅）
 5. 租戶隔離：A tenant 嘅 run 唔可以俾 B tenant 見到
"""

import uuid

import pytest
from sqlalchemy import text

from app.db import async_session
from app.services.prompt_eval import (
    EvalCase,
    assertion_ok,
    render_prompt,
    run_eval,
)

T_A = uuid.UUID("00000000-0000-0000-0000-0000000e1001")
T_B = uuid.UUID("00000000-0000-0000-0000-0000000e1002")
USER = uuid.UUID("00000000-0000-0000-0000-0000000000ff")


@pytest.fixture(autouse=True)
async def _db_fixture():
    """跑之前 + 跑之後都 dispose engine（清走上一個 loop 嘅連線），再清測試資料。"""
    from app.db import engine

    await engine.dispose()
    yield
    try:
        async with async_session() as db:
            for t in (T_A, T_B):
                await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t)})
                await db.execute(text("DELETE FROM nexus_ai.prompt_eval_runs WHERE tenant_id = :t"), {"t": t})
                await db.execute(text("DELETE FROM nexus_ai.prompt_templates WHERE tenant_id = :t"), {"t": t})
            await db.commit()
    except Exception:
        pass
    await engine.dispose()


async def _seed_template(tenant, key="system_chat", version=1, content="你係助手。{user_name} 你好"):
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        await db.execute(text("""
            INSERT INTO nexus_ai.prompt_templates
                (tenant_id, key, name, content, version, is_active, variables)
            VALUES (:t, :k, :k, :c, :v, true, '[]'::jsonb)
            ON CONFLICT (tenant_id, key, version) DO UPDATE SET content = EXCLUDED.content
        """), {"t": tenant, "k": key, "c": content, "v": version})
        await db.commit()


# ── 1. render ──

def test_render_substitutes_variables():
    out = render_prompt("哈囉 {user_name}，你係 {role}。", {"user_name": "陳大文", "role": "老闆"})
    assert out == "哈囉 陳大文，你係 老闆。"


def test_render_missing_variable_does_not_crash():
    out = render_prompt("哈囉 {user_name}，今日係 {date}。", {"user_name": "陳大文"})
    assert "陳大文" in out
    assert "{date}" in out, "缺失 variable 要原樣留低，唔可以爆 / 靜默清空"


# ── 2. 斷言 ──

def test_assertion_contains():
    ok, reason = assertion_ok("三六零數字安全係客戶", {"type": "contains", "value": "三六零"})
    assert ok is True, reason
    ok2, reason2 = assertion_ok("三六零數字安全", {"type": "contains", "value": "匯豐"})
    assert ok2 is False
    assert reason2, "失敗要有 reason"


def test_assertion_not_contains():
    ok, _ = assertion_ok("答案：唔知道", {"type": "not_contains", "value": "未能連接服務"})
    assert ok is True
    ok2, reason2 = assertion_ok("未能連接服務", {"type": "not_contains", "value": "未能連接服務"})
    assert ok2 is False and reason2


def test_assertion_regex_and_json_and_maxchars():
    assert assertion_ok("共 12 個客戶", {"type": "regex", "value": r"\d+ 個客戶"})[0] is True
    assert assertion_ok("冇數字", {"type": "regex", "value": r"\d+ 個客戶"})[0] is False
    assert assertion_ok('{"a": 1}', {"type": "json_valid"})[0] is True
    assert assertion_ok("唔係 json", {"type": "json_valid"})[0] is False
    assert assertion_ok("短", {"type": "max_chars", "value": 10})[0] is True
    assert assertion_ok("x" * 11, {"type": "max_chars", "value": 10})[0] is False


def test_assertion_unknown_type_is_failure_not_crash():
    ok, reason = assertion_ok("任何嘢", {"type": "no_such_rule"})
    assert ok is False
    assert "no_such_rule" in reason


# ── 3/4. run_eval ──

@pytest.mark.asyncio
async def test_run_eval_scores_and_persists():
    await _seed_template(T_A)

    async def fake_llm(_prompt: str) -> str:
        return "你好，陳大文！本公司有 12 個客戶。"

    cases = [
        EvalCase(key="greet", variables={"user_name": "陳大文"},
                 assertions=[{"type": "contains", "value": "陳大文"}]),
        EvalCase(key="no_fail_phrase", variables={"user_name": "陳大文"},
                 assertions=[{"type": "not_contains", "value": "未能連接服務"}]),
        EvalCase(key="must_fail", variables={"user_name": "陳大文"},
                 assertions=[{"type": "contains", "value": "呢句一定冇"}]),
    ]
    async with async_session() as db:
        card = await run_eval(
            db, tenant_id=T_A, key="system_chat", version=1,
            cases=cases, llm_call=fake_llm, created_by=USER, model="fake-model",
        )

        assert card["total"] == 3
        assert card["passed"] == 2
        assert card["failed"] == 1
        assert card["run_id"]

        # ⚠️ run_eval 內部 commit 過 → transaction-scoped GUC 被 reset
        # → 之後嘅 SELECT 會撞 RLS false-zero（返 0 row），所以要重設
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T_A)})
        rows = (await db.execute(text("""
            SELECT case_key, passed, reason FROM nexus_ai.prompt_eval_cases
            WHERE run_id = :r ORDER BY case_key
        """), {"r": card["run_id"]})).mappings().all()
        assert len(rows) == 3
        by_key = {r["case_key"]: r for r in rows}
        assert by_key["must_fail"]["passed"] is False
        assert by_key["must_fail"]["reason"], "失敗 case 一定要有 reason"


@pytest.mark.asyncio
async def test_run_eval_is_tenant_scoped():
    await _seed_template(T_A)
    await _seed_template(T_B)

    async def fake_llm(_p: str) -> str:
        return "陳大文 你好"

    cases = [EvalCase(key="c1", variables={"user_name": "陳大文"},
                      assertions=[{"type": "contains", "value": "陳大文"}])]

    async with async_session() as db:
        await run_eval(db, tenant_id=T_A, key="system_chat", version=1,
                       cases=cases, llm_call=fake_llm, created_by=USER, model="m")

    async with async_session() as db_b:
        await db_b.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T_B)})
        n = (await db_b.execute(text(
            "SELECT count(*) FROM nexus_ai.prompt_eval_runs WHERE tenant_id = :t"), {"t": T_A})).scalar()
        assert n == 0, f"B tenant 唔應該睇到 A tenant 嘅 run（實際 {n}）"

    async with async_session() as db_a:
        await db_a.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T_A)})
        n_a = (await db_a.execute(text(
            "SELECT count(*) FROM nexus_ai.prompt_eval_runs WHERE tenant_id = :t"), {"t": T_A})).scalar()
        assert n_a == 1, f"A tenant 應該睇到自己嘅 run（實際 {n_a}）"

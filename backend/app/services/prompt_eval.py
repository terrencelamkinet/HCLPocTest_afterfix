"""Prompt eval —— 跑 prompt 版本嘅回歸評估（版本管理 + eval 之 eval 部分）。

**為咩存在**：`nexus_ai.prompt_templates` 有 version / is_active / unique(tenant,key,version)
（版本管理 ✅），但改完 prompt **冇任何方法知「改好咗定改壞咗」**。呢個 module 補嗰忽。

**設計**：
  - 一次 run = 一組 case 對某個 `(tenant, key, version)` 跑
  - 每條 case：`render_prompt` → call LLM → **確定性斷言**評分（唔靠另一個 LLM 做主觀評分，
    因為咁樣評分本身唔可重現）
  - **LLM call 係注入嘅**（`llm_call` 參數）→ 測試用 fake，唔會靠 live 模型輸出；CLI 用真 provider
  - 落庫（`nexus_ai.prompt_eval_runs` + `prompt_eval_cases`）→ 可以比較兩個版本嘅分數

**斷言類型**（確定性，可重現）：
  `contains` / `not_contains` / `regex` / `json_valid` / `max_chars`

CLI：
    cd backend && ./venv/bin/python -m app.services.prompt_eval \
        --tenant 00000000-0000-0000-0000-000000000001 --key system_chat --version 1 \
        --cases cases.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

LlmCall = Callable[[str], Awaitable[str]]


@dataclass
class EvalCase:
    key: str
    variables: dict = field(default_factory=dict)
    assertions: list[dict] = field(default_factory=list)


def render_prompt(content: str, variables: dict) -> str:
    """填 variable；**缺 variable 原樣留低**（唔爆、唔靜默清空）。"""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in variables and variables[name] is not None:
            return str(variables[name])
        return m.group(0)

    return PLACEHOLDER_RE.sub(repl, content or "")


def assertion_ok(output: str, rule: dict) -> tuple[bool, str]:
    """回 `(ok, reason)`；reason 只喺失敗時有意義。**未知類型當失敗**（唔准靜默當 pass）。"""
    if not isinstance(rule, dict):
        return False, f"rule 唔係 dict：{rule!r}"
    t = rule.get("type")
    val = rule.get("value")

    if t in ("contains", "not_contains"):
        if val is None:
            return False, f"{t} 嘅 value 唔可以係 null"
        needle = str(val)
        if t == "contains":
            if needle in output:
                return True, ""
            return False, f"應該包含 {needle!r}（實際：{output[:120]!r}）"
        if needle not in output:
            return True, ""
        return False, f"唔應該包含 {needle!r}"

    if t == "regex":
        try:
            if re.search(str(val), output):
                return True, ""
        except re.error as e:
            return False, f"regex 無效：{e}"
        return False, f"應該 match /{val}/（實際：{output[:120]!r}）"

    if t == "json_valid":
        try:
            json.loads(output)
            return True, ""
        except Exception as e:
            return False, f"唔係有效 JSON：{e}"

    if t == "max_chars":
        try:
            limit = int(str(val))
        except (TypeError, ValueError):
            return False, f"max_chars 嘅 value 無效：{val!r}"
        if len(output) <= limit:
            return True, ""
        return False, f"太長：{len(output)} > {limit}"

    return False, f"未知斷言類型：{t!r}"


async def _get_template_content(db: AsyncSession, tenant_id: UUID, key: str, version: int) -> str:
    row = (await db.execute(
        text("""
            SELECT content FROM nexus_ai.prompt_templates
            WHERE tenant_id = :t AND key = :k AND version = :v
        """),
        {"t": tenant_id, "k": key, "v": version},
    )).first()
    if not row:
        raise ValueError(f"搵唔到 prompt template：tenant={tenant_id} key={key} version={version}")
    return row[0]


async def run_eval(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    key: str,
    version: int,
    cases: list[EvalCase],
    llm_call: LlmCall,
    created_by: UUID | None = None,
    model: str | None = None,
    excerpt_chars: int = 800,
) -> dict:
    """跑一組 case 並落庫，回 scorecard。"""
    # ⚠️ 一開始就要設 GUC —— 唔係讀 prompt_templates 會撞 RLS false-zero
    # （app session 冇 app.tenant_id → RLS 過濾走所有 row → 誤判「冇 template」）。
    # transaction-scoped：一個 session 一次就夠，覆蓋埋後面嘅 INSERT。
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})

    content = await _get_template_content(db, tenant_id, key, version)

    t0 = time.perf_counter()
    results: list[dict] = []
    for case in cases:
        prompt = render_prompt(content, case.variables or {})
        c0 = time.perf_counter()
        output, err = "", None
        try:
            output = await llm_call(prompt) or ""
        except Exception as e:  # LLM 爆唔應該炸成個 eval run
            # 2026-09-15 SAST：唔好將 raw exception message 放入 API 回傳（會漏內部細節／
            # 上游 provider 資訊）。完整資訊仍然入 server log。
            err = f"LLM call 失敗（{type(e).__name__}）"
            logger.exception("prompt_eval: LLM call failed (case=%s)", case.key)
        latency_ms = int((time.perf_counter() - c0) * 1000)

        if err:
            results.append({"key": case.key, "passed": False, "reason": err,
                            "output": "", "latency_ms": latency_ms})
            continue

        reasons = []
        for rule in case.assertions or []:
            ok, why = assertion_ok(output, rule)
            if not ok:
                reasons.append(why)
        results.append({"key": case.key, "passed": not reasons, "reason": "；".join(reasons),
                        "output": output, "latency_ms": latency_ms})

    duration_ms = int((time.perf_counter() - t0) * 1000)
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    # RLS：GUC 喺 run 開頭已設（transaction-scoped）
    run_id = (await db.execute(
        text("""
            INSERT INTO nexus_ai.prompt_eval_runs
                (tenant_id, prompt_key, prompt_version, model, total, passed, failed,
                 duration_ms, created_by)
            VALUES (:t, :k, :v, :m, :total, :p, :f, :d, :u)
            RETURNING id
        """),
        {"t": tenant_id, "k": key, "v": version, "m": model, "total": len(results),
         "p": passed, "f": failed, "d": duration_ms, "u": created_by},
    )).scalar()

    for r in results:
        await db.execute(
            text("""
                INSERT INTO nexus_ai.prompt_eval_cases
                    (run_id, tenant_id, case_key, passed, reason, output_excerpt, latency_ms)
                VALUES (:r, :t, :k, :p, :why, :out, :lat)
            """),
            {"r": run_id, "t": tenant_id, "k": r["key"], "p": r["passed"],
             "why": r["reason"] or None, "out": (r["output"] or "")[:excerpt_chars],
             "lat": r["latency_ms"]},
        )
    await db.commit()

    return {
        "run_id": str(run_id),
        "tenant_id": str(tenant_id),
        "key": key,
        "version": version,
        "model": model,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "duration_ms": duration_ms,
        "cases": [{"key": r["key"], "passed": r["passed"], "reason": r["reason"],
                   "latency_ms": r["latency_ms"]} for r in results],
    }


# ── CLI ──

def load_cases_file(path: str) -> list[EvalCase]:
    """cases.json 格式：
    [{"key": "greet", "variables": {...}, "assertions": [{"type": "contains", "value": "..."}]}]
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("cases 檔要係 JSON array")
    return [
        EvalCase(key=c["key"], variables=c.get("variables") or {}, assertions=c.get("assertions") or [])
        for c in raw
    ]


async def _cli_main(args: argparse.Namespace) -> int:
    from app.db import async_session

    cases = load_cases_file(args.cases)

    # 真 LLM call（CLI 專用；測試一律注入 fake）
    from app.ai.providers.gemini import GeminiAdapter

    adapter = GeminiAdapter()
    used = {"model": args.model or getattr(adapter, "_default_model", "") or "gemini"}

    async def llm_call(prompt: str) -> str:
        # ⚠️ 切片 1：將整段 rendered prompt 當 user message 送出去。
        # 對 system prompt 嚟講唔係最正確嘅語意（應該 system instruction + 獨立 user turn），
        # 但作為 smoke eval 足夠；system/user 分離係下一步。
        # ⚠️ 一定要傳 model 落去 —— 唔係會 fallback 去 `_default_model`
        # （2026-09-12 踩過：記錄寫 gemini-2.5-flash 但實際 call gemini-2.0-flash → 404，
        #  即係 scorecard 嘅 model 名係假嘅）
        text, report = await adapter.chat(
            [{"role": "user", "content": prompt}],
            model=args.model or "",
            temperature=0.2,
        )
        if getattr(report, "model", None):
            used["model"] = report.model
        return text

    async with async_session() as db:
        card = await run_eval(
            db,
            tenant_id=UUID(args.tenant),
            key=args.key,
            version=args.version,
            cases=cases,
            llm_call=llm_call,
            model=used["model"],
        )

    logger.info("prompt_eval done: %s", json.dumps(card, ensure_ascii=False))
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0 if card["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Prompt eval run")
    p.add_argument("--tenant", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--cases", required=True, help="JSON array 檔")
    p.add_argument("--model", default=None)
    args = p.parse_args(argv)
    try:
        return asyncio.run(_cli_main(args))
    except Exception:
        logger.exception("prompt_eval CLI failed")
        return 2


if __name__ == "__main__":
    sys.exit(main())

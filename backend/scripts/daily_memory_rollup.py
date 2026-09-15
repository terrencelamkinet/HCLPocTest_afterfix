"""Daily Memory Rollup — G08 NEXUS CRM.

Summarises each active session's messages from *yesterday (HKT)* into
`sessions.memory_summary`, then writes a per-tenant daily digest into
`user_memory` (category='daily', source='daily_rollup:YYYY-MM-DD') so
future AI sessions can remember what happened yesterday.

Product-level cron script (no_agent) — zero AI-agent dependency.
Reads backend/.env for DEEPSEEK_API_KEY. DB URL comes from app.config.

Run: cd backend && venv/bin/python scripts/daily_memory_rollup.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── env bootstrap: load backend/.env (DEEPSEEK_API_KEY etc.) ───────────
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy import text  # noqa: E402

from app.db import async_session  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")
SUMMARY_MODEL = "deepseek-chat"
MAX_SESSION_MSGS = 60  # cap per-session LLM input
MIN_MSGS_FOR_SUMMARY = 2  # ignore sessions with a single trivial message

_SESSION_SUMMARY_SYSTEM = """\
You are a CRM conversation memory system. Summarise the conversation below \
into 3-8 concise bullet facts that would help a future AI assistant remember \
this user's work. Focus on: decisions made, people/companies/projects mentioned, \
preferences, pending follow-ups, data the user asked to update. \
Keep each fact under 40 words. Output ONLY the bullet list, no preamble."""

_DAILY_DIGEST_SYSTEM = """\
You are a CRM daily memory digest system. Below are per-session summaries of a \
user's conversations yesterday. Merge them into ONE coherent daily digest of \
5-10 bullets covering: key decisions, people/companies/projects discussed, \
preferences stated, open follow-ups. Keep each bullet under 45 words. \
Output ONLY the bullet list, no preamble."""


async def _llm_summarize(messages: list[dict], system: str) -> str | None:
    """Call DeepSeek directly (no adapter — keeps script standalone)."""
    from openai import AsyncOpenAI

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("  [warn] DEEPSEEK_API_KEY missing — skipping LLM calls")
        return None
    client = AsyncOpenAI(api_key=key, base_url="https://api.deepseek.com")
    try:
        resp = await client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "system", "content": system}] + messages,
            temperature=0.2,
            max_tokens=800,
        )
        return resp.choices[0].message.content
    finally:
        await client.close()


async def main() -> None:
    # ── Yesterday's HKT window ──────────────────────────────────────────
    now_hkt = datetime.now(HKT)
    day_start = datetime.combine(now_hkt.date() - timedelta(days=1), time.min, tzinfo=HKT)
    day_end = day_start + timedelta(days=1)
    day_label = day_start.strftime("%Y-%m-%d")
    print(f"[{now_hkt:%Y-%m-%d %H:%M %Z}] rollup target: {day_label}")

    async with async_session() as db:
        # ── 1. Fetch yesterday's messages grouped by session ────────────
        rows = (
            await db.execute(
                text(
                    """
                    SELECT m.session_id,
                           s.tenant_id, s.user_id, s.title,
                           m.role, m.content
                    FROM nexus_ai.messages m
                    JOIN nexus_ai.sessions s ON s.id = m.session_id
                    WHERE m.created_at >= :d0 AND m.created_at < :d1
                      AND m.content IS NOT NULL AND m.content <> ''
                    ORDER BY m.created_at ASC
                    """
                ),
                {"d0": day_start, "d1": day_end},
            )
        ).fetchall()

        if not rows:
            print("  no messages yesterday — nothing to roll up")
            return

        by_session: dict = {}
        for r in rows:
            by_session.setdefault(
                r.session_id,
                {
                    "tenant_id": r.tenant_id,
                    "user_id": r.user_id,
                    "title": r.title,
                    "msgs": [],
                },
            )["msgs"].append({"role": r.role, "content": r.content})

        print(f"  {len(rows)} messages across {len(by_session)} sessions")

        # ── 2. Per-session summary → sessions.memory_summary ────────────
        per_session_summaries: list[tuple] = []  # (tenant, user, session_id, digest)
        for sess_id, info in by_session.items():
            msgs = info["msgs"]
            if len(msgs) < MIN_MSGS_FOR_SUMMARY:
                continue
            conv = msgs[-MAX_SESSION_MSGS:]
            summary = await _llm_summarize(
                [{"role": m["role"], "content": m["content"][:2000]} for m in conv],
                _SESSION_SUMMARY_SYSTEM,
            )
            if not summary:
                continue
            await db.execute(
                text(
                    "UPDATE nexus_ai.sessions SET memory_summary = :s WHERE id = :id"
                ),
                {"s": summary.strip(), "id": sess_id},
            )
            per_session_summaries.append(
                (info["tenant_id"], info["user_id"], sess_id, summary.strip())
            )
            print(f"  session {str(sess_id)[:8]}… → {len(summary)} chars")

        if not per_session_summaries:
            print("  no sessions met summary threshold")
            return

        # ── 3. Per-tenant daily digest → user_memory (category='daily') ─
        by_tenant: dict = {}
        for tenant_id, user_id, sess_id, summary in per_session_summaries:
            by_tenant.setdefault(
                (str(tenant_id), str(user_id)), []
            ).append(f"• {summary}")

        written = 0
        for (tenant_id, user_id), summaries in by_tenant.items():
            digest = await _llm_summarize(
                [{"role": "user", "content": "\n\n".join(summaries)}],
                _DAILY_DIGEST_SYSTEM,
            )
            if not digest:
                continue
            # Upsert: one daily row per (tenant, user, date) — replace old
            await db.execute(
                text(
                    """
                    DELETE FROM nexus_ai.user_memory
                    WHERE tenant_id = :t AND user_id = :u AND source = :src
                    """
                ),
                {"t": tenant_id, "u": user_id, "src": f"daily_rollup:{day_label}"},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO nexus_ai.user_memory
                        (id, tenant_id, user_id, category, content, source,
                         confidence, created_at, last_accessed)
                    VALUES (gen_random_uuid(), :t, :u, 'daily', :content, :src,
                            1.0, now(), now())
                    """
                ),
                {
                    "t": tenant_id,
                    "u": user_id,
                    "content": digest.strip(),
                    "src": f"daily_rollup:{day_label}",
                },
            )
            written += 1
            print(f"  daily digest → user {str(user_id)[:8]}… ({len(digest)} chars)")

        await db.commit()
        print(f"DONE — {written} daily digest(s) written for {day_label}")


if __name__ == "__main__":
    asyncio.run(main())

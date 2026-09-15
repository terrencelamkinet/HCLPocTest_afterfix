"""檢索審計（spec §11）— 每次 retrieval 寫一筆，出事查得到。

原則：
  - **唔記原文**：只記 query 嘅 SHA-256 + 命中 doc/chunk id（避免普通 log 洩漏內容）
  - **best-effort**：審計寫入失敗唔可以影響 AI 回答
  - **自己嘅短 transaction**：唔用 caller 嘅 session —— 呼叫做緊嘅寫入唔應該
    因為審計 commit 而提早落地（2026-09-12 double check 修正）
  - 冇 user_id = 審計失效 → 出 WARNING（唔可以靜默，否則「有做」係假象）
事件名（spec §11）：rag.retrieval.allowed / rag.retrieval.denied
"""

from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import text

logger = logging.getLogger(__name__)

EVENT_ALLOWED = "rag.retrieval.allowed"
EVENT_DENIED = "rag.retrieval.denied"


def query_hash(query: str) -> str:
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:32]


async def record_retrieval(
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    query: str,
    hits: list,
    latency_ms: int | None = None,
    source: str = "chat",
    session_id: UUID | None = None,
) -> None:
    """寫一筆檢索審計（用自己嘅 session，唔影響 caller 嘅 transaction）。"""
    if user_id is None:
        # 唔可以靜默 —— 冇 user_id 即係審計完全冇記，要出聲
        logger.warning(
            "retrieval audit SKIPPED (caller did not pass user_id) tenant=%s source=%s",
            tenant_id,
            source,
        )
        return

    event = EVENT_ALLOWED if hits else EVENT_DENIED
    detail = {
        "source": source,
        "query_hash": query_hash(query),
        "result_count": len(hits),
        "document_ids": [str(h.document_id) for h in hits[:20]],
        "chunk_ids": [str(h.chunk_id) for h in hits[:20]],
        "top_score": round(hits[0].score, 4) if hits else None,
        "latency_ms": latency_ms,
    }
    try:
        from app.db import async_session

        async with async_session() as adb:
            await adb.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            await adb.execute(
                text("""
                    INSERT INTO nexus_ai.ai_audit_log
                        (tenant_id, user_id, session_id, event_type, detail)
                    VALUES (:t, :u, :s, :ev, CAST(:d AS jsonb))
                """),
                {
                    "t": tenant_id,
                    "u": user_id,
                    "s": session_id,
                    "ev": event,
                    "d": json.dumps(detail, ensure_ascii=False),
                },
            )
            await adb.commit()
    except Exception:
        # best-effort：審計唔可以拖冧回答
        logger.exception("retrieval audit write failed tenant=%s", tenant_id)

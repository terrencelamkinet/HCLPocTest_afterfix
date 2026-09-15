"""DLP（Data Loss Prevention）— 出站內容掃描（BYOK + DLP + 審計報告 之三）。

定位：**出站邊界**（餵去 LLM 嘅文字）掃敏感資料 —— 唔係防內部人，而係防
「敏感資料經 AI context 出去」。

捉咩（刻意保守，寧少勿濫）：
  - `secret`：password / passwd / pwd / secret / token / api_key / authorization / bearer
  - `hkid`：香港身份證（A123456(3)）
  - `credit_card`：13-19 位數字，**要過 Luhn 檢查**（唔過 = 唔當信用卡，避免誤報）

**刻意唔捉電話號碼**：CRM 正常資料滿佈電話，捉咗 = 全部 flag = 等於冇用。

行為：
  - `scan_text()` 只報告（唔改字）
  - `redact_text()` 遮蔽：保留 label（`password:[REDACTED]`），值一定走
  - `audit_dlp()` 寫 `ai_audit_log`（event_type=`dlp.flagged`）—— **唔記原文**
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SECRET_RE = re.compile(
    r"(?P<label>password|passwd|pwd|secret|token|api[_-]?key|authorization|bearer)"
    # ⚠️ value 唔可以以 `[` 開頭 —— 唔係會將上一層（ingest）已經遮成 `[已遮蔽]`
    # 嘅標記當成 value 再遮一次，令原本嘅值被推去後面留住（2026-09-12 踩過）
    r"\s*[:=]\s*(?P<value>(?!\[)[^\s,;，。；]{4,})",
    re.IGNORECASE,
)
HKID_RE = re.compile(r"\b[A-Z]{1,2}\d{6}\(\d\)")
CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

REDACTED = "[REDACTED]"


@dataclass
class DlpHit:
    label: str
    start: int
    end: int


@dataclass
class DlpVerdict:
    hits: list[DlpHit] = field(default_factory=list)
    text_len: int = 0

    @property
    def hit(self) -> bool:
        return bool(self.hits)

    @property
    def labels(self) -> list[str]:
        return sorted({h.label for h in self.hits})

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for h in self.hits:
            out[h.label] = out.get(h.label, 0) + 1
        return out


def _luhn_ok(digits: str) -> bool:
    """Luhn 檢查 —— 唔過就唔當信用卡（信用卡號碼校驗位）。"""
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def scan_text(text_in: str) -> DlpVerdict:
    """掃敏感資料（唯讀，唔改字）。"""
    v = DlpVerdict(text_len=len(text_in or ""))
    if not text_in:
        return v

    for m in SECRET_RE.finditer(text_in):
        v.hits.append(DlpHit("secret", m.start(), m.end()))

    for m in HKID_RE.finditer(text_in):
        v.hits.append(DlpHit("hkid", m.start(), m.end()))

    for m in CARD_CANDIDATE_RE.finditer(text_in):
        digits = re.sub(r"[ -]", "", m.group(0))
        if _luhn_ok(digits):
            v.hits.append(DlpHit("credit_card", m.start(), m.end()))

    v.hits.sort(key=lambda h: h.start)
    return v


def redact_text(text_in: str) -> str:
    """遮蔽敏感值，保留 label（俾讀者知係咩被遮）。"""
    if not text_in:
        return text_in

    out = SECRET_RE.sub(lambda m: f"{m.group('label')}:{REDACTED}", text_in)

    def _mask_cards(text: str) -> str:
        def repl(m: re.Match) -> str:
            digits = re.sub(r"[ -]", "", m.group(0))
            if _luhn_ok(digits):
                return f"{digits[:4]}****{digits[-4:]}" if len(digits) >= 8 else REDACTED
            return m.group(0)
        return CARD_CANDIDATE_RE.sub(repl, text)

    out = _mask_cards(out)
    out = HKID_RE.sub(lambda m: f"{m.group(0)[:1]}******(*)", out)
    return out


async def _write(session: AsyncSession, tenant_id: UUID, user_id: UUID | None, detail: dict) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )
    await session.execute(
        text("""
            INSERT INTO nexus_ai.ai_audit_log (tenant_id, user_id, event_type, detail)
            VALUES (:t, :u, 'dlp.flagged', CAST(:d AS jsonb))
        """),
        {"t": tenant_id, "u": user_id, "d": json.dumps(detail, ensure_ascii=False)},
    )


async def audit_dlp(
    db: AsyncSession | None,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    verdict: DlpVerdict,
    source: str = "unknown",
) -> None:
    """寫 DLP 審計（event_type=dlp.flagged）—— 唔記原文，只記類型 + 數目 + 來源。

    - `db` 有值 → 用 caller 嘅 session，**唔 commit**（由 caller 控制 transaction）
    - `db` 係 None → 自己開短 session + commit（RAG 出站路徑用呢個，
      確保唔會提早 commit 人哋嘅 transaction —— 見 KB-022）
    """
    if not verdict.hit:
        return
    detail = {
        "source": source,
        "hit_labels": verdict.labels,
        "counts": verdict.counts(),
        "text_len": verdict.text_len,
    }
    try:
        if db is not None:
            await _write(db, tenant_id, user_id, detail)
        else:
            from app.db import async_session

            async with async_session() as adb:
                await _write(adb, tenant_id, user_id, detail)
                await adb.commit()
        logger.warning(
            "DLP flagged source=%s labels=%s counts=%s", source, verdict.labels, verdict.counts()
        )
    except Exception:
        logger.exception("DLP audit write failed (source=%s)", source)

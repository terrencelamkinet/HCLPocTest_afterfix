"""Structural IM message routing gates (KB-009 permanent fix).

Why this module exists
----------------------
A pre-AI interceptor in ``services/telegram_inbound.py`` used to decide, by
keyword matching on message *content*, whether an incoming Telegram message
was an answer to a pending calendar follow-up / write-action confirm. Because
the decision was content-based it silently swallowed real user messages and
wrote them into ``nexus_crm.touchpoints`` as fake "meeting" records. That
happened three distinct times in one day (「今日天氣」, a troubleshooting
question, and a whole uploaded PDF whose text happened to contain 會議).

Patching keyword lists is fundamentally leaky. This module replaces it with a
small set of STRUCTURAL gates that make an accidental swallow impossible by
construction:

  a) provenance gate  — only a TYPED message may ever be claimed by a
     text-reply interceptor. Voice / document / image / callback text can
     NEVER be claimed, regardless of what the text says.
  b) grammar gate     — the WHOLE trimmed message must be one of a tiny set
     of exact tokens ("係" / "唔使" / "ok" ...). No substring / "contains"
     logic exists anywhere in this file.
  c) freshness gate   — the pending prompt must still be young enough; an
     UNKNOWN age fails closed (never claimable).
  d) size gate        — the message must be short enough to plausibly be a
     one-word reply (a pasted document can never be).

A message that fails ANY gate is *not* claimable: it falls through to the AI
consumer, and NOTHING is ever recorded from the user's own words.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "MessageOrigin",
    "RouteDecision",
    "normalize_token",
    "is_discrete_reply",
    "may_text_reply_claim",
    "CONFIRM_TOKENS",
    "CANCEL_TOKENS",
    "NUMERIC_TOKENS",
    "DISCRETE_TOKENS",
]


class MessageOrigin(str, Enum):
    """Where a piece of inbound text came from.

    Only :attr:`TYPED` may ever be claimed by a text-reply interceptor. The
    other origins represent machine-derived text (STT transcripts, extracted
    document bodies, OCR'd images) or non-message events, all of which must
    reach the AI consumer.
    """

    TYPED = "typed"
    VOICE = "voice"
    DOCUMENT = "document"
    IMAGE = "image"
    CALLBACK = "callback"


@dataclass(frozen=True)
class RouteDecision:
    """Outcome of a routing decision — logged so any swallow is visible.

    ``consumer`` names who handled the message (e.g. ``"ai"`` or
    ``"followup"``); ``reply`` is the in-band reply when an interceptor
    claimed it (``None`` when the AI consumer answers); ``reason`` is the
    gate name that produced the decision.
    """

    consumer: str
    reply: str | None
    reason: str


# --- Exact-token grammar -------------------------------------------------
# A discrete reply is the WHOLE trimmed, lower-cased message equal to one of
# these tokens. Anything else (「確認一下」「今日天氣」「會議安排」…) is NOT a
# discrete reply and must fall through to the AI.
CONFIRM_TOKENS: frozenset[str] = frozenset(
    {
        # --- basics (pre-existing) ---
        "係", "是", "對", "啱", "好", "確認", "確定", "可以", "ok", "yes", "y",
        # --- C4 (2026-09-10): widened to the vocabulary that actually works in
        #     telegram_inbound.py today (_CONFIRM_WORDS / _CONFIRM_QUESTION_WORDS
        #     + the namecard YES set) so switching to exact-match does NOT
        #     silently break confirmations users rely on. EXACT-match only.
        "好的", "好嘅", "係嘅", "就咁", "咁做", "冇錯", "正確", "嗯", "得",
        "同意", "執行", "建立", "開始", "okay", "sure", "go", "go ahead",
        "proceed", "confirmed", "approve", "approved", "accept", "do it",
        "create", "confirm",
    }
)
CANCEL_TOKENS: frozenset[str] = frozenset(
    {
        # --- basics (pre-existing) ---
        "唔使", "唔需要", "唔係", "取消", "不要", "唔好", "no", "n",
        # --- C4 (2026-09-10): widened to match _CANCEL_WORDS today ---
        "拒絕", "唔要", "算啦", "cancel", "reject", "decline", "stop", "abort",
    }
)
# C3 (2026-09-10): NUMERIC_TOKENS is DELIBERATELY EXCLUDED from
# DISCRETE_TOKENS. No consumer renders a numbered menu anywhere, so a stray
# 「1」 must NOT be able to execute a pending draft (that would be a NEW
# regression in the dangerous direction). The constant is kept (and exported)
# only as documentation / for tests asserting it is not claimable.
NUMERIC_TOKENS: frozenset[str] = frozenset({"1", "2", "3", "4", "5"})

DISCRETE_TOKENS: frozenset[str] = CONFIRM_TOKENS | CANCEL_TOKENS

# Trailing sentence punctuation tolerated on an otherwise-exact token (mirrors
# the `[!。.？?]*$` the old regexes allowed). This only strips *punctuation* —
# it never turns a phrase into a token, so the grammar stays exact.
_TRAILING_PUNCT = "!。.？?！，,、 "

# Defaults for the freshness / size gates.
DEFAULT_MAX_AGE_SECONDS = 7200  # 2 hours
DEFAULT_MAX_LEN = 40


def normalize_token(text: str) -> str:
    """Normalise a message the same way the grammar gate does.

    Trim → lower-case → strip trailing sentence punctuation. Consumers (the two
    interceptors) MUST use this so their ``tok in CONFIRM_TOKENS`` checks agree
    exactly with :func:`is_discrete_reply`; otherwise 「係！」 would pass the gate
    but miss the cancel/confirm branch.
    """
    if not text:
        return ""
    return text.strip().lower().rstrip(_TRAILING_PUNCT).strip()


def is_discrete_reply(text: str) -> bool:
    """True ONLY when the whole trimmed message is one exact token.

    Case-insensitive and whitespace-stripped. There is deliberately NO
    ``contains`` / prefix / suffix matching — that is what caused the
    original bug.
    """
    if not text:
        return False
    return normalize_token(text) in DISCRETE_TOKENS


def _origin_value(origin: object) -> str:
    try:
        if isinstance(origin, MessageOrigin):
            return origin.value
        return MessageOrigin(origin).value  # type: ignore[arg-type]
    except Exception:
        return repr(origin)


def may_text_reply_claim(
    origin: object,
    text: str,
    pending_age_seconds: float | None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    max_len: int = DEFAULT_MAX_LEN,
) -> tuple[bool, str]:
    """Can a text-reply interceptor claim this message?

    Returns ``(allowed, reason)``. ALL of the gates below must hold; the
    reason string names the first gate that failed (it is logged so any
    future swallow is visible in the journal).

      1. provenance — origin must be ``MessageOrigin.TYPED``
      2. grammar    — ``is_discrete_reply(text)`` (exact token only)
      3. freshness  — ``pending_age_seconds <= max_age_seconds``
      4. size       — ``len(text.strip()) <= max_len``
    """
    # a) provenance gate — voice / document / image / callback can NEVER be
    #    claimed by a text-reply interceptor.
    if not isinstance(origin, MessageOrigin):
        try:
            origin = MessageOrigin(origin)
        except Exception:
            return False, f"gate:origin-not-typed:{_origin_value(origin)}"
    if origin is not MessageOrigin.TYPED:
        return False, f"gate:origin-not-typed:{origin.value}"

    # b) grammar gate — exact token only.
    if not is_discrete_reply(text):
        return False, "gate:grammar-not-discrete-reply"

    # c) freshness gate — FAIL CLOSED on unknown age (C1, 2026-09-10). A legacy
    #    pending row with no stored timestamp could be months old; a bare 「係」
    #    must NOT be able to execute a stale CRM write. Unknown age = NOT
    #    claimable, so the message falls through to the AI instead.
    if pending_age_seconds is None:
        return False, "gate:age-unknown"
    age = pending_age_seconds
    if age > max_age_seconds:
        return False, f"gate:stale-pending:{int(age)}s>{int(max_age_seconds)}s"

    # d) size gate — belt-and-braces; discrete tokens are all far shorter.
    stripped_len = len((text or "").strip())
    if stripped_len > max_len:
        return False, f"gate:too-long:{stripped_len}>{max_len}"

    return True, "allowed"

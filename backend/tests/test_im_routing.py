"""Unit tests for the structural IM routing gates (KB-009 permanent fix).

Pure unit tests — no network, no DB. Run:

    backend/venv/bin/python -m pytest tests/test_im_routing.py -q

The MATRIX test is the permanent regression guard: it asserts that for every
non-typed origin (VOICE / DOCUMENT / IMAGE), ``may_text_reply_claim`` ALWAYS
returns False for every sample text — including confirm tokens. That makes the
"a document / voice transcript / image caption gets swallowed and recorded as
a fake meeting" class of bug impossible to reintroduce.
"""

import pytest

from app.services.im_routing import (
    CANCEL_TOKENS,
    CONFIRM_TOKENS,
    DISCRETE_TOKENS,
    NUMERIC_TOKENS,
    MessageOrigin,
    RouteDecision,
    is_discrete_reply,
    may_text_reply_claim,
)


# --- is_discrete_reply: exact tokens only --------------------------------

EXACT_TOKENS = sorted(DISCRETE_TOKENS)

NON_DISCRETE = [
    "確認一下",          # contains 確認 but is not the token
    "今日天氣",
    "幫我搵 Wilson Chan",
    "會議安排",
    "通告內容關於會議安排，詳情如下",
    "通告內容關於會議安排，詳情如下" + "等" * 470,  # ~500-char paste
    "係呀",
    "好呀",
    "唔使喇",
    "ok ok",
    "yes please",
    "會議",
    "1",                 # C3: numerics dropped — must NOT be claimable
    "2",
    "5",
    "",
    "   ",
    "6",
    "0",
    "abc",
    "開會",
    "約咗 Wilson",
]


@pytest.mark.parametrize("token", EXACT_TOKENS)
def test_exact_tokens_are_discrete(token):
    assert is_discrete_reply(token) is True


@pytest.mark.parametrize("token", EXACT_TOKENS)
def test_exact_tokens_case_insensitive_and_padded(token):
    assert is_discrete_reply(f"  {token.upper()}  ") is True


@pytest.mark.parametrize("text", NON_DISCRETE)
def test_non_discrete_replies_are_false(text):
    assert is_discrete_reply(text) is False


def test_confirm_and_cancel_token_sets_disjoint():
    assert CONFIRM_TOKENS.isdisjoint(CANCEL_TOKENS)
    # tokens that look like confirm/cancel but are NOT exact must not be included
    assert "確認一下" not in DISCRETE_TOKENS
    assert "對呀" not in DISCRETE_TOKENS


# --- MATRIX: non-typed origins can NEVER be claimed ----------------------

MATRIX_ORIGINS = [MessageOrigin.VOICE, MessageOrigin.DOCUMENT, MessageOrigin.IMAGE]
MATRIX_TEXTS = EXACT_TOKENS + NON_DISCRETE


@pytest.mark.parametrize("origin", MATRIX_ORIGINS)
@pytest.mark.parametrize("text", MATRIX_TEXTS)
def test_matrix_non_typed_origin_never_claimable(origin, text):
    """Regression guard: voice/document/image text is never claimable — even
    an exact confirm token — so no interceptor can ever swallow it."""
    allowed, reason = may_text_reply_claim(origin, text, pending_age_seconds=1)
    assert allowed is False, f"{origin} + {text!r} must never be claimable"
    assert reason.startswith("gate:origin-not-typed")


def test_matrix_callback_origin_never_claimable():
    allowed, reason = may_text_reply_claim(
        MessageOrigin.CALLBACK, "係", pending_age_seconds=1
    )
    assert allowed is False
    assert reason.startswith("gate:origin-not-typed")


# --- Gate-by-gate behaviour ----------------------------------------------

def test_typed_discrete_fresh_short_is_allowed():
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, "唔使", pending_age_seconds=100
    )
    assert allowed is True
    assert reason == "allowed"


def test_typed_non_discrete_is_rejected_by_grammar():
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, "今日天氣", pending_age_seconds=100
    )
    assert allowed is False
    assert reason == "gate:grammar-not-discrete-reply"


def test_freshness_age_100s_allowed():
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, "係", pending_age_seconds=100
    )
    assert allowed is True, reason


def test_freshness_age_20h_rejected():
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, "係", pending_age_seconds=20 * 3600
    )
    assert allowed is False
    assert reason.startswith("gate:stale-pending")


def test_freshness_boundary_exactly_max_age_allowed():
    allowed, _ = may_text_reply_claim(
        MessageOrigin.TYPED, "係", pending_age_seconds=7200
    )
    assert allowed is True


def test_length_10_chars_allowed_when_discrete():
    # a discrete token with surrounding whitespace stays short + exact
    allowed, _ = may_text_reply_claim(
        MessageOrigin.TYPED, "   確認   ", pending_age_seconds=10
    )
    assert allowed is True


def test_length_500_chars_rejected_by_size_gate():
    # 500 similar chars which are not a discrete token: grammar catches it
    # first, so also assert the size gate independently via max_len override.
    long_text = "確" * 500
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, long_text, pending_age_seconds=10
    )
    assert allowed is False
    assert reason == "gate:grammar-not-discrete-reply"

    # Force a discrete-looking token past grammar by making it discrete yet
    # longer than max_len via a tiny max_len — proves the size gate exists.
    allowed2, reason2 = may_text_reply_claim(
        MessageOrigin.TYPED, "確認", pending_age_seconds=10, max_len=1
    )
    assert allowed2 is False
    assert reason2.startswith("gate:too-long")


def test_unknown_age_fails_closed():
    """C2: `None` age (a legacy pending row with NO stored timestamp) must be
    NOT claimable — the old test enshrined the opposite (treated None as
    fresh), which let a months-old pending be claimed by a bare 「係」."""
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, "係", pending_age_seconds=None
    )
    assert allowed is False
    assert reason == "gate:age-unknown"


def test_numeric_tokens_are_not_claimable():
    """C3: numerics are dropped from DISCRETE_TOKENS — no numbered menu exists,
    so a stray 「1」 must never execute a pending draft."""
    for n in NUMERIC_TOKENS:
        assert is_discrete_reply(n) is False, n
        allowed, reason = may_text_reply_claim(
            MessageOrigin.TYPED, n, pending_age_seconds=10
        )
        assert allowed is False, n
        assert reason == "gate:grammar-not-discrete-reply"


# --- Real-incident regression cases (KB-009) ------------------------------

INCIDENT_TEXTS = [
    "今日天氣",
    "幫我搵 Wilson Chan",
    "通告內容關於會議安排，詳情如下",
    "通告內容關於會議安排，詳情如下" + "等" * 470,  # 500-char paste
    "會議",               # a DOCUMENT whose text contains 會議
]


@pytest.mark.parametrize("text", INCIDENT_TEXTS)
def test_incident_typed_messages_are_not_claimable(text):
    """The exact messages swallowed in production must fall through to the AI
    even when a pending follow-up is fresh."""
    allowed, reason = may_text_reply_claim(
        MessageOrigin.TYPED, text, pending_age_seconds=10
    )
    assert allowed is False, f"{text!r} must reach the AI"
    assert reason == "gate:grammar-not-discrete-reply"


@pytest.mark.parametrize("text", INCIDENT_TEXTS)
def test_incident_document_origin_with_meeting_text_not_claimable(text):
    """The whole uploaded PDF whose text contained 會議 must never be claimed."""
    allowed, reason = may_text_reply_claim(
        MessageOrigin.DOCUMENT, text, pending_age_seconds=10
    )
    assert allowed is False
    assert reason.startswith("gate:origin-not-typed")


def test_unknown_origin_denied():
    allowed, reason = may_text_reply_claim(
        "weird", "係", pending_age_seconds=1
    )
    assert allowed is False
    assert reason.startswith("gate:origin-not-typed")


def test_route_decision_shape():
    d = RouteDecision(consumer="ai", reply=None, reason="allowed")
    assert d.consumer == "ai"
    assert d.reply is None
    assert d.reason == "allowed"

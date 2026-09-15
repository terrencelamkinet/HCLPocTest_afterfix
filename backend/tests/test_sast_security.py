"""SAST 修復單元測試（2026-09-15 AppScan P0/P1）。

覆蓋：
  1. backend/app/services/html_sanitize.py — server 側 allowlist 清洗
  2. models/crm.py Note.content @validates — ORM 層自動清洗（所有寫入路徑）
  3. crm_todo.py _safe_upload_name — 上載檔名 path traversal
"""
from __future__ import annotations

import sys
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.html_sanitize import sanitize_note_html  # noqa: E402


# ── 1. html_sanitize ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "payload",
    [
        '<p>ok</p><script>window.x=1</script>',
        '<img src=x onerror="window.x=1">',
        '<iframe src="https://evil.example"></iframe>',
        '<a href="javascript:window.x=1">click</a>',
        '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
        '<svg/onload=alert(1)>',
        '<object data="evil.swf"></object>',
        '<style>@import url("//evil.example/x.css");</style>',
        '<div style="background:url(javascript:alert(1))">x</div>',
        '<form action="//evil.example"><input name="a"></form>',
    ],
)
def test_dangerous_constructs_removed(payload: str) -> None:
    out = sanitize_note_html(payload) or ""
    low = out.lower()
    assert "<script" not in low
    assert "onerror" not in low
    assert "<iframe" not in low
    assert "javascript:" not in low
    assert "<svg" not in low
    assert "<object" not in low
    assert "@import" not in low
    assert "data:text/html" not in low
    assert "<form" not in low


def test_tiptap_markup_preserved() -> None:
    """正常排版要保留：taskList 狀態、mention attrs、內部連結、表格。"""
    html = (
        '<ul data-type="taskList">'
        '<li data-type="taskItem" data-checked="true">'
        '<label><input type="checkbox" checked="checked"><span></span></label>'
        "<div><p>做完</p></div></li></ul>"
        '<p><span data-type="mention" data-record-mention="true" data-entity-type="contact"'
        ' data-entity-id="abc" data-label="陳大文">@陳大文</span></p>'
        '<p><strong>粗</strong><em>斜</em><a href="/companies/1">內部</a></p>'
        "<table><tbody><tr><td colspan=\"2\">cell</td></tr></tbody></table>"
    )
    out = sanitize_note_html(html) or ""
    assert 'data-checked="true"' in out
    assert "data-record-mention" in out
    assert 'data-label="陳大文"' in out
    assert 'href="/companies/1"' in out
    assert 'colspan="2"' in out
    assert "做完" in out


def test_none_and_empty_passthrough() -> None:
    assert sanitize_note_html(None) is None
    assert sanitize_note_html("") == ""


def test_non_string_passthrough() -> None:
    """避免 TypeError：非字串原樣返回（呼叫方自己處理）。"""
    assert sanitize_note_html(123) == 123


def test_link_gets_rel() -> None:
    out = sanitize_note_html('<a href="https://example.com">x</a>') or ""
    assert "noopener" in out and "noreferrer" in out


# ── 2. ORM 層 @validates ───────────────────────────────────────────────────
def test_note_model_validates_sanitizes_on_assignment() -> None:
    from app.models.crm import Note

    n = Note(title="t", content='<p>keep</p><script>bad()</script><img src=x onerror=1>')
    assert "<script" not in (n.content or "")
    assert "onerror" not in (n.content or "")
    assert "keep" in (n.content or "")


def test_note_model_validates_on_update() -> None:
    from app.models.crm import Note

    n = Note(title="t", content="<p>v1</p>")
    n.content = '<p>v2</p><iframe src="//evil"></iframe>'
    assert "<iframe" not in (n.content or "")
    assert "v2" in (n.content or "")


# ── 3. 上載檔名 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "../../pwned.txt",
        "..\\..\\pwned.txt",
        "/etc/passwd",
        "....//....//x.txt",
        ".env",
        "..",
        "",
    ],
)
def test_safe_upload_name_blocks_traversal(raw: str) -> None:
    from app.routers.crm_todo import _safe_upload_name

    out = _safe_upload_name(raw)
    assert "/" not in out and "\\" not in out
    assert ".." not in out
    assert not out.startswith(".")
    # 格式 = 8 位 hex prefix + "_" + 淨化後 basename
    assert re.fullmatch(r"[0-9a-f]{8}_[A-Za-z0-9._-]{1,80}", out), out


def test_safe_upload_name_keeps_extension() -> None:
    from app.routers.crm_todo import _safe_upload_name

    out = _safe_upload_name("報告 final.PDF")
    assert out.endswith(".PDF")
    assert " " not in out

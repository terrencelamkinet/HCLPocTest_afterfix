"""HTML 清洗 — Notes / editor 內容（2026-09-15 SAST / AppScan 修復）。

背景：`nexus_crm.notes.content` 係用戶（同 AI）提供嘅 HTML，前端用
`dangerouslySetInnerHTML` render。之前 server 完全冇清洗 → stored XSS
（note 內 <img onerror> 可以在其他 workspace 成員 browser 執行 → 偷
localStorage 內嘅 auth_token）。

設計：**唯一清洗邊界喺 ORM 層**（`Note.content` 嘅 `@validates`），
唔喺逐個 endpoint 加 guard —— 咁樣 create / update / restore revision /
template / AI 寫入 全部自動覆蓋，將來加新寫入路徑亦唔會漏。

用 nh3（Rust ammonia binding）：唔喺 allowlist 嘅 tag（script / iframe /
object / embed / svg…）連內容一齊刪；唔喺 allowlist 嘅 attribute（包括所有
`on*` event handler）自動 strip。Allowlist 對應前端 TipTap 實際用到嘅
extensions（StarterKit + underline + highlight + color/textStyle + link +
image + table + taskList + mention）。
"""
from __future__ import annotations

import re

import nh3

# ── tag allowlist（TipTap schema 對應）───────────────────────────────────
ALLOWED_TAGS: set[str] = {
    "p", "br", "hr",
    "strong", "b", "em", "i", "u", "s", "strike", "del", "mark", "sub", "sup",
    "code", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "a", "img",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "col",
    "label", "input", "div", "span",
}

# ── attribute allowlist（`*` = 所有 tag 通用）────────────────────────────
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"class", "style", "data-type", "data-checked"},  # data-checked = TipTap taskItem 狀態
    "a": {"href", "target"},  # rel 由 nh3 link_rel 統一設定（nh3 唔准同時 allow "rel"）
    "img": {"src", "alt", "title", "width", "height"},
    "input": {"type", "checked", "disabled"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    # @mention（notes V2）— 前端 + sync_note_mentions() 靠呢四個 attribute
    "span": {"data-record-mention", "data-entity-type", "data-entity-id", "data-label"},
}

# ── URL scheme allowlist（擋 javascript: / data: / vbscript: …）──────────
ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto", "tel"}

# style 內唔准嘅寫法（CSS 層 exfiltration / 舊 IE expression）
_BAD_STYLE = re.compile(r"(?i)(expression\s*\(|javascript\s*:|vbscript\s*:|url\s*\(|@import|behaviou?r\s*:|<\s*/?\s*script)")


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """回 None = 刪走呢個 attribute。"""
    if attr == "style":
        return None if _BAD_STYLE.search(value) else value
    if attr in ("href", "src"):
        v = value.strip()
        if v.startswith(("/", "#", "./", "../")):
            return value  # 相對路徑（內部 media URL）
        m = re.match(r"(?i)^([a-z][a-z0-9+.\-]*):", v)
        if m and m.group(1).lower() not in ALLOWED_URL_SCHEMES:
            return None
        return value
    return value


def sanitize_note_html(html: str | None) -> str | None:
    """清洗 note HTML。None / 空字串原樣返回（唔好將 None 變 ""）。"""
    if not html:
        return html
    if not isinstance(html, str):
        return html
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    return cleaned

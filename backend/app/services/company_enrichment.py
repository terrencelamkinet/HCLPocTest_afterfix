"""Company name web enrichment — 開源 Playwright，零外部資源。

用法：`enrich_company_web(query)` 對一個公司名做網上查證，回傳結構化 facts。
任何失敗一律 return None（caller fallback 去原本 extraction 行為），唔會 throw。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from playwright.async_api import async_playwright

# 非官方 / 唔應該當公司官方站嘅 domain（或 domain 內含呢啲字）→ skip
_NON_OFFICIAL = (
    "wikipedia", "linkedin", "facebook", "twitter", "x.com", "youtube",
    "crunchbase", "zoominfo", "glassdoor", "indeed", "bloomberg", "reuters",
    "google", "bing", "duckduckgo", "yelp", "trustpilot", "forbes", "cnbc",
    "bbc", "cnn", "yahoo", "news", "gov", "edu",
)

# 公司 domain 優先級（越前越 preferred）
_DOMAIN_PREF = (".com", ".com.hk", ".hk", ".cn", ".com.cn", ".net", ".org", ".io", ".co")

# 全頁 time budget（秒）— 所有 navigation 加埋唔好超
_TOTAL_BUDGET_SEC = 15.0


def _decode_ddg_href(href: str | None) -> str | None:
    """DDG html result 條 href 通常係 `//duckduckgo.com/l/?uddg=<urlencoded>` → decode 返真實 URL。"""
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        # urlsplit 處理 query 內有 & 嘅情況
        q = urllib.parse.urlsplit(href).query
        params = urllib.parse.parse_qs(q)
        uddg = params.get("uddg")
        if uddg:
            return urllib.parse.unquote(uddg[0])
    if href.startswith("http"):
        return href
    return None


def _decode_bing_href(href: str | None) -> str | None:
    """Bing `/ck/a` 結果係 redirect link，真實 URL 喺 `u=a1<base64>` param → decode。"""
    if not href:
        return None
    href = href.strip()
    if "u=a1" not in href:
        if href.startswith("http"):
            return href
        return None
    q = urllib.parse.urlsplit(href).query
    params = urllib.parse.parse_qs(q)
    u = (params.get("u") or [""])[0]
    if not u.startswith("a1"):
        return None
    b = u[2:]
    try:
        import base64 as _b64
        padded = b + "=" * ((4 - len(b) % 4) % 4)
        return _b64.b64decode(padded).decode("utf-8", errors="ignore") or None
    except Exception:
        return None


def _is_blacklisted(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).netloc or "").lower()
    for b in _NON_OFFICIAL:
        if b in host:
            return True
    return False


def _domain_pref_score(url: str) -> int:
    host = (urllib.parse.urlsplit(url).netloc or "").lower()
    for i, suf in enumerate(_DOMAIN_PREF):
        if host.endswith(suf):
            return len(_DOMAIN_PREF) - i
    return 0


def _clean_company_name(raw: str | None) -> str | None:
    """由 title / og:title 抽公司全名：drop tagline（` - ` / ` | ` 之後）、摺疊空白、cap length。"""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.strip())
    # 取第一個 separator 之前嘅 segment（e.g. 「新华三 - 融绘数字未来」→「新华三」）
    for sep in (" | ", " - ", " — ", " – ", " -", " |"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    s = s.strip(" -–—|,。")
    if not s:
        return None
    if len(s) > 120:
        s = s[:120].rstrip()
    return s


async def _search_ddg(page: Any, query: str) -> list[dict[str, Any]]:
    """DDG HTML search → top 5 results（decode uddg redirect）。"""
    search_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    await page.goto(search_url, timeout=8000, wait_until="domcontentloaded")
    results = await page.eval_on_selector_all(
        ".result",
        """els => els.slice(0, 5).map(el => {
            const a = el.querySelector('.result__a');
            const s = el.querySelector('.result__snippet');
            return {
              title: a ? (a.textContent || '').trim() : '',
              href: a ? (a.getAttribute('href') || '') : '',
              snippet: s ? (s.textContent || '').trim() : ''
            };
        })""",
    )
    decoded = []
    for r in results:
        url = _decode_ddg_href(r.get("href"))
        if url:
            decoded.append({"title": r.get("title", ""), "url": url, "snippet": r.get("snippet", "")})
    return decoded


async def _search_bing(page: Any, query: str) -> list[dict[str, Any]]:
    """Bing search fallback（DDG 喺 server IP 成日被 block）→ top 5 organic results。"""
    search_url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    await page.goto(search_url, timeout=8000, wait_until="domcontentloaded")
    results = await page.eval_on_selector_all(
        "li.b_algo",
        """els => els.slice(0, 5).map(el => {
            const h2 = el.querySelector('h2 a');
            const p = el.querySelector('p');
            return {
              title: h2 ? (h2.textContent || '').trim() : '',
              href: h2 ? (h2.getAttribute('href') || '') : '',
              snippet: p ? (p.textContent || '').trim() : ''
            };
        })""",
    )
    decoded = []
    for r in results:
        url = _decode_bing_href(r.get("href"))
        if url:
            decoded.append({"title": r.get("title", ""), "url": url, "snippet": r.get("snippet", "")})
    return decoded


def _pick_official(results: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    """由 DDG top results 揀官方站。

    Scoring：domain 包含 query token 加分最多；title 包含 query + 官方字眼加分；
    加埋 domain 優先級。揀唔到就 return None。
    """
    q_tokens = [t for t in re.split(r"[\s\W_]+", query.lower()) if t]
    best: dict[str, Any] | None = None
    best_score = -1.0
    for r in results:
        url = r.get("url") or ""
        title = (r.get("title") or "").lower()
        if not url or _is_blacklisted(url):
            continue
        host = (urllib.parse.urlsplit(url).netloc or "").lower()
        score = 0.0
        # domain 包含 query token → 最強訊號（例如 query「h3c」→ domain「h3c.com」）
        for tok in q_tokens:
            if tok and tok in host:
                score += 3.0
        # title 包含 query 關鍵字
        if any(tok and tok in title for tok in q_tokens):
            score += 1.5
        # title 有官方字眼
        if any(w in title for w in ("official", "官网", "官方", "官網")) and any(
            tok and tok in title for tok in q_tokens
        ):
            score += 1.0
        # domain 優先級
        score += _domain_pref_score(url) * 0.25
        if score > best_score:
            best_score = score
            best = r
    if best and best_score > 0:
        return best
    return None


def _extract_emails(text: str | None) -> list[str]:
    if not text:
        return []
    found = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    seen: list[str] = []
    for e in found:
        e = e.strip().lower().rstrip(".")
        if e and e not in seen and "example" not in e and "sentry" not in e and "wixpress" not in e:
            seen.append(e)
    return seen[:5]


def _extract_phones_strict(text: str | None) -> str | None:
    """強化電話抽取：HK 格式 / 國際格式優先；寧願 None 都唔好 partial garbage。

    - 優先揾完整帶 country code 嘅號碼（+852 / +86 / +1 等）
    - 唔好抽到 partial（例如淨得 8 位冇 country code 嘅，除非有明顯分隔格式）
    - 排除年份（20XX-20XX）、排除過長/過短
    回傳最完整嗰個（最長 digits）。搵唔到合格 → None。
    """
    if not text:
        return None
    candidates: list[str] = []
    # 1) 優先國際格式（含 +country code）
    for m in re.finditer(
        r"\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}", text
    ):
        candidates.append(m.group(0).strip())
    # 2) 其他帶多位分隔嘅本地號碼（如 1234 5678 / 1234-5678），但要整齊分隔
    for m in re.finditer(
        r"\b(?:\d{2,4}[\s\-]){1,2}\d{3,4}(?:[\s\-]\d{2,4})?\b", text
    ):
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if 6 <= len(digits) <= 15:
            candidates.append(cand)

    # 揀最完整（digits 最長、且有分隔符、優先帶 +）
    best: str | None = None
    best_score = -1
    for c in candidates:
        c = c.strip()
        digits = re.sub(r"\D", "", c)
        # 排除年份
        if re.fullmatch(r"(?:20\d{2})[\s\-]*(?:20\d{2})?", c) and len(digits) <= 8:
            continue
        if len(digits) < 7 or len(digits) > 15:
            continue
        score = len(digits)
        if c.startswith("+"):
            score += 10  # 帶 country code 優先
        if re.search(r"[\s\-]", c):
            score += 2  # 有分隔符更完整
        if score > best_score:
            best_score = score
            best = c
    return best


def _extract_address_from_text(text: str | None) -> str | None:
    """由頁面 text 抽地址 pattern（含 street/road/號嘅完整地址，優先 HK / 有 district）。"""
    if not text:
        return None
    # 地址 keyword（suffix）— 單字母縮寫要加 (?!\w) 確保係完整字（避免 St 撞 Stories/Store）
    kw = (
        r"(?:Floor|Floors?|Rd\.?(?!\w)|Road|St\.?(?!\w)|Street|Ave\.?(?!\w)|Avenue|Lane|"
        r"Place|Building|Buildings|Centre|Center|Plaza|Tower|Boulevard|Blvd|Highway|Hwy|Way)"
    )
    patterns = [
        r"[A-Za-z0-9 ,.\-/]{6,80}" + kw + r"(?=[\s,.]|$)[A-Za-z0-9 ,.\-/]{2,60}",
        r"\d{1,5}\s+[A-Za-z0-9 ,.\-]{4,60}(?:Street|St\.?(?!\w)|Road|Rd\.?(?!\w)|Avenue|Ave\.?(?!\w)|Lane|Boulevard|Blvd)",
        r"[^\n]{4,60}(?:區|市|县|縣|镇|鎮)[^\n]{0,50}(?:路|街|道|號|号|大厦|大廈|中心|广场|廣場)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            addr = re.sub(r"\s+", " ", m.group(0)).strip().strip(",.、，。")
            # 太短（<8）或太長（>140）唔算地址
            if 8 <= len(addr) <= 140:
                # 排除純 email / 純電話 pattern 誤判
                if re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", addr):
                    continue
                # 要含數字（樓號/街號/郵遞區號）先當地址 — 擋住 "Customer Stories" 呢類 nav phrase
                if not re.search(r"\d", addr):
                    continue
                return addr
    return None


def _extract_ceo_from_text(text: str | None) -> str | None:
    """由頁面 text 抽 CEO/創始人 附近嘅人名。Best-effort，搵唔到 → None，唔好 hallucinate。"""
    if not text:
        return None
    # 名稱唔應該包含呢啲 stopword（出現 = regex over-capture，唔算人名）
    STOP = (" the ", " of ", " and ", " at ", " our ", " company ", " founded ", " board ")
    # CEO 名通常喺 "CEO" / "Chief Executive Officer" / "行政總裁" / "創始人" 後 2-3 個詞
    ceo_pat = re.compile(
        r"(?:Chief Executive Officer|Chief Executive|CEO|行政總裁|行政总裁|总裁|總裁|創始人|创始人|Founder|Co-?founder)\s*[:：\-–—]*\s*"
        r"([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})"
    )
    m = ceo_pat.search(text)
    if m:
        name = m.group(1).strip()
        if 2 <= len(name.split()) <= 4 and len(name) <= 40 and not any(sw in f" {name} " for sw in STOP):
            return name
    # 試埋 name 喺 title 之前（"John Smith — CEO"）
    m2 = re.search(
        r"([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})\s*[\-–—:]\s*(?:CEO|Chief Executive Officer|行政總裁|創始人|Founder)",
        text,
    )
    if m2:
        name = m2.group(1).strip()
        if 2 <= len(name.split()) <= 4 and len(name) <= 40 and not any(sw in f" {name} " for sw in STOP):
            return name
    return None


def _extract_linkedin_from_search(results: list[dict[str, Any]]) -> str | None:
    """由 search results 抽 `linkedin.com/company/<slug>` URL（唔開 LinkedIn，防 block）。

    搵到第一個含 linkedin.com/company/ 嘅 href → 回傳（normalize 去 https://）。
    冇 → None。
    """
    for r in results or []:
        url = (r.get("url") or "").strip()
        if "linkedin.com/company/" in url.lower():
            # normalize：確保 https:// 開頭
            norm = url if url.startswith("http") else "https://" + url.lstrip("/")
            # 切走 query/fragment + 結尾 slash
            norm = norm.split("?")[0].split("#")[0].rstrip("/")
            if "linkedin.com/company/" in norm.lower():
                return norm
    return None


async def _search_linkedin(page: Any, query: str) -> str | None:
    """做一次 site:linkedin.com/company 嘅 search（DDG→Bing fallback），抽返 LinkedIn company URL。

    只係 search（唔開 LinkedIn 網頁，防 block bots）。搵唔到 → None。
    """
    lq = f'site:linkedin.com/company "{query}"' if query else ""
    if not lq:
        return None
    for searcher in (_search_ddg, _search_bing):
        try:
            results = await searcher(page, lq)
        except Exception:
            results = []
        if results:
            li = _extract_linkedin_from_search(results)
            if li:
                return li
    return None


async def _extract_address_from_page(page: Any) -> str | None:
    """由官方站抽地址：優先 JSON-LD schema（PostalAddress / Organization.address），

    fallback 去 footer / body text。冇 → None。
    """
    # 1) JSON-LD
    try:
        scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
        for raw in scripts:
            try:
                import json as _json
                data = _json.loads(raw)
            except Exception:
                continue
            # 支援單一 object 或 @graph list
            nodes = data if isinstance(data, list) else [data]
            for n in nodes:
                addr = None
                if isinstance(n, dict) and n.get("@type") in (
                    "PostalAddress", "Organization", "LocalBusiness", "Corporation",
                ):
                    a = n.get("address")
                    if isinstance(a, dict):
                        addr = " ".join(
                            str(a.get(k, "")) for k in (
                                "streetAddress", "addressLocality", "addressRegion",
                                "postalCode", "addressCountry",
                            ) if a.get(k)
                        ).strip()
                    elif isinstance(a, str) and a:
                        addr = a
                    elif isinstance(n, dict) and isinstance(n.get("address"), str):
                        addr = n.get("address")
                    if addr:
                        return re.sub(r"\s+", " ", addr).strip()
        # @graph 內可能係 list of dict
        for raw in scripts:
            try:
                import json as _json
                data = _json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("@graph"), list):
                for n in data["@graph"]:
                    if isinstance(n, dict) and isinstance(n.get("address"), dict):
                        addr = " ".join(str(n.get("address", {}).get(k, "")) for k in (
                            "streetAddress", "addressLocality", "addressRegion",
                            "postalCode", "addressCountry",
                        ) if n.get("address", {}).get(k)).strip()
                        if addr:
                            return re.sub(r"\s+", " ", addr).strip()
    except Exception:
        pass
    # 2) footer / body text fallback
    try:
        txt = await page.evaluate(
            """() => {
                const f = document.querySelector('footer');
                const body = document.body ? document.body.innerText : '';
                return (f ? f.innerText.slice(0, 2000) : '') + '\\n' + body.slice(0, 6000);
            }"""
        )
        return _extract_address_from_text(txt)
    except Exception:
        return None


async def _scrape_facts(page: Any, url: str, deadline: float, target_fields: list[str] | None = None, search_results: list[dict[str, Any]] | None = None, query: str | None = None) -> dict[str, Any]:
    """開官方站抽 facts。任何一步失敗都唔 throw（best-effort）。deadline = time.monotonic 上限。

    target_fields（可選，smart_fill existing_fields keys）：決定要唔要抽
    phone / address / ceo_name / linkedin_url。冇指定（None）= 抽齊晒（backward compatible）。
    search_results：由 search 步驟傳入，用嚟抽 linkedin_url（唔開 LinkedIn，防 block）。
    query：原始公司名，用嚟做額外 LinkedIn-targeted search（唔開 LinkedIn，只係 search）。
    """
    import time as _time
    wants = target_fields or []
    want = lambda k: (not target_fields) or (k in wants)  # noqa: E731 — None = 全部
    facts: dict[str, Any] = {
        "full_name": None,
        "domain": None,
        "website": url,
        "description": None,
        "phone": None,
        "address": None,
        "emails": [],
        "ceo_name": None,
        "linkedin_url": None,
    }
    try:
        facts["domain"] = (urllib.parse.urlsplit(url).netloc or "").replace("www.", "").lower()
    except Exception:
        pass
    # 先導航去官方站（title / og:title / meta 都要喺呢個 page 讀）
    try:
        await page.goto(url, timeout=8000, wait_until="domcontentloaded")
    except Exception:
        pass
    # title + og:title（prefer og:title，其次 page title）
    title_text = None
    og_title = None
    try:
        og_title = await page.eval_on_selector(
            'meta[property="og:title"]', "el => el.getAttribute('content')"
        )
    except Exception:
        pass
    try:
        if not og_title:
            title_text = await page.title()
    except Exception:
        pass
    name_src = (og_title or title_text or "").strip()
    facts["full_name"] = _clean_company_name(name_src) or None

    # meta description + og:description
    desc = None
    try:
        desc = await page.eval_on_selector(
            'meta[name="description"]', "el => el.getAttribute('content')"
        )
        if not desc:
            desc = await page.eval_on_selector(
                'meta[property="og:description"]', "el => el.getAttribute('content')"
            )
    except Exception:
        pass
    facts["description"] = (desc or "").strip() or None

    # 首個 h1
    try:
        h1 = await page.eval_on_selector("h1", "el => el.textContent")
        h1 = (h1 or "").strip()
        if h1 and len(h1) < 200 and not facts["full_name"]:
            facts["full_name"] = h1
        elif h1 and len(h1) < 200 and facts["full_name"] and h1 not in facts["full_name"]:
            pass
    except Exception:
        pass

    # ── body 抽 email（always）+ 電話 / 地址（視乎 target_fields）──
    page_text = ""
    try:
        page_text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 6000) : ''")
    except Exception:
        pass
    facts["emails"] = _extract_emails(page_text + " " + (desc or ""))

    # LinkedIn URL：由 search results 抽（唔開 LinkedIn 網頁，防 block）
    if want("linkedin_url"):
        if search_results:
            li = _extract_linkedin_from_search(search_results)
            if li:
                facts["linkedin_url"] = li
        # 未搵到 → 做一次 LinkedIn-targeted search（site: 限定，只係 search 唔開網頁）
        if not facts["linkedin_url"] and query and _time.monotonic() < deadline:
            li2 = await _search_linkedin(page, query)
            if li2:
                facts["linkedin_url"] = li2

    # 電話（field-driven 強化）
    if want("phone"):
        ph = _extract_phones_strict(page_text)
        if ph:
            facts["phone"] = ph

    # 地址（field-driven）— homepage JSON-LD + footer regex
    if want("address"):
        addr = await _extract_address_from_page(page)
        if addr:
            facts["address"] = addr

    # ── best-effort 開子頁（/about /about-us /contact /contact-us /leadership /team）──
    # 每個子頁都有獨立 timeout guard（deadline 內先開；每個 page 自身 4000ms）
    core_subs = ("/about", "/about-us", "/about/", "/contact", "/contact-us")
    ceo_subs = ("/about", "/about-us", "/about/", "/leadership", "/team", "/team/")
    # 已用 home text 抽過嘅，睇下仲有冇嘢要補
    for sub in core_subs:
        if _time.monotonic() > deadline:
            break
        try:
            sub_url = urllib.parse.urljoin(url, sub)
            await page.goto(sub_url, timeout=4000, wait_until="domcontentloaded")
            sub_text = await page.evaluate(
                "() => document.body ? document.body.innerText.slice(0, 6000) : ''"
            )
            sms = _extract_emails(sub_text)
            for e in sms:
                if e not in facts["emails"]:
                    facts["emails"].append(e)
            if want("phone") and not facts["phone"]:
                ph2 = _extract_phones_strict(sub_text)
                if ph2:
                    facts["phone"] = ph2
            if want("address") and not facts["address"]:
                addr2 = _extract_address_from_text(sub_text)
                if addr2:
                    facts["address"] = addr2
            # CEO：喺 /about 頁先試抽（避免為 CEO 開多幾頁）
            if want("ceo_name") and not facts["ceo_name"] and sub.startswith("/about"):
                ceo = _extract_ceo_from_text(sub_text)
                if ceo:
                    facts["ceo_name"] = ceo
        except Exception:
            continue  # 失敗就 skip，唔好令成個 function 失敗

    # CEO 仍未有 + field-driven + 未超時 → 專門去 leadership/team 頁
    if want("ceo_name") and not facts["ceo_name"]:
        for sub in (s for s in ceo_subs if not s.startswith("/about")):
            if _time.monotonic() > deadline:
                break
            try:
                sub_url = urllib.parse.urljoin(url, sub)
                await page.goto(sub_url, timeout=4000, wait_until="domcontentloaded")
                sub_text = await page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 6000) : ''"
                )
                ceo = _extract_ceo_from_text(sub_text)
                if ceo:
                    facts["ceo_name"] = ceo
                    break
            except Exception:
                continue

    return facts


async def enrich_company_web(query: str, target_fields: list[str] | None = None) -> dict | None:
    """開源 browser 公司 enrichment：DDG search → 揀官方站 → 抽 facts。

    target_fields：需要收集嘅 form fields（smart_fill 嘅 existing_fields keys）。
    按 target_fields 決定抽咩 facts（phone/address/ceo_name/linkedin_url）—
    冇指定就抽核心 set（backward compatible，None = 抽齊）。
    任何失敗 return None（caller fallback 去原本行為）。總 budget ~15s。
    """
    if not query or not query.strip():
        return None
    import time as _time
    _deadline = _time.monotonic() + _TOTAL_BUDGET_SEC
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    )
                )
                page = await context.new_page()

                # Step 1 — Search（DDG 主，被 block 時 fallback Bing）
                decoded: list[dict[str, Any]] = []
                for searcher in (_search_ddg, _search_bing):
                    try:
                        decoded = await searcher(page, query)
                    except Exception:
                        decoded = []
                    if decoded:
                        break

                # Step 2 — 揀官方站
                best = _pick_official(decoded, query)
                if not best:
                    return None

                # Step 3 — 開官方站抽 facts（field-driven）
                facts = await _scrape_facts(page, best["url"], _deadline, target_fields, decoded, query)
                return facts
            finally:
                await browser.close()
    except Exception:
        # 任何失敗（browser 起唔到 / sandbox / network）都 graceful → None
        return None

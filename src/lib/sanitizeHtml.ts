/**
 * HTML 清洗（2026-09-15 SAST / AppScan：dangerouslySetInnerHTML 修復）。
 *
 * Server 端已經係權威清洗邊界（backend/app/services/html_sanitize.py，nh3 allowlist），
 * 呢個係 second layer：萬一有舊數據 / 新路徑漏洗，或者內容經其他渠道入 DB，
 * 前端 render 之前再洗一次。
 *
 * 用 DOMParser + allowlist（無新 dependency）：
 *  - 唔喺 allowlist 嘅 tag → 拆走 tag 只保留文字（同 server 行為一致）
 *  - attribute 逐個檢查：通用 class/style/data-*（style 過濾 url()/expression()）、
 *    a[href,target,rel]、img[src,alt]、mention span 嘅 data-entity-* …
 *  - javascript: / data: / vbscript: 之類 scheme 一律唔准入 DOM
 */

const OK_TAGS = new Set([
  'P', 'BR', 'HR', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'STRIKE', 'DEL', 'MARK', 'SUB', 'SUP',
  'CODE', 'PRE', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'UL', 'OL', 'LI', 'A', 'IMG', 'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TD', 'TH',
  'COLGROUP', 'COL', 'LABEL', 'INPUT', 'DIV', 'SPAN',
]);

const OK_ATTRS: Record<string, Set<string>> = {
  // ⚠️ 要同 backend/app/services/html_sanitize.py 嘅 ALLOWED_ATTRIBUTES 對齊：
  // 呢層只可以再收窄，唔可以比 server 洗得更狠（否則 taskItem 狀態 / mention label 會唔見）。
  '*': new Set(['class', 'style', 'data-type', 'data-checked', 'data-id']),
  A: new Set(['href', 'target', 'rel']),
  IMG: new Set(['src', 'alt', 'title', 'width', 'height']),
  INPUT: new Set(['type', 'checked', 'disabled']),
  TD: new Set(['colspan', 'rowspan']),
  TH: new Set(['colspan', 'rowspan', 'scope']),
  COL: new Set(['span']),
  SPAN: new Set(['data-record-mention', 'data-entity-type', 'data-entity-id', 'data-label']),
};

const OK_SCHEMES = new Set(['http:', 'https:', 'mailto:', 'tel:']);
const BAD_STYLE = /(expression\s*\(|javascript\s*:|url\s*\(|@import)/i;

const attrAllowed = (tag: string, attr: string): boolean =>
  OK_ATTRS['*'].has(attr) || (OK_ATTRS[tag]?.has(attr) ?? false);

const safeValue = (attr: string, value: string): boolean => {
  if (attr === 'style') return !BAD_STYLE.test(value);
  if (attr === 'href' || attr === 'src') {
    const v = value.trim();
    if (v.startsWith('/') || v.startsWith('#') || v.startsWith('./')) return true;
    const m = /^([a-z][a-z0-9+.-]*):/i.exec(v);
    if (!m) return true; // 相對 URL
    return OK_SCHEMES.has(`${m[1].toLowerCase()}:`);
  }
  return true;
};

/** 清洗 HTML 字串。任何例外 → 回空字串（唔好將未洗過嘅內容注入 DOM）。 */
export function sanitizeHtml(html: string | null | undefined): string {
  if (!html) return '';
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const out = document.createElement('div');
    const walk = (src: Node, dst: Node): void => {
      src.childNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          dst.appendChild(document.createTextNode(node.textContent ?? ''));
          return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        const el = node as Element;
        const tag = el.tagName.toUpperCase();
        if (!OK_TAGS.has(tag)) {
          walk(el, dst); // 唔准嘅 tag → 保文字，唔保 tag
          return;
        }
        const clone = document.createElement(el.tagName.toLowerCase());
        for (const attr of Array.from(el.attributes)) {
          const name = attr.name.toLowerCase();
          if (!attrAllowed(tag, name) || !safeValue(name, attr.value)) continue;
          try {
            clone.setAttribute(name, attr.value);
          } catch {
            /* 非法 attribute 名 → 略過 */
          }
        }
        if (tag === 'A') {
          clone.setAttribute('rel', 'noopener noreferrer nofollow');
        }
        walk(el, clone);
        dst.appendChild(clone);
      });
    };
    walk(doc.body, out);
    return out.innerHTML;
  } catch {
    return '';
  }
}

// @vitest-environment happy-dom
/**
 * sanitizeHtml 單元測試（2026-09-15 SAST）。
 * 同 backend/tests/test_sast_security.py 對應：兩層 allowlist 行為要一致。
 */
import { describe, expect, it } from 'vitest';
import { sanitizeHtml } from './sanitizeHtml';

const DANGEROUS = [
  '<p>ok</p><script>window.x=1</script>',
  '<img src=x onerror="window.x=1">',
  '<iframe src="https://evil.example"></iframe>',
  '<a href="javascript:window.x=1">click</a>',
  '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
  '<svg/onload=alert(1)>',
  '<object data="evil.swf"></object>',
  '<div style="background:url(javascript:alert(1))">x</div>',
  '<div style="width:expression(alert(1))">x</div>',
  '<form action="//evil.example"><input name="a"></form>',
];

describe('sanitizeHtml — 危險構造', () => {
  it.each(DANGEROUS)('洗走 %s', (payload) => {
    const out = sanitizeHtml(payload).toLowerCase();
    expect(out).not.toContain('<script');
    expect(out).not.toContain('onerror');
    expect(out).not.toContain('<iframe');
    expect(out).not.toContain('javascript:');
    expect(out).not.toContain('<svg');
    expect(out).not.toContain('<object');
    expect(out).not.toContain('expression(');
    expect(out).not.toContain('data:text/html');
    expect(out).not.toContain('<form');
  });

  it('保留文字內容（只拆 tag，唔食字）', () => {
    expect(sanitizeHtml('<p>保留我</p><script>x</script>')).toContain('保留我');
  });

  it('on* event handler 一律唔入 DOM', () => {
    const out = sanitizeHtml('<p onclick="x()" onmouseover="y()">t</p>');
    expect(out).not.toContain('onclick');
    expect(out).not.toContain('onmouseover');
    expect(out).toContain('t');
  });
});

describe('sanitizeHtml — TipTap 正常排版要保留', () => {
  const html =
    '<ul data-type="taskList">' +
    '<li data-type="taskItem" data-checked="true">' +
    '<label><input type="checkbox" checked="checked"><span></span></label>' +
    '<div><p>做完</p></div></li></ul>' +
    '<p><span data-type="mention" data-record-mention="true" data-entity-type="contact"' +
    ' data-entity-id="abc" data-label="陳大文">@陳大文</span></p>' +
    '<p><strong>粗</strong><em>斜</em><a href="/companies/1">內部</a></p>' +
    '<table><tbody><tr><td colspan="2">cell</td></tr></tbody></table>';

  it('保留 taskList 狀態 + mention attrs + 連結 + 表格', () => {
    const out = sanitizeHtml(html);
    expect(out).toContain('data-checked="true"');
    expect(out).toContain('data-record-mention');
    expect(out).toContain('data-label="陳大文"');
    expect(out).toContain('href="/companies/1"');
    expect(out).toContain('colspan="2"');
    expect(out).toContain('做完');
  });

  it('a[rel] 自動加 noopener', () => {
    expect(sanitizeHtml('<a href="https://example.com">x</a>')).toContain('noopener');
  });

  it('相對路徑 / 錨點 / mailto 放行', () => {
    expect(sanitizeHtml('<a href="#top">t</a>')).toContain('href="#top"');
    expect(sanitizeHtml('<a href="./x">t</a>')).toContain('href="./x"');
    expect(sanitizeHtml('<a href="mailto:a@b.com">t</a>')).toContain('mailto:');
  });
});

describe('sanitizeHtml — 邊界', () => {
  it('空值 → 空字串', () => {
    expect(sanitizeHtml('')).toBe('');
    expect(sanitizeHtml(null)).toBe('');
    expect(sanitizeHtml(undefined)).toBe('');
  });

  it('純文字原樣返回', () => {
    expect(sanitizeHtml('hello 世界')).toBe('hello 世界');
  });

  it('server / frontend allowlist 要對齊（同一份 payload 兩邊都唔可以洗走）', () => {
    const out = sanitizeHtml(html());
    for (const attr of ['data-checked', 'data-label', 'data-record-mention', 'data-type']) {
      expect(out).toContain(attr);
    }
  });
});

function html(): string {
  return (
    '<ul data-type="taskList"><li data-type="taskItem" data-checked="true">x</li></ul>' +
    '<p><span data-type="mention" data-entity-type="contact" data-record-mention="true"' +
    ' data-label="A">@A</span></p>'
  );
}

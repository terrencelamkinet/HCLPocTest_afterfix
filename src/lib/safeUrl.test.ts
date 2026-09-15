// @vitest-environment happy-dom
/** safeExternalUrl 單元測試（2026-09-15 SAST：window.open 傳染）。 */
import { describe, expect, it } from 'vitest';
import { isSafeExternalUrl, safeExternalUrl } from './safeUrl';

const ORIGIN = window.location.origin;

describe('safeExternalUrl — 放行', () => {
  it('絕對 http / https（URL 正規化會補 trailing slash）', () => {
    expect(safeExternalUrl('https://example.com/a')).toBe('https://example.com/a');
    expect(safeExternalUrl('http://example.com')).toBe('http://example.com/');
  });

  it('內部路徑（單斜線開頭）', () => {
    expect(safeExternalUrl('/companies/1')).toBe('/companies/1');
    expect(safeExternalUrl('/api/v1/media/x.png')).toBe('/api/v1/media/x.png');
  });

  it('相對路徑會 resolve 成同源 URL', () => {
    expect(safeExternalUrl('image.png')).toBe(`${ORIGIN}/image.png`);
  });
});

describe('safeExternalUrl — 擋', () => {
  it('javascript: / data: / vbscript: / file:', () => {
    expect(safeExternalUrl('javascript:window.x=1')).toBeNull();
    expect(safeExternalUrl('JavaScript:alert(1)')).toBeNull();
    expect(safeExternalUrl('data:text/html,<script>x</script>')).toBeNull();
    expect(safeExternalUrl('vbscript:msgbox(1)')).toBeNull();
    expect(safeExternalUrl('file:///etc/passwd')).toBeNull();
  });

  it('protocol-relative //evil.com（會走去其他 origin）', () => {
    expect(safeExternalUrl('//evil.example/x')).toBeNull();
  });

  it('前後有空白嘅 javascript:', () => {
    expect(safeExternalUrl('   javascript:alert(1)  ')).toBeNull();
  });

  it('空值', () => {
    expect(safeExternalUrl('')).toBeNull();
    expect(safeExternalUrl('   ')).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
  });
});

describe('isSafeExternalUrl', () => {
  it('同 safeExternalUrl 一致', () => {
    expect(isSafeExternalUrl('https://example.com')).toBe(true);
    expect(isSafeExternalUrl('/x')).toBe(true);
    expect(isSafeExternalUrl('javascript:x')).toBe(false);
    expect(isSafeExternalUrl(null)).toBe(false);
  });
});

/**
 * URL scheme 安全檢查（2026-09-15 SAST / AppScan：window.open 傳染）。
 *
 * 所有 `window.open(...)` / 動態 link 嘅目標都可能來自 server 或 AI 輸出，
 * 之前冇檢查 scheme → `javascript:` / `data:` URL 可以喺 opener context 執行。
 * 呢度只准 http(s)（同內部相對路徑），其他一律 null。
 */

export function safeExternalUrl(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null;
  const v = url.trim();
  if (!v) return null;
  // 內部路徑：只准單斜線開頭。
  // `//evil.example` 係 protocol-relative，new URL() 會將佢 resolve 成 http://evil.example
  // → 一定要喺度擋（單元測試 src/lib/safeUrl.test.ts 有 case）。
  if (v.startsWith('/')) return v.startsWith('//') ? null : v;
  try {
    const u = new URL(v, window.location.origin);
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.toString() : null;
  } catch {
    return null;
  }
}

export const isSafeExternalUrl = (url: string | null | undefined): boolean => safeExternalUrl(url) !== null;

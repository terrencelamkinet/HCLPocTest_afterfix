// @vitest-environment happy-dom
/**
 * Session hint 測試 — 2026-09-15 SAST（AppScan「Web, Local Storage Insecure」）。
 *
 * 守住核心不變量：**localStorage 唔准出現任何 token**。session 授權一律喺
 * httpOnly cookie，前端只可以存 email + 提示用到期時間。
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { getSession, storeSession, clearAuth, isAuthenticated } from './api';

const LEGACY = 'nexus_crm_auth';
const HINT = 'nexus_session';

describe('session hint（localStorage 唔可以有 token）', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('storeSession 只寫 email + 到期時間，冇 token', () => {
    storeSession('a@b.com');
    const raw = localStorage.getItem(HINT) || '';
    expect(JSON.parse(raw).email).toBe('a@b.com');
    expect(typeof JSON.parse(raw).expires).toBe('number');
    // JWT 一定係 "eyJ..." 開頭；access/refresh token 都唔應該出現喺 storage
    expect(raw).not.toMatch(/eyJ/);
    expect(raw).not.toMatch(/access_token|refresh_token/);
  });

  it('storeSession 會清走舊版遺留嘅 nexus_crm_auth（嗰個 key 有真 token）', () => {
    localStorage.setItem(
      LEGACY,
      JSON.stringify({ access_token: 'eyJleak', refresh_token: 'eyJleak' }),
    );
    storeSession('a@b.com');
    expect(localStorage.getItem(LEGACY)).toBeNull();
  });

  it('clearAuth 清走 hint 同舊 legacy key', () => {
    storeSession('a@b.com');
    localStorage.setItem(LEGACY, '{"access_token":"x"}');
    clearAuth();
    expect(localStorage.getItem(HINT)).toBeNull();
    expect(localStorage.getItem(LEGACY)).toBeNull();
    expect(isAuthenticated()).toBe(false);
  });

  it('isAuthenticated 跟 session hint（真正授權由 cookie 決定）', () => {
    expect(isAuthenticated()).toBe(false);
    storeSession('a@b.com');
    expect(isAuthenticated()).toBe(true);
    expect(getSession()?.email).toBe('a@b.com');
  });

  it('壞 JSON 唔會 throw（storage 被改壞都唔好炒 app）', () => {
    localStorage.setItem(HINT, '{not json');
    expect(getSession()).toBeNull();
  });
});

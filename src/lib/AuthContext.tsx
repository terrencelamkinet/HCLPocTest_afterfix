/**
 * Penguin CRM Auth Context
 *
 * Provides login, logout, and user state across the app.
 * Session 由 httpOnly cookie 帶（2026-09-15 SAST）；呢度只係存非敏感 session hint。
 */

import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import {
  login as apiLogin,
  sendMfa,
  verifyMfa as apiVerifyMfa,
  storeSession,
  clearAuth,
  getSession,
  logoutSession,
} from './api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AuthUser {
  email: string;
  displayName?: string;
  /** Google 頭像或自己上載嘅頭像 URL（相對路徑 → 同源）。 */
  avatarUrl?: string;
  locale?: string;
  timezone?: string;
}

export interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<'mfa' | 'success'>;
  verifyMfa: (otp: string) => Promise<void>;
  logout: () => void;
  sendMfaCode: () => Promise<void>;
  /** 重新由 /auth/me 拉最新 profile（改名／換頭像之後用）。 */
  refreshMe: () => Promise<void>;
  mfaEmail: string;
}

const AuthContext = createContext<AuthState | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [mfaEmail, setMfaEmail] = useState('');

  // Fetch real user profile from backend. 授權靠 httpOnly cookie → 唔需要（亦冇）
  // Authorization header；cookie 無效就係 401 → 回 null。
  const fetchMe = useCallback(async (): Promise<AuthUser | null> => {
    try {
      const res = await fetch('/api/v1/auth/me', { credentials: 'include' });
      if (!res.ok) return null;
      const me = await res.json();
      return {
        email: me.email,
        displayName: me.display_name || undefined,
        avatarUrl: me.avatar_url || undefined,
        locale: me.locale || undefined,
        timezone: me.timezone || undefined,
      };
    } catch {
      return null;
    }
  }, []);

  const applyMe = useCallback((me: AuthUser | null, fallbackEmail?: string) => {
    if (me) setUser(me);
    else if (fallbackEmail) setUser({ email: fallbackEmail });
  }, []);

  // 改名／換頭像之後由呼叫方主動 refresh（AuthContext 唔會輪詢）
  const refreshMe = useCallback(async () => {
    const me = await fetchMe();
    if (me) setUser(me);
  }, [fetchMe]);

  // Mount：用 session hint 即刻 render，再問 /auth/me 確認 cookie 仲有效。
  // ⚠️ 冇 hint 就唔打 /auth/me（唔好每次開 sign-in 頁都打一次）；hint 有但
  //    /auth/me 401 → cookie 已經死 → 清 hint（AuthGuard 會轉去 sign-in）。
  useEffect(() => {
    const hint = getSession();
    if (hint) {
      setUser({ email: hint.email });
      fetchMe().then((me) => {
        if (me) setUser(me);
        else {
          clearAuth();
          setUser(null);
        }
      });
    }
    setLoading(false);
  }, [fetchMe]);

  const login = useCallback(async (email: string, password: string): Promise<'mfa' | 'success'> => {
    const res = await apiLogin(email, password);

    if (res.mfa_required) {
      setMfaEmail(email);
      await sendMfa(email);
      return 'mfa';
    }

    // cookie 已經由 server 種（HttpOnly，JS 讀唔到）— 前端只記非敏感 hint
    storeSession(email);
    setUser({ email });
    fetchMe().then((me) => applyMe(me, email));
    setMfaEmail('');
    return 'success';
  }, [fetchMe, applyMe]);

  const sendMfaCode = useCallback(async () => {
    if (mfaEmail) {
      await sendMfa(mfaEmail);
    }
  }, [mfaEmail]);

  const verifyMfa = useCallback(async (otp: string) => {
    if (!mfaEmail) throw new Error('No MFA session');
    const res = await apiVerifyMfa(mfaEmail, otp);
    void res; // body 仍然有 token（向後兼容 CLI／e2e），前端唔再存
    storeSession(mfaEmail);
    setUser({ email: mfaEmail });
    fetchMe().then((me) => applyMe(me, mfaEmail));
    setMfaEmail('');
  }, [mfaEmail, fetchMe, applyMe]);

  const logout = useCallback(() => {
    // server 清 cookie + revoke session（fire-and-forget，UI 唔等）
    void logoutSession();
    setUser(null);
    setMfaEmail('');
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, verifyMfa, logout, sendMfaCode, refreshMe, mfaEmail }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

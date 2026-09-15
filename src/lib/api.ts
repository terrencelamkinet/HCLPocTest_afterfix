/**
 * Penguin CRM API Client
 *
 * Session 授權由 **httpOnly cookie** 帶（2026-09-15 SAST，對應 AppScan
 * 「Web, Local Storage Insecure」finding）。前端唔會再接觸 access/refresh token：
 *
 *   - 之前：`localStorage['nexus_crm_auth']` 存 access_token + refresh_token
 *     → 任何 XSS 都可以一次過偷走 24 小時有效嘅 token。
 *   - 現在：cookie（HttpOnly + SameSite=Lax + Secure）由瀏覽器自動帶，JS 讀唔到。
 *     localStorage 只留一個**非敏感提示**（email + 提示用到期時間），令 UI 可以即刻
 *     render，真正嘅授權判斷一律由後端 cookie 決定（401 → refresh → 或者去 sign-in）。
 *
 * 同源：API 同 SPA 同一個 origin（生產 nginx proxy、dev Vite proxy），所以每次
 * fetch 都用 `credentials: 'include'`。
 */

const API_BASE = ''; // Same-origin via Vite proxy (/api/* → :8001)

/** 舊 key（≤v7.88.8）：入面有真 token，登入／登出時一定要清走。 */
const LEGACY_AUTH_KEY = 'nexus_crm_auth';
const SESSION_KEY = 'nexus_session';

// ---------------------------------------------------------------------------
// Session hint（非敏感）
// ---------------------------------------------------------------------------

/** localStorage 只存呢啲：冇 token、冇 secret，唔可以當授權憑證。 */
export interface StoredSession {
  email: string;
  /** 提示用（UI 早 refresh）；真正授權由 cookie 決定。 */
  expires: number;
}

export function getSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    return parsed && typeof parsed.email === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

export function storeSession(email: string): void {
  try {
    localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ email, expires: Date.now() + 1439 * 60 * 1000 }),
    );
    // 順手清走舊版遺留嘅 token（升級後第一次登入就會清到）
    localStorage.removeItem(LEGACY_AUTH_KEY);
  } catch {
    /* localStorage 唔可用（私隱模式）— session hint 唔係必需 */
  }
}

export function clearAuth(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(LEGACY_AUTH_KEY);
  } catch {
    /* ignore */
  }
}

/** 有冇 session hint。真正嘅 401 由 api() 統一處理（refresh → sign-in）。 */
export function isAuthenticated(): boolean {
  return getSession() !== null;
}

// ---------------------------------------------------------------------------
// Session refresh（cookie-based，冇 token 喺 JS）
// ---------------------------------------------------------------------------

let refreshing: Promise<boolean> | null = null;

/** POST /auth/refresh — refresh token 由 cookie 帶（body 留空，向後兼容）。 */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
          credentials: 'include',
        });
        return res.ok;
      } catch {
        return false;
      }
    })();
    // 清 dedupe 鎖（唔阻住 caller 拎結果）
    refreshing.then(
      () => { refreshing = null; },
      () => { refreshing = null; },
    );
  }
  return refreshing;
}

// ---------------------------------------------------------------------------
// API Error
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, body: any) {
    super(body?.detail || body?.message || `HTTP ${status}`);
    this.status = status;
    this.detail = body?.detail || '';
  }
}

/**
 * 由 API error 抽「人睇得明」嘅文字。
 *
 * ⚠️ 必須經呢度：FastAPI 嘅 422 會回 `detail: [{type, loc, msg, input, ctx}, ...]`
 * （pydantic 結構化 error）。如果直接 `setError(e.detail)` 再 render，
 * React 會 throw "Objects are not valid as a React child"（error #31）→ **整頁白屏**。
 * 2026-09-11 實測：URL 帶一個唔存在嘅 notebook id → 422 → Notes 整頁 crash。
 */
export function errText(e: any): string | null {
  const d = e?.detail;
  if (typeof d === 'string' && d) return d;
  if (Array.isArray(d)) {
    const parts = d.map((x: any) => {
      if (typeof x === 'string') return x;
      const where = Array.isArray(x?.loc) ? x.loc[x.loc.length - 1] : '';
      return x?.msg ? (where ? `${where}: ${x.msg}` : String(x.msg)) : '';
    }).filter(Boolean);
    if (parts.length) return parts.join('；');
  }
  if (d && typeof d === 'object') {
    if (typeof (d as any).msg === 'string') return (d as any).msg;
    if (typeof (d as any).code === 'string') return (d as any).code;
  }
  return typeof e?.message === 'string' && e.message ? e.message : null;
}

/** UUID v4-ish 檢查 — 唔可以用「唔係 all/uncat 就當係 uuid」，否則 URL 有 junk
    （例如 /notes/n/undefined）會將 `notebook_id=undefined` 送去 API → 422。 */
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// ---------------------------------------------------------------------------
// Generic fetch
// ---------------------------------------------------------------------------

/** 將 401 轉去 /sign-in（清 hint + 唔好喺 sign-in 頁再跳）。 */
function redirectToSignIn(): void {
  clearAuth();
  const currentPath = window.location.pathname;
  if (!currentPath.startsWith('/sign-in')) {
    window.location.href = '/sign-in';
  }
}

export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const doFetch = async (): Promise<{ res: Response; body: any }> => {
    const isForm = options.body instanceof FormData;
    const headers: Record<string, string> = {
      // JSON default, but skip Content-Type for FormData (browser sets boundary)
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers as Record<string, string>),
    };

    // 冇 Authorization header：session 喺 httpOnly cookie，由 browser 自動帶
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: 'include',
    });
    const body = res.status === 204 ? undefined : await res.json().catch(() => ({}));
    return { res, body };
  };

  let { res, body } = await doFetch();

  // On 401, try refreshing the session once (deduplicates concurrent attempts)
  if (res.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) {
      ({ res, body } = await doFetch());
    }
  }

  // If still 401 after refresh attempt, redirect to sign-in
  if (res.status === 401) {
    redirectToSignIn();
    throw new ApiError(401, { detail: 'Unauthorized' });
  }

  // No content (204)
  if (res.status === 204) return undefined as T;

  if (!res.ok) {
    throw new ApiError(res.status, body);
  }

  return body as T;
}

// ---------------------------------------------------------------------------
// Convenience methods
// ---------------------------------------------------------------------------

export interface GetOptions { params?: Record<string, string>; signal?: AbortSignal }

/** Append a `?k=v` query string (URL-encoded) to a path. */
function withQuery(path: string, params?: Record<string, string>): string {
  if (!params) return path
  const qs = Object.entries(params)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
  return qs ? `${path}${path.includes('?') ? '&' : '?'}${qs}` : path
}

export const apiClient = {
  get: <T = any>(path: string, opts?: GetOptions) =>
    api<T>(withQuery(path, opts?.params), opts?.signal ? { signal: opts.signal } : {}),
  post: <T = any>(path: string, data?: any) =>
    api<T>(path, { method: 'POST', body: data ? JSON.stringify(data) : undefined }),
  /** POST multipart/form-data (skips JSON stringify; cookie auth attached automatically).
   *  2026-09-13：加可選 signal（v4 MD suggestion T2 — 批量上載「取消」要真 abort in-flight request）。 */
  postForm: <T = any>(path: string, formData: FormData, signal?: AbortSignal) =>
    api<T>(path, { method: 'POST', body: formData, ...(signal ? { signal } : {}) }),
  put: <T = any>(path: string, data: any) =>
    api<T>(path, { method: 'PUT', body: JSON.stringify(data) }),
  patch: <T = any>(path: string, data: any) =>
    api<T>(path, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: <T = any>(path: string) =>
    api<T>(path, { method: 'DELETE' }),
};

/** Upload a file (multipart/form-data). Returns parsed JSON body. */
export async function uploadFile<T = any>(path: string, file: File, extraFields?: Record<string, string>): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  if (extraFields) {
    for (const [k, v] of Object.entries(extraFields)) form.append(k, v);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body: form,
    credentials: 'include',
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) {
      redirectToSignIn();
    }
    throw new ApiError(res.status, body);
  }
  return body as T;
}

// ---------------------------------------------------------------------------
// Auth-specific endpoints
// ---------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  refresh_token: string;
  mfa_required: boolean;
  email: string;
  device_token: string | null;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
    credentials: 'include',
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

export async function signup(email: string, password: string, display_name: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, display_name }),
    credentials: 'include',
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

export async function forgotPassword(email: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
    credentials: 'include',
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

export async function resetPassword(token: string, password: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
    credentials: 'include',
  });
  const body = await res.json();
  if (!res.ok) throw new ApiError(res.status, body);
  return body;
}

export async function sendMfa(email: string): Promise<void> {
  await api('/api/v1/auth/send-mfa', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

export async function verifyMfa(email: string, otp_code: string): Promise<LoginResponse> {
  return api<LoginResponse>('/api/v1/auth/verify-mfa', {
    method: 'POST',
    body: JSON.stringify({ email, otp_code }),
  });
}

/** 登出：server 清 cookie + revoke refresh session（冇 token 要傳）。 */
export async function logoutSession(): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      credentials: 'include',
    });
  } catch {
    /* 網絡問題都好，前端一定要清 hint */
  }
  clearAuth();
}

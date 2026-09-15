// Admin Console API client — JWT (shared trust domain with main site) + 403 gate
const API_BASE: string = (import.meta.env.VITE_API_BASE as string) || ''
const TOKEN_KEY = 'adm_token'

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) {
    super(msg)
    this.status = status
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string> | undefined) }
  if (opts.body) headers['Content-Type'] = 'application/json'
  const tok = getToken()
  if (tok) headers['Authorization'] = `Bearer ${tok}`
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers })
  if (res.status === 401 || res.status === 403) {
    throw new ApiError(res.status, 'unauthorized')
  }
  if (!res.ok) {
    let detail = res.statusText
    try { const d = await res.json(); detail = d?.detail || detail } catch { /* ignore */ }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export interface LoginResp {
  access_token: string
  refresh_token?: string
  mfa_required?: boolean
  email?: string
}

export async function login(email: string, password: string): Promise<LoginResp> {
  return api<LoginResp>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function fmtMoney(n: number): string {
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}
export function fmtNum(n: number): string {
  return n.toLocaleString('en-US')
}

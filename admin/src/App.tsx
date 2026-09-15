import { useEffect, useRef, useState } from 'react'
import './admin.css'
import { api, ApiError, getToken, login, setToken, type LoginResp } from './api'
import { ReportsPage } from './pages/ReportsPage'
import { OverviewPage } from './pages/OverviewPage'
import { TenantsPage } from './pages/TenantsPage'
import { UsagePage } from './pages/UsagePage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { SystemPage } from './pages/SystemPage'
import { I18nPage } from './pages/I18nPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { ErrorsPage } from './pages/ErrorsPage'
import { AuditPage } from './pages/AuditPage'
import { StatusPage } from './pages/StatusPage'

type PageKey = 'reports' | 'overview' | 'tenants' | 'usage' | 'connections' | 'system' | 'notifications' | 'platform' | 'i18n' | 'errors' | 'audit' | 'status'

const NAV: { key: PageKey; label: string; icon: string; group?: string }[] = [
  { key: 'overview', label: 'Overview 總覽', icon: '📊' },
  { key: 'tenants', label: 'Tenants 租戶', icon: '🏢', group: '監控 Monitoring' },
  { key: 'errors', label: '錯誤監控 Errors', icon: '🚨' },
  { key: 'status', label: '服務狀態 Status', icon: '📡' },
  { key: 'usage', label: 'AI Usage 用量', icon: '🤖' },
  { key: 'connections', label: 'Connections 連接', icon: '🔌', group: '基建 Infrastructure' },
  { key: 'system', label: 'System 系統', icon: '🖥️' },
  { key: 'reports', label: '報表中心 Reports', icon: '📈', group: '管理 Management' },
  { key: 'audit', label: '審計報告 Audit', icon: '🔍' },
  { key: 'i18n', label: 'i18n 翻譯管理', icon: '🌐' },
  { key: 'notifications', label: '通知系統', icon: '🔔' },
  { key: 'platform', label: 'Platform 平台設定', icon: '⚙️' },
]

const TITLES: Record<PageKey, string> = {
  reports: '📈 報表中心 Reports', overview: '📊 Overview 總覽', tenants: '🏢 Tenants 租戶',
  usage: '🤖 AI Usage 用量', connections: '🔌 Connections 連接',
  system: '🖥️ System 系統', i18n: '🌐 i18n 翻譯管理', notifications: '🔔 通知系統', platform: '⚙️ Platform 平台設定',
  errors: '🚨 錯誤監控 Errors',
  audit: '🔍 審計報告 Audit',
  status: '📡 服務狀態 Status',
}

function LoginView({ onAuthed }: { onAuthed: () => void }) {
  const [email, setEmail] = useState('terrence_lam@kinetix.com.hk')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [otp, setOtp] = useState(false)
  const [otpCode, setOtpCode] = useState('')

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await login(email, password)
      if (r.mfa_required) { setOtp(true); return }
      setToken(r.access_token)
      onAuthed()
    } catch (e) {
      setErr(e instanceof ApiError ? (e.status === 403 ? '此帳號無 admin 權限（403）' : e.message) : '登入失敗')
    } finally { setBusy(false) }
  }

  const submitOtp = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setBusy(true); setErr('')
    try {
      // Main-site MFA is optional & off for the admin account — v1 guard
      const r = await api<LoginResp>('/api/v1/auth/mfa/verify', { method: 'POST', body: JSON.stringify({ email, code: otpCode }) })
      setToken(r.access_token); onAuthed()
    } catch (e) { setErr(e instanceof ApiError ? e.message : '驗證失敗') } finally { setBusy(false) }
  }

  return (
    <div id="loginView">
      <div className="login-wrap">
        <div className="login-side">
          <div>
            <div className="brand">🐧 PenguinCRM</div>
            <h2>企業級 AI CRM<br />統一管理控制台</h2>
            <p>adm.penguincrm.io — 集中監控全平台租戶、用量、系統健康與安全事件。</p>
            <div className="feat">
              <div><span className="dot" style={{ background: 'var(--primary)' }} /> 即時監控租戶用量與成本</div>
              <div><span className="dot" style={{ background: 'var(--primary)' }} /> 真數據報表中心（usage_events）</div>
              <div><span className="dot" style={{ background: 'var(--primary)' }} /> 獨立後台 — admin-only 權限</div>
            </div>
          </div>
          <div className="foot">© 2026 PenguinCRM · adm.penguincrm.io · v1.0.0</div>
        </div>
        <div className="login-form">
          {!otp ? (
            <form onSubmit={submit}>
              <h1 style={{ margin: 0 }}>管理員登入</h1>
              <div className="sub" style={{ margin: '6px 0 20px' }}>使用您的管理員帳號登入控制台</div>
              <div className="lfield"><label>Email</label>
                <div className="iwrap"><input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" /><span className="ic">✉️</span></div>
              </div>
              <div className="lfield"><label>密碼</label>
                <div className="iwrap"><input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" placeholder="••••••••" /><span className="ic">👁️</span></div>
              </div>
              {err && <div className="login-err">⚠️ {err}</div>}
              <button className="lbtn" disabled={busy || !email || !password}>
                {busy ? <span className="spinner" /> : null}{busy ? '驗證中...' : '登入控制台'}
              </button>
            </form>
          ) : (
            <form onSubmit={submitOtp}>
              <div className="back-link" onClick={() => setOtp(false)}>← 返回</div>
              <h1 style={{ margin: 0 }}>兩步驟驗證</h1>
              <div className="sub" style={{ margin: '6px 0 16px' }}>驗證碼已發送至 {email.replace(/^(.{2}).*(@.*)$/, '$1***$2')}</div>
              <div className="lfield"><label>6 位驗證碼</label>
                <input type="text" value={otpCode} onChange={e => setOtpCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="••••••" style={{ height: 44, width: '100%', borderRadius: 10, border: '1.5px solid var(--border)', padding: '0 13px', fontSize: 18, letterSpacing: 8, textAlign: 'center' }} />
              </div>
              {err && <div className="login-err">⚠️ {err}</div>}
              <button className="lbtn" disabled={busy || otpCode.length < 6}>{busy ? <span className="spinner" /> : null}{busy ? '驗證中...' : '驗證並登入'}</button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [page, setPage] = useState<PageKey>('overview')
  const [sideOpen, setSideOpen] = useState(false)
  const [toasts, setToasts] = useState<{ id: number; msg: string; type: string }[]>([])
  const toastId = useRef(0)

  const toast = (msg: string, type = 'ok') => {
    const id = ++toastId.current
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 2600)
  }

  const nav = (k: PageKey) => { setPage(k); setSideOpen(false) }
  const navStr = (p: string) => nav(p as PageKey)

  let prevGroup = ''
  const pageComp = (() => {
    const props = { toast, onLogout }
    switch (page) {
      case 'reports': return <ReportsPage {...props} onNav={navStr} />
      case 'overview': return <OverviewPage {...props} onNav={navStr} />
      case 'tenants': return <TenantsPage {...props} />
      case 'errors': return <ErrorsPage {...props} />
      case 'audit': return <AuditPage {...props} />
      case 'status': return <StatusPage {...props} />
            case 'usage': return <UsagePage {...props} />
      case 'connections': return <ConnectionsPage {...props} />
      case 'system': return <SystemPage {...props} />
      case 'i18n': return <I18nPage {...props} />
      default: return <PlaceholderPage title={TITLES[page]} onNav={navStr} />
    }
  })()

  return (
    <div id="appShell" className="active">
      <div className="sidebar-overlay" id="sideOverlay" style={{ display: sideOpen ? 'block' : 'none' }} onClick={() => setSideOpen(false)} />
      <div className={`sidebar ${sideOpen ? 'open' : ''}`}>
        <div className="logo">🐧 PenguinCRM Admin<small>adm.penguincrm.io</small></div>
        <nav id="navlist">
          {NAV.map(n => {
            const groupLabel = n.group && n.group !== prevGroup ? (prevGroup = n.group, <div className="navgroup-label">{n.group}</div>) : null
            return (
              <span key={n.key}>
                {groupLabel}
                <a className={page === n.key ? 'active' : ''} onClick={() => nav(n.key)}>
                  {n.icon} {n.label}
                </a>
              </span>
            )
          })}
        </nav>
      </div>
      <div className="main">
        <div className="topbar">
          <div className="tleft">
            <div className="hamburger" onClick={() => setSideOpen(v => !v)}>☰</div>
            <h1 id="pageTitle">{TITLES[page]}</h1>
          </div>
          <div className="right">
            <div className="arch-pill"><span className="seg"><span className="adot" />FE</span>→<span className="seg"><span className="adot" />API</span>→<span className="seg"><span className="adot" style={{ background: '#e8912a' }} />DB</span></div>
            <div className="avatar" title="登出" onClick={onLogout} style={{ cursor: 'pointer' }}>TL</div>
          </div>
        </div>
        <div className="content">
          {pageComp}
        </div>
      </div>
      <div className="toast-wrap">
        {toasts.map(t => (
          <div key={t.id} className={`toast show ${t.type}`}>
            {t.type === 'ok' ? '✅ ' : '⚠️ '}{t.msg}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  useEffect(() => {
    if (!getToken()) return
    // verify token still valid + admin on load
    api('/api/v1/admin/overview').then(() => setAuthed(true)).catch(() => { setToken(null); setAuthed(false) })
  }, [])
  if (!authed) return <LoginView onAuthed={() => setAuthed(true)} />
  return <Shell onLogout={() => { setToken(null); setAuthed(false) }} />
}

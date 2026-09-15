import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Maximize2 } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'
import CommandPalette from './CommandPalette'
import { apiClient } from '../../lib/api'
import { useAuth } from '../../lib/AuthContext'
import { useToast } from './useToast'
import { useNavigate } from 'react-router-dom'

/* ═══════════════════════════════════════════════════════════
   HeaderV2 — Centralized Topbar
   - Search trigger AND the AI pill both open CommandPalette
     (⌘K) — the single entry point for search, navigation,
     quick-create actions, and natural-language AI queries.
   - New(+) dropdown includes a direct "Ask AI" shortcut.
   - Notifications + user menu are fully wired (click-outside
     to close, badge counts, real content).
   ═══════════════════════════════════════════════════════════ */

export default function HeaderV2() {
  const { t } = useTranslation()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  // 2026-09-12：初始主題要同 DOM 實際狀態一致。
  // 之前 fallback 'dark' 但 DOM 冇 data-theme 時 :root 其實係淺色 →
  // toggle 顯示錯狀態，要撳兩次先真正切到。
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'))
  const [notifications, setNotifications] = useState<any[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const newRef = useRef<HTMLDivElement>(null)
  const notifRef = useRef<HTMLDivElement>(null)
  const userRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(true) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (newRef.current && !newRef.current.contains(e.target as Node)) setNewOpen(false)
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false)
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  useEffect(() => {
    apiClient.get<{ items: any[]; total: number }>('/api/v1/notifications?page=1&page_size=8')
      .then(d => setNotifications(d.items || [])).catch(() => {})
    apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count')
      .then(d => setUnreadCount(d.unread_count || 0)).catch(() => {})
  }, [])

  // ── Notification polling + alert ──
  // Poll unread-count every 30s so new notifications surface without a reload,
  // and pop a toast alert the moment the unread count increases.
  const { showToast } = useToast()
  const lastUnreadRef = useRef<number | null>(null)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const { unread_count } = await apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count')
        if (!alive) return
        const prev = lastUnreadRef.current
        lastUnreadRef.current = unread_count
        setUnreadCount(unread_count)
        if (prev !== null && unread_count > prev) {
          showToast(t('header.newNotificationsAlert', { defaultValue: '🔔 你有 {{count}} 則新通知', count: unread_count }))
          // Refresh the dropdown list so it shows the newest items.
          apiClient.get<{ items: any[]; total: number }>('/api/v1/notifications?page=1&page_size=8')
            .then(d => setNotifications(d.items || [])).catch(() => {})
        }
      } catch { /* silent — transient network errors must not spam */ }
    }
    poll() // initial baseline (no toast on first load)
    const timer = setInterval(poll, 30000)
    return () => { alive = false; clearInterval(timer) }
  }, [showToast, t])

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.setAttribute('data-theme', next)
    localStorage.setItem('nexus-theme', next)
  }

  const initials = (user?.displayName || 'U').split(' ').map((s: string) => s[0]).slice(0, 2).join('').toUpperCase()

  return (
    <>
      <header className="hdr2-bar">
        <div className="hdr2-left">
          <div className="hdr2-search-wrap">
            <button className="hdr2-search-trigger" onClick={() => setPaletteOpen(true)}>
              <span className="hdr2-search-badge"><SvcIcon name="penguin-ai" size={13} /></span>
              <span className="hdr2-search-placeholder">{t('search.triggerPlaceholder', { defaultValue: '搜尋或詢問 AI…' })}</span>
              <kbd className="hdr2-search-kbd">⌘K</kbd>
            </button>
            <button className="hdr2-search-expand" onClick={() => navigate('/search')} aria-label="Open full search page" title={t('header.openSearchFull', { defaultValue: '開啟完整搜尋頁面' })}>
              <Maximize2 size={15} />
            </button>
          </div>
        </div>

        <div className="hdr2-right">
          <div className="hdr2-new-wrap" ref={newRef}>
            <button className="hdr2-new-btn" onClick={() => setNewOpen(v => !v)} aria-label="Create new" title={t('quickAction.title', { defaultValue: '快速新增' })}>
              <SvcIcon name="plus" size={18} />
            </button>
            <div className={`hdr2-new-dropdown ${newOpen ? 'open' : ''}`}>
              <button className="hdr2-new-dropdown-item" onClick={() => { setNewOpen(false); navigate('/contacts?new=1') }}><SvcIcon name="users" size={14} /> {t('quickAction.newContact', { defaultValue: '新增聯絡人' })}</button>
              <button className="hdr2-new-dropdown-item" onClick={() => { setNewOpen(false); navigate('/tasks?new=1') }}><SvcIcon name="check-square" size={14} /> {t('quickAction.newTask', { defaultValue: '新增任務' })}</button>
              <div className="hdr2-new-dropdown-divider" />
              <button className="hdr2-new-dropdown-item" onClick={() => { setNewOpen(false); setPaletteOpen(true) }}><SvcIcon name="sparkles" size={14} /> {t('quickAction.aiQuery', { defaultValue: '問 AI 一個問題' })}</button>
            </div>
          </div>

          <button className="hdr2-icon-btn" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === 'dark' ? <SvcIcon name="sun" size={18} /> : <SvcIcon name="moon" size={18} />}
          </button>

          <div className="hdr2-notif-wrap" ref={notifRef}>
            <button className="hdr2-icon-btn" onClick={() => setNotifOpen(v => !v)} aria-label="Notifications">
              <SvcIcon name="bell" size={18} />
              {unreadCount > 0 && <span className="hdr2-notif-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>
            <div className={`hdr2-notif-panel ${notifOpen ? 'open' : ''}`}>
              <div className="hdr2-notif-header">
                <span>{t('header.notifications', { defaultValue: '通知' })}</span>
                {unreadCount > 0 && <span className="hdr2-notif-count">{unreadCount} {t('header.new', { defaultValue: '則新通知' })}</span>}
                <button className="hdr2-notif-viewall" onClick={() => { setNotifOpen(false); navigate('/notifications') }}>{t('header.viewAll', { defaultValue: '查看全部' })} →</button>
              </div>
              <div className="hdr2-notif-list">
                {notifications.length === 0 ? (
                  <div className="hdr2-notif-empty">{t('header.noNotifications', { defaultValue: '暫無通知' })}</div>
                ) : notifications.map((n) => (
                  <div key={n.id} className={`hdr2-notif-item ${n.status === 'UNREAD' ? 'unread' : ''}`}>
                    <div className="hdr2-notif-item-title">{n.title}</div>
                    <div className="hdr2-notif-item-body">{n.body}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="hdr2-user-wrap" ref={userRef}>
            <button className="hdr2-user-btn" onClick={() => setUserOpen(v => !v)}>
              <div className="hdr2-avatar">{initials}</div>
              <SvcIcon name="chevron-down" size={14} className="hdr2-chevron" />
            </button>
            <div className={`hdr2-user-dropdown ${userOpen ? 'open' : ''}`}>
              <div className="hdr2-user-info">
                <div className="hdr2-user-name">{user?.displayName}</div>
                <div className="hdr2-user-email">{user?.email}</div>
              </div>
              <button className="hdr2-user-dropdown-item" onClick={() => { setUserOpen(false); navigate('/settings') }}><SvcIcon name="user" size={14} /> {t('header.profile', { defaultValue: '個人資料' })}</button>
              <button className="hdr2-user-dropdown-item" onClick={() => { setUserOpen(false); navigate('/settings') }}><SvcIcon name="settings" size={14} /> {t('header.settings', { defaultValue: '設定' })}</button>
              <button className="hdr2-user-dropdown-item danger" onClick={logout}><SvcIcon name="log-out" size={14} /> {t('header.logout', { defaultValue: '登出' })}</button>
            </div>
          </div>
        </div>
      </header>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  )
}

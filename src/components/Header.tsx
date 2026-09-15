import SvcIcon from '../components/SvcIcon';
import { Activity, Building2, CheckSquare, FileText, FolderKanban, Users } from 'lucide-react'
import { useAuth } from '../lib/AuthContext';
import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../lib/api';
import { useTranslation } from 'react-i18next';
import MobileSearchSheet from './MobileSearchSheet';

// Desktop top-bar global search result type (mirrors MobileSearchSheet)
interface TopBarSearchResult {
  id: string;
  type: string;
  label: string;
  sub: string;
  url: string;
}

const TOPBAR_TYPE_ICONS: Record<string, any> = {
  contact: Users,
  company: Building2,
  task: CheckSquare,
  project: FolderKanban,
  touchpoint: Activity,
  note: FileText,
};

export default function Header() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const [aiEnabled, setAiEnabled] = useState(true); // default show until loaded

  // ── Desktop top-bar global search (mirrors MobileSearchSheet behaviour) ──
  const [topQuery, setTopQuery] = useState('');
  const [topResults, setTopResults] = useState<TopBarSearchResult[]>([]);
  const [topLoading, setTopLoading] = useState(false);
  const [topOpen, setTopOpen] = useState(false);
  const topSearchRef = useRef<HTMLDivElement>(null);
  const topInputRef = useRef<HTMLInputElement>(null);
  const topTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const topReqRef = useRef(0);

  // Immediate search — Enter / search button / debounce all funnel here.
  // Race-guarded: stale responses (older request id) are dropped.
  const runTopSearch = useCallback(async () => {
    const id = ++topReqRef.current;
    const q = topQuery.trim();
    if (!q) { setTopResults([]); setTopLoading(false); setTopOpen(false); return; }
    setTopLoading(true);
    try {
      const data = await apiClient.get<{ results: TopBarSearchResult[] }>(
        `/api/v1/crm/search?q=${encodeURIComponent(q)}&limit=10`
      );
      if (id === topReqRef.current) { setTopResults((data?.results || []).filter(r => r.type !== 'deal')); setTopOpen(true); }
    } catch {
      if (id === topReqRef.current) setTopResults([]);
    } finally {
      if (id === topReqRef.current) setTopLoading(false);
    }
  }, [topQuery]);

  // Trigger the search now — cancels any pending debounce first
  const runTopSearchNow = () => {
    if (topTimerRef.current) { clearTimeout(topTimerRef.current); topTimerRef.current = undefined; }
    void runTopSearch();
  };

  // Blur search — live debounced search as you type (200ms, same as MobileSearchSheet)
  useEffect(() => {
    const q = topQuery.trim();
    if (!q) { setTopResults([]); setTopLoading(false); setTopOpen(false); return; }
    setTopLoading(true);
    if (topTimerRef.current) clearTimeout(topTimerRef.current);
    topTimerRef.current = setTimeout(() => { void runTopSearch(); }, 200);
    return () => { if (topTimerRef.current) clearTimeout(topTimerRef.current); };
  }, [topQuery, runTopSearch]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (topSearchRef.current && !topSearchRef.current.contains(e.target as Node)) setTopOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const topSearchGo = (url: string) => {
    setTopOpen(false);
    setTopQuery('');
    setTopResults([]);
    navigate(url);
  };

  const topSearchClear = () => {
    setTopQuery('');
    setTopResults([]);
    setTopOpen(false);
    topInputRef.current?.focus();
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Listen for AI module changes
  const loadModuleState = () => {
    apiClient.get('/api/v1/crm/module-settings').then((list: any) => {
      const ai = (list || []).find((m: any) => m.module_key === 'ai_assistant');
      if (ai) setAiEnabled(ai.enabled);
    }).catch(() => {});
  };
  useEffect(() => {
    loadModuleState();
    window.addEventListener('modules-changed', loadModuleState);
    return () => window.removeEventListener('modules-changed', loadModuleState);
  }, []);

  // Mobile sidebar toggle
  useEffect(() => {
    const shell = document.getElementById('appShell');
    if (shell) {
      shell.classList.toggle('mobile-open', mobileOpen);
    }
  }, [mobileOpen]);

  // Sync with scrim close from Layout
  useEffect(() => {
    const handler = () => setMobileOpen(false);
    window.addEventListener('close-mobile-menu', handler);
    return () => window.removeEventListener('close-mobile-menu', handler);
  }, []);

  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('nexus-theme');
    if (saved) return saved === 'dark';
    return document.documentElement.getAttribute('data-theme') === 'dark';
  });

  useEffect(() => {
    const theme = dark ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('nexus-theme', theme);
  }, [dark]);

  const [notifOpen, setNotifOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifList, setNotifList] = useState<any[]>([]);
  const notifRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const fetchNotifs = async () => {
    try {
      const { unread_count } = await apiClient.get('/api/v1/notifications/unread-count');
      setUnreadCount(unread_count);
      if (notifOpen) {
        const { items } = await apiClient.get('/api/v1/notifications?page_size=5');
        setNotifList(items || []);
      }
    } catch {}
  };

  useEffect(() => {
    if (!notifOpen) return
    fetchNotifs()
    const t = setInterval(fetchNotifs, 15000)
    return () => clearInterval(t)
  }, [notifOpen]);
  useEffect(() => { if (notifOpen) fetchNotifs(); }, [notifOpen]);

  const handleNotifClick = async (n: any) => {
    try { await apiClient.patch(`/api/v1/notifications/${n.id}/read`, {}); } catch {}
    if (n.action_url) navigate(n.action_url);
    setNotifOpen(false);
  };

  /* T5 fix (2026-09-07): Header 要用 display_name（同 Profile form 一致）— 唔好淨係 email 推
     display_name 有 → initials/名用 display_name；冇（舊帳戶）→ fallback email prefix */
  const fullName = user?.displayName?.trim() || user?.email?.split('@')[0].replace('.', ' ') || 'User';
  const initials = user?.displayName?.trim()
    ? user.displayName.trim().split(/\s+/).map(s => s[0]).join('').toUpperCase().slice(0, 2)
    : (user?.email ? user.email.split('@')[0].split('.').map(s => s[0]).join('').toUpperCase().slice(0, 2) : '?');
  const displayName = fullName.charAt(0).toUpperCase() + fullName.slice(1);

  return (
    <>
      <header className="topbar">
      {/* Hamburger — mobile only */}
      <button className="topbar-hamburger icon-btn" onClick={() => setMobileOpen(!mobileOpen)}
        aria-label={t('common.close')}>
        <div className={`ham-icon${mobileOpen ? ' open' : ''}`}>
          <span></span><span></span><span></span>
        </div>
      </button>
      {/* Mobile search icon — opens bottom sheet (design04 pattern) */}
      <button className="topbar-search-icon icon-btn" onClick={() => setSearchOpen(true)}
        aria-label={t('header.searchPlaceholder')}>
        <SvcIcon name="search" size={19} />
      </button>
      <div className="topbar-search" ref={topSearchRef}>
        <SvcIcon name="search" />
        <input
          ref={topInputRef}
          type="text"
          value={topQuery}
          onChange={(e) => setTopQuery(e.target.value)}
          onFocus={() => { if (topQuery.trim()) setTopOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); runTopSearchNow(); }
            if (e.key === 'Escape') setTopOpen(false);
          }}
          placeholder={t('header.searchPlaceholder')}
        />
        {topQuery && (
          <button className="topbar-search-clear" onClick={topSearchClear} aria-label={t('common.clear')}>
            <SvcIcon name="x" size={14} />
          </button>
        )}
        <button className="topbar-search-btn" onClick={runTopSearchNow} aria-label={t('common.search')} title={t('common.search')}>
          <SvcIcon name="search" size={15} />
        </button>
        {topOpen && topQuery.trim() && (
          <div className="topbar-search-dropdown">
            {topLoading && topResults.length === 0 && (
              <div className="topbar-search-msg">{t('common.loading', '載入中…')}</div>
            )}
            {!topLoading && topResults.length === 0 && (
              <div className="topbar-search-msg">{t('header.searchNoResults')}</div>
            )}
            {topResults.map((r) => {
              const Icon = TOPBAR_TYPE_ICONS[r.type] || FileText;
              return (
                <button key={r.type + r.id} className="topbar-search-item" onClick={() => topSearchGo(r.url)}>
                  <span className={`topbar-search-item-icon topbar-search-item-icon--${r.type}`}>
                    <Icon size={15} />
                  </span>
                  <span className="topbar-search-item-body">
                    <span className="topbar-search-item-label">{r.label}</span>
                    {r.sub && <span className="topbar-search-item-sub">{r.sub}</span>}
                  </span>
                  <span className="topbar-search-item-type">{r.type}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="topbar-actions">
        <button className="icon-btn" onClick={() => setDark(!dark)} title={t('header.toggleTheme')}>
          {dark ? <SvcIcon name="sun" /> : <SvcIcon name="moon" />}
        </button>
        <div className="relative" ref={notifRef}>
          <button className="icon-btn" onClick={() => setNotifOpen(!notifOpen)} style={{display:aiEnabled?'':'none'}}>
            <SvcIcon name="bell" />
            {unreadCount > 0 && <span className="notif-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>}
          </button>
          {notifOpen && (
            <div className="notif-dropdown">
              <div className="notif-head">
                <span>{t('header.notifications')}</span>
                <button className="text-xs" style={{color:'var(--color-primary)',fontWeight:600,background:'none',border:'none',cursor:'pointer'}}
                  onClick={async () => { try{await apiClient.post('/api/v1/notifications/read-all');setUnreadCount(0);setNotifList([])}catch{} }}>
                  {t('notifications.markAllRead')}
                </button>
              </div>
              {notifList.length === 0 ? (
                <div className="notif-empty">{t('notifications.empty')}</div>
              ) : notifList.map((n: any) => (
                <div key={n.id} className={`notif-item${n.status === 'UNREAD' ? ' unread' : ''}`}
                  onClick={() => handleNotifClick(n)}>
                  <div className="notif-title">{n.title}</div>
                  {n.body && <div className="notif-body">{n.body}</div>}
                  <div className="notif-meta">
                    <span className={`notif-priority ${n.priority?.toLowerCase()}`}>{n.priority}</span>
                    {n.source_module && <span>{n.source_module}</span>}
                    <span>{n.created_at ? new Date(n.created_at).toLocaleTimeString('zh-HK',{hour:'2-digit',minute:'2-digit'}) : ''}</span>
                  </div>
                </div>
              ))}
              <div className="notif-foot" onClick={() => { navigate('/notifications'); setNotifOpen(false); }}>
                {t('common.viewAll')} →
              </div>
            </div>
          )}
        </div>
        <div className="relative" ref={menuRef}>
          <button onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-offset transition-colors">
            <div className="avatar-sm !w-8 !h-8 !text-sm">{initials}</div>
            <div className="hidden sm:block text-left">
              <p className="text-sm font-medium leading-tight capitalize c-text">{displayName}</p>
              <p className="text-xs leading-tight c-text-muted">{user?.email || ''}</p>
            </div>
            <SvcIcon name="chevron-down" className="w-4 h-4 c-text-faint" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 mt-1 w-56 bg-surface border border-border rounded-lg shadow-lg py-1 z-50" style={{boxShadow:'var(--shadow-lg)'}}>
              <div className="px-4 py-2 border-b border-divider">
                <p className="text-sm font-medium capitalize c-text">{displayName}</p>
                <p className="text-xs c-text-muted">{user?.email}</p>
              </div>
              <button onClick={() => { logout(); window.location.href = '/sign-in'; }}
                className="w-full flex items-center gap-2 px-4 py-2 text-sm transition-colors"
                style={{color:'var(--color-notification)'}}>
                <SvcIcon name="log-out" className="w-4 h-4" /> {t('nav.signOut')}
              </button>
            </div>
          )}
        </div>
      </div>
      </header>
      <MobileSearchSheet open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}

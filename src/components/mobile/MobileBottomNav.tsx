import { useState, useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../components/SvcIcon'
import { useAuth } from '../../lib/AuthContext';
import { apiClient } from '../../lib/api';
import { useSecretarySettings } from '../../hooks/useSecretarySettings';

/**
 * Penguin CRM — Mobile Bottom Navigation v3 (AI 管家秘書 theme) — v6.70
 * Mobile view 吸收 sidebar + top bar：
 *   工作區 tab ← sidebar 工作區選項
 *   紀錄   tab ← sidebar 記錄選項
 *   設定   tab ← sidebar 組織選項 + top bar（黑白轉 / 個人頁面 / 通知）
 * ≤768px 時 sidebar + top bar 完全 hidden（CSS），bottom nav 係唯一導航。
 */

export interface Props {
  onOpenAiSearch: () => void;
  /** 2026-09-12：任何 nav 操作前先關掉其他 overlay（AI panel 等），
      否則 overlay 蓋住 nav 會令按鍵撳唔到（用戶 #1）。 */
  onNavInteract?: () => void;
  onScanCard: () => void;
  onQuickAdd: (recordType: string) => void;
}

const THEME_STORAGE = 'nexus-theme';

export default function MobileBottomNav({ onOpenAiSearch, onScanCard, onQuickAdd, onNavInteract }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const addTiles = ADD_TILES_BASE.map(tile => ({ ...tile, label: t(tile.labelKey, { defaultValue: tile.label }) }));
  const [sheet, setSheet] = useState<'workspace' | 'add' | 'settings' | null>(null);
  const [dark, setDark] = useState(() => document.documentElement.getAttribute('data-theme') === 'dark');
  const [unreadCount, setUnreadCount] = useState(0);
  // SPEC ai-butler-v2 動態版: 新通知到達 → 搖鈴一吓（~1.4s — 用戶: 搖一下夠醒）→ 停喺靜態通知 pose
  const [ringing, setRinging] = useState(false);
  const prevUnread = useRef(0);
  useEffect(() => {
    if (unreadCount > 0 && prevUnread.current === 0) {
      // 0 → N：新通知到達 — 搖一吓 + 通聲（WORKFLOW-2026-09: 重複名片 HIGH 通知等都要有聲）
      setRinging(true);
      const t = setTimeout(() => setRinging(false), 1400);
      try {
        const AC = window.AudioContext || (window as any).webkitAudioContext;
        if (AC) {
          const ctx = new AC();
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain); gain.connect(ctx.destination);
          osc.type = 'sine'; osc.frequency.value = 880;
          gain.gain.setValueAtTime(0.1, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
          osc.start(); osc.stop(ctx.currentTime + 0.65);
          ctx.resume?.().catch?.(() => {});
        }
      } catch { /* audio blocked — silent ok */ }
      try { navigator.vibrate?.(250); } catch { /* no vibrate */ }
      return () => clearTimeout(t);
    }
    prevUnread.current = unreadCount;
  }, [unreadCount]);

  /* ── v6.94: AI 管家設定 4 開關（backend ai_secretary_settings）── */
  const secretary = useSecretarySettings();
  const secSettings = secretary.settings;
  const BRIEFING_MODULES = ['weather', 'today_tasks', 'meetings'];
  const briefingOn = !!secSettings?.modules && BRIEFING_MODULES.some(m => (secSettings.modules as Record<string, unknown>)[m]);
  const toggleBriefing = async () => {
    const cur: Record<string, unknown> = { ...(secSettings?.modules || {}) };
    if (briefingOn) {
      const next: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(cur)) if (!BRIEFING_MODULES.includes(k)) next[k] = v;
      await secretary.update({ modules: next as any });
    } else {
      const next: Record<string, unknown> = { ...cur };
      for (const m of BRIEFING_MODULES) if (!next[m]) next[m] = {};
      await secretary.update({ modules: next as any });
    }
  };
  const toggleCalAwareness = async () => { await secretary.update({ calendar_awareness: !secSettings?.calendar_awareness }); };
  const toggleWeekendMute = async () => { await secretary.update({ weekend_mute: !secSettings?.weekend_mute }); };
  const toggleStrictSilence = async () => { await secretary.update({ strict_silence: !secSettings?.strict_silence }); };

  /* ── Sidebar mirror（同 SidebarV2 一致）── */
  /* v6.93: project-centric — Deals 完全移除（設計文件：Deal/Pipeline 唔再顯示） */
  /* v7.24: icons 換 PenguinCRM SVG kit（SvcIcon name） */
  /* 2026-09-10 Terrence: Dashboard 抽出做「首頁」bottom-nav tab；工作區 sheet
     保留 CRM 工作項，並吸收原本「紀錄」tab 嘅聯繫記錄 + 名片庫（紀錄 tab 已移除）。 */
  const workspaceItems = [
    { to: '/contacts',   label: t('nav.contacts', { defaultValue: '聯絡人' }), icon: 'contacts' },
    { to: '/calendar',   label: t('nav.calendar', { defaultValue: '日曆' }), icon: 'calendar' },
    { to: '/companies',  label: t('nav.companies', { defaultValue: '公司' }), icon: 'companies' },
    { to: '/projects',   label: t('nav.projects', { defaultValue: '項目' }), icon: 'projects' },
    { to: '/tasks',      label: t('nav.tasks', { defaultValue: '任務' }), icon: 'tasks' },
  ];
  const recordItems = [
    { to: '/touchpoints', label: t('nav.touchpoints', { defaultValue: '聯繫記錄' }), icon: 'touchpoints' },
    { to: '/namecards',   label: t('nav.namecards', { defaultValue: '名片庫' }), icon: 'name-cards' },
    // Notes v2 (T1.3) — 桌面側欄之外，bottom nav 工作區 sheet 嘅「紀錄」組都要有入口
    { to: '/notes',       label: t('nav.notes', { defaultValue: '筆記' }), icon: 'book-open' },
    // /reports removed 2026-09-09（Coming Soon）— nice-to-have backlog
  ];
  const settingsItems = [
    // /team removed 2026-09-09（Coming Soon）— nice-to-have backlog
    { to: '/ai-apps',      label: t('nav.aiApps', { defaultValue: 'AI Apps' }), icon: 'ai-apps' },
    // /marketplace removed 2026-09-09（UI 半成品）— nice-to-have backlog
    { to: '/settings',     label: t('nav.settings', { defaultValue: '設定' }), icon: 'settings' },
  ];

  /* ── 通知 badge（中間管家 logo — SPEC ai-butler-v2 T2）── */
  const fetchNotifs = () => {
    apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count')
      .then(d => setUnreadCount(d?.unread_count || 0)).catch(() => {});
  };
  useEffect(() => { fetchNotifs(); }, []);
  useEffect(() => { if (sheet === 'settings') fetchNotifs(); }, [sheet]);
  // SPEC ai-butler-v2 T2: 60s poll — 中間管家 logo badge 自動更新（唔使開 settings 先見）
  useEffect(() => {
    const iv = setInterval(fetchNotifs, 60000);
    return () => clearInterval(iv);
  }, []);
  // 2026-09-07 fix: AiSearchPanel 睇完通知（mark read）→ dispatch nexus:notif-read → 即時 refresh badge（唔使等 60s poll / reload）
  useEffect(() => {
    window.addEventListener('nexus:notif-read', fetchNotifs);
    return () => window.removeEventListener('nexus:notif-read', fetchNotifs);
  }, []);

  const path = location.pathname;
  const activeTab: 'home' | 'workspace' | 'records' | 'settings' | 'none' =
    path.startsWith('/settings') || path.startsWith('/team') || path.startsWith('/ai-apps') || path.startsWith('/marketplace') || path.startsWith('/notifications') ? 'settings'
    : path.startsWith('/dashboard') ? 'home'
    : ['/touchpoints', '/namecards', '/notes'].some(p => path.startsWith(p)) ? 'records'
    : ['/contacts', '/calendar', '/companies', '/projects', '/tasks'].some(p => path.startsWith(p)) ? 'workspace'
    : 'none';

  const toggleTheme = () => {
    const el = document.documentElement;
    const next = el.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    el.setAttribute('data-theme', next);
    setDark(next === 'dark');
    try { localStorage.setItem(THEME_STORAGE, next); } catch { /* ignore */ }
  };

  const go = (route: string) => { onNavInteract?.(); setSheet(null); navigate(route); };
  const isActive = (to: string) => path.startsWith(to);

  return (
    <>
      <nav className="mnav-bar" role="navigation" aria-label="Primary">
        {/* 2026-09-10 Terrence: 首頁 = Dashboard（原本工作區位置）；工作區 = sheet
            （原本紀錄位置，已吸收 touchpoints + namecards） */}
        <button type="button" className={`mnav-item ${activeTab === 'home' ? 'active' : ''}`} onClick={() => go('/dashboard')}>
          <SvcIcon name="dashboard" /><span>{t('nav.home', { defaultValue: '首頁' })}</span>
        </button>
        <button type="button" className={`mnav-item ${activeTab === 'workspace' || activeTab === 'records' ? 'active' : ''}`} onClick={() => { onNavInteract?.(); setSheet('workspace') }}>
          <SvcIcon name="workspace" /><span>{t('nav.workspace', { defaultValue: '工作區' })}</span>
        </button>
        <div className="mnav-center-wrap">
          <div className="mnav-center-btn-wrap">
            <button type="button" className={`mnav-center-btn ${ringing ? 'ringing' : unreadCount > 0 ? 'has-notif' : ''}`} onClick={onOpenAiSearch} aria-label="Penguin AI">
              {/* SPEC ai-butler-v2 動態版: 新通知到達 → item 1（企鵝揸鈴 pose）彈出 + 搖鈴一次
                  （CSS ringing — 一次性）；之後停喺 item 1 靜態 pose（未讀期間）；已讀 → 靜態 logo */}
              {unreadCount > 0 ? (
                <img src="/assets/butler/notify_pose.png" alt="Penguin AI 有通知" className="mnav-center-logo notif" />
              ) : (
                <img src="/assets/butler/butler_idle.png" alt="Penguin AI" className="mnav-center-logo" />
              )}
            </button>
            {/* SPEC ai-butler-v2 T2: 管家 logo 右上角通知 badge（紅點+數字，9+ cap）— 保留 */}
            {unreadCount > 0 && (
              <span className="mnav-center-badge" aria-label={`${unreadCount} 則未讀通知`}>
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </div>
          <span>{t('mobile.aiSearch', { defaultValue: '企鵝管家' })}</span>
        </div>
        <button type="button" className={`mnav-item ${sheet === 'add' ? 'active' : ''}`} onClick={() => { onNavInteract?.(); setSheet('add') }}>
          {/* Terrence: add icon 跟 workspace icon 風格（container icon — circle plus，
              唔係淨 plus 幼線）*/}
          <SvcIcon name="plus-circle" /><span>{t('common.add', { defaultValue: '新增' })}</span>
        </button>
        <button type="button" className={`mnav-item ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => { onNavInteract?.(); setSheet('settings') }}>
          <SvcIcon name="settings" />
          <span>{t('nav.settings', { defaultValue: '設定' })}</span>
          {/* SPEC ai-butler-v2: 通知 badge 集中中間管家 logo — settings tab 唔再顯示 */}
        </button>
      </nav>

      {/* ── 工作區 sheet（= sidebar 工作區選項 + 原紀錄 tab 內容）── */}
      {sheet === 'workspace' && (
        <Sheet title={t('nav.workspace', { defaultValue: '工作區' })} onClose={() => setSheet(null)}>
          <div className="mnav-section-label">{t('nav.workspace', { defaultValue: 'Workspace' })}</div>
          {workspaceItems.map(item => (
            <button key={item.to} type="button" className={`mnav-row ${isActive(item.to) ? 'active' : ''}`} onClick={() => go(item.to)}>
              <span className="mnav-row-icon mnav-row-icon-neutral"><SvcIcon name={item.icon} size={18} /></span>
              <span className="txt"><strong>{item.label}</strong></span>
              <SvcIcon name="chevron-right" className="mnav-row-chev" />
            </button>
          ))}
          {/* 原「紀錄」tab（2026-09-10 移除）→ 併入工作區 */}
          <div className="mnav-section-label" style={{ marginTop: 14 }}>{t('nav.records', { defaultValue: '紀錄' })}</div>
          {recordItems.map(item => (
            <button key={item.to} type="button" className={`mnav-row ${isActive(item.to) ? 'active' : ''}`} onClick={() => go(item.to)}>
              <span className="mnav-row-icon mnav-row-icon-neutral"><SvcIcon name={item.icon} size={18} /></span>
              <span className="txt"><strong>{item.label}</strong></span>
              <SvcIcon name="chevron-right" className="mnav-row-chev" />
            </button>
          ))}
        </Sheet>
      )}

      {/* ── 新增 sheet ── */}
      {sheet === 'add' && (
        <Sheet title={t('mobile.addNew', { defaultValue: 'Add New' })} onClose={() => setSheet(null)}>
          <button type="button" className="mnav-scan-banner" onClick={() => { setSheet(null); onScanCard(); }}>
            <span className="mnav-scan-banner-icon"><SvcIcon name="scan-line" /></span>
            <span className="txt"><strong>{t('mobile.autoCardImport', { defaultValue: '拍卡片自動入庫' })}</strong><span>{t('mobile.scanCardDesc', { defaultValue: '用鏡頭掃描名片，AI 自動識別並存為聯絡人' })}</span></span>
            <SvcIcon name="chevron-right" className="chev" />
          </button>
          <div className="mnav-section-label">{t('mobile.quickCreate', { defaultValue: 'Quick Create' })}</div>
          <div className="mnav-add-grid">
            {addTiles.map(tile => (
              <button key={tile.id} type="button" className="mnav-add-tile" onClick={() => {
                /* 2026-09-13（用戶指示）：新增筆記 tile —— 筆記冇 quick-add modal，
                   直接入 Notes workspace 開「建立筆記」sheet（?new=1，見 NotesWorkspacePage） */
                if (tile.id === 'note') { go('/notes/n/all?new=1'); return }
                setSheet(null); onQuickAdd(tile.id)
              }}>
                <span className="mnav-add-tile-icon"><SvcIcon name={tile.icon} size={18} /></span>
                <span>{tile.label}</span>
              </button>
            ))}
          </div>
        </Sheet>
      )}

      {/* ── 設定 sheet（= sidebar 組織 + top bar：黑白轉/個人/通知）── */}
      {sheet === 'settings' && (
        <Sheet title={t('nav.settings', { defaultValue: '設定' })} onClose={() => setSheet(null)} tall>
          {/* 個人頁面（top bar user menu → profile） */}
          <button type="button" className="mnav-org-profile" onClick={() => go('/settings')} style={{ width: '100%', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}>
            <span className="mnav-org-avatar">{(user?.displayName || user?.email || 'U')[0].toUpperCase()}</span>
            <span style={{ flex: 1 }}>
              <strong>{user?.displayName || user?.email || ''}</strong>
              <span style={{ display: 'block' }}>{user?.email || ''}</span>
            </span>
            <SvcIcon name="chevron-right" className="mnav-row-chev" />
          </button>

          {/* SPEC ai-butler-v2: 通知 section 移除（bell + preview）— 通知入口集中
              中間管家 logo（badge + click → panel 通知 tab） */}

          {/* 組織（sidebar organization） */}
          <div className="mnav-section-label">{t('nav.organization', { defaultValue: 'Organization' })}</div>
          {settingsItems.map(item => (
            <button key={item.to} type="button" className="mnav-org-row" onClick={() => go(item.to)}>
              <SvcIcon name={item.icon} size={18} /><span>{item.label}</span><SvcIcon name="chevron-right" className="chev" />
            </button>
          ))}

          {/* v6.94: AI 管家設定 4 開關 */}
          <div className="mnav-section-label">{t('mobile.aiButler', { defaultValue: 'AI 管家' })}</div>
          <button type="button" className="mnav-org-row" onClick={toggleBriefing}>
            <SvcIcon name="penguin-ai" size={22} /><span>{t('mobile.dailyBriefing', { defaultValue: '每日 Briefing' })}</span>
            <span className={`mnav-switch ${briefingOn ? 'on' : ''}`} onClick={e => { e.stopPropagation(); toggleBriefing(); }} />
          </button>
          <button type="button" className="mnav-org-row" onClick={toggleCalAwareness}>
            <SvcIcon name="calendar" /><span>{t('mobile.calendarProactive', { defaultValue: '行事曆主動提問' })}</span>
            <span className={`mnav-switch ${secSettings?.calendar_awareness ? 'on' : ''}`} onClick={e => { e.stopPropagation(); toggleCalAwareness(); }} />
          </button>
          <button type="button" className="mnav-org-row" onClick={toggleWeekendMute}>
            <SvcIcon name="moon" /><span>{t('mobile.weekendSilent', { defaultValue: '週末靜音' })}</span>
            <span className={`mnav-switch ${secSettings?.weekend_mute ? 'on' : ''}`} onClick={e => { e.stopPropagation(); toggleWeekendMute(); }} />
          </button>
          <button type="button" className="mnav-org-row" onClick={toggleStrictSilence}>
            <SvcIcon name="bell" /><span>{t('mobile.strictSilent', { defaultValue: '嚴格靜音' })}</span>
            <span className={`mnav-switch ${secSettings?.strict_silence ? 'on' : ''}`} onClick={e => { e.stopPropagation(); toggleStrictSilence(); }} />
          </button>

          {/* 外觀（top bar 黑白轉） */}
          <div className="mnav-section-label">{t('settings.appearance', { defaultValue: '外觀' })}</div>
          <button type="button" className="mnav-org-row" onClick={toggleTheme}>
            <SvcIcon name="moon" /><span>{t('mobile.darkMode', { defaultValue: 'Dark Mode' })}</span>
            <span className={`mnav-switch ${dark ? 'on' : ''}`} onClick={e => e.stopPropagation()} />
          </button>

          {/* 帳戶 */}
          <div className="mnav-section-label">{t('settings.account', { defaultValue: '帳戶' })}</div>
          <button type="button" className="mnav-org-row" onClick={() => { setSheet(null); logout(); }}>
            <SvcIcon name="log-out" /><span style={{ color: 'var(--color-error)' }}>{t('nav.signOut', { defaultValue: '登出' })}</span>
          </button>
        </Sheet>
      )}
    </>
  );
}

const ADD_TILES_BASE = [
  { id: 'project', labelKey: 'mobile.addTiles.project', label: 'Project', icon: 'projects', color: 'var(--color-primary)' },
  { id: 'contact', labelKey: 'mobile.addTiles.contact', label: 'Contact', icon: 'contacts', color: 'var(--color-blue)' },
  { id: 'company', labelKey: 'mobile.addTiles.company', label: 'Company', icon: 'companies', color: 'var(--color-warning)' },
  { id: 'task',    labelKey: 'mobile.addTiles.task',    label: 'Task',    icon: 'tasks',    color: 'var(--color-purple)' },
  // 2026-09-09: Event → Touchpoint（互動記錄 add new — calendar event 唔係 CRM 互動）；
  { id: 'touchpoint', labelKey: 'mobile.addTiles.touchpoint', label: 'Touchpoint', icon: 'touchpoints', color: 'var(--color-success)' },
  // 2026-09-13（用戶指示）：Note tile 加返 —— 之前因 G08 less is more 移除，
  // 而家有真嘅「建立筆記」流程（?new=1），唔再係空 tile。
  { id: 'note', labelKey: 'mobile.addTiles.note', label: 'Note', icon: 'book-open', color: 'var(--color-primary)' },
];

function Sheet({ title, onClose, children, tall = false }: { title: string; onClose: () => void; children: ReactNode; tall?: boolean }) {
  const [closing, setClosing] = useState(false);

  /* v6.82: lock background scroll while sheet is open (same pattern as
     BottomSheet/ActionPreviewModal — prevents touch scrolling the page
     behind the sheet) */
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const handleClose = () => {
    if (closing) return;
    setClosing(true);
    setTimeout(onClose, 200);
  };

  return createPortal(
    <div className={`mnav-sheet-overlay ${closing ? 'closing' : ''}`} onClick={handleClose}>
      <div className={`mnav-sheet ${tall ? 'tall' : ''} ${closing ? 'closing' : ''}`} onClick={e => e.stopPropagation()}>
        <div className="mnav-sheet-handle" />
        <div className="mnav-sheet-head">
          <h3>{title}</h3>
          <button type="button" className="mnav-sheet-close" onClick={handleClose} aria-label="Close"><SvcIcon name="x" /></button>
        </div>
        <div className="mnav-sheet-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}

import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'

/* ═══════════════════════════════════════════════════════════
   SidebarV2 — Collapsible navigation rail (PenguinCRM brand icons v7.08).
   Clicking the logo toggles collapse on desktop (persisted).
   On mobile it's rendered as a slide-in drawer by LayoutV2.
   Includes: Team (nav.team) module explicitly, per audit.
   ═══════════════════════════════════════════════════════════ */

/* 2026-09-14：移除 `module` 欄位 —— 桌面選單原本喺 label 後面多印一個 raw module key
   （只有 Notes 有），變成「Notes notes」。G08 鐵律 Less is more：唔加多餘 UI。 */
interface NavItem { to: string; label: string; icon: string }
interface NavSection { label: string; items: NavItem[] }

export default function SidebarV2({ collapsed, onToggleCollapse }: { collapsed: boolean; onToggleCollapse: () => void }) {
  const { t } = useTranslation()

  const sections: NavSection[] = [
    { label: t('nav.workspace', { defaultValue: '工作區' }), items: [
      { to: '/dashboard', label: t('nav.dashboard', { defaultValue: 'Dashboard' }), icon: 'dashboard' },
      { to: '/contacts', label: t('nav.contacts', { defaultValue: '聯絡人' }), icon: 'contacts' },
      { to: '/calendar', label: t('nav.calendar', { defaultValue: '日曆' }), icon: 'calendar' },
      { to: '/companies', label: t('nav.companies', { defaultValue: '公司' }), icon: 'companies' },
      { to: '/projects', label: t('nav.projects', { defaultValue: '項目' }), icon: 'projects' },
      { to: '/tasks', label: t('nav.tasks', { defaultValue: '任務' }), icon: 'tasks' },
      // NOTE: Renewal Radar 刻意收埋（2026-09-12，Terrence 指示）—— 將來併入 Insurance Agent module。
      // 代碼仍然存在（src/pages/RenewalsPage.tsx + App.tsx route + backend /api/v1/crm/renewals），
      // 重新開啟 = 加返下面一行。詳見 docs/renewal-radar.md
      // { to: '/renewals', label: t('nav.renewals', { defaultValue: '續約雷達' }), icon: 'alarm-clock' },
    ]},
    { label: t('nav.records', { defaultValue: '記錄' }), items: [
      { to: '/touchpoints', label: t('nav.touchpoints', { defaultValue: '聯繫記錄' }), icon: 'touchpoints' },
      { to: '/notes', label: t('nav.notes', { defaultValue: '筆記' }), icon: 'book-open' },
      { to: '/namecards', label: t('nav.namecards', { defaultValue: '名片庫' }), icon: 'name-cards' },
      // /reports removed 2026-09-09（Coming Soon）— nice-to-have backlog
    ]},
    { label: t('nav.organization', { defaultValue: '組織' }), items: [
      // /team removed 2026-09-09（Coming Soon）— nice-to-have backlog
      { to: '/ai-apps', label: t('nav.aiApps', { defaultValue: 'AI Apps' }), icon: 'ai-apps' },
      { to: '/notifications', label: t('nav.notifications', { defaultValue: '通知' }), icon: 'notifications' },
      // /marketplace removed 2026-09-09（UI 半成品）— nice-to-have backlog
      { to: '/settings', label: t('nav.settings', { defaultValue: '設定' }), icon: 'settings' },
    ]},
  ]

  return (
    <aside className={`sbv2-sidebar ${collapsed ? 'collapsed' : ''}`}>
      <button className="sbv2-logo-btn" onClick={onToggleCollapse} title={collapsed ? t('sidebar.expand', { defaultValue: '展開側邊欄' }) : t('sidebar.collapse', { defaultValue: '收合側邊欄' })}>
        <img src="/assets/logo/logo_square.png" alt="PenguinCRM" className="sbv2-logo-icon" />
        {!collapsed && <span className="sbv2-logo-text">Penguin CRM</span>}
        {!collapsed && <SvcIcon name="chevron-left" size={15} className="sbv2-collapse-caret" />}
      </button>

      <nav className="sbv2-nav">
        {sections.map((section) => (
          <div key={section.label}>
            {!collapsed && <div className="sbv2-section-label">{section.label}</div>}
            {section.items.map((item) => {
              return (
                <NavLink key={item.to} to={item.to} data-tooltip={item.label}
                  className={({ isActive }) => `sbv2-nav-item ${isActive ? 'active' : ''}`}>
                  <SvcIcon name={item.icon} size={18} />
                  {!collapsed && <span className="sbv2-nav-label">{item.label}</span>}
                </NavLink>
              )
            })}
          </div>
        ))}
      </nav>
    </aside>
  )
}

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';
import { Activity, Building2, Calendar, CheckSquare, FolderKanban, LayoutDashboard, ScanLine, Sparkles, Users } from 'lucide-react'
import { apiClient } from '../lib/api';

export interface ModuleSetting {
  module_key: string;
  enabled: boolean;
}

const closeMobileMenu = () => {
  const shell = document.getElementById('appShell');
  if (shell) shell.classList.remove('mobile-open');
  window.dispatchEvent(new CustomEvent('close-mobile-menu'));
};

export default function Sidebar() {
  const { t } = useTranslation();

  const workspaceItems = [
    { to: '/dashboard', label: t('nav.dashboard'), icon: LayoutDashboard },
    { to: '/contacts', label: t('nav.contacts'), icon: Users },
    { to: '/calendar', label: t('nav.calendar'), icon: Calendar },
    { to: '/companies', label: t('nav.companies'), icon: Building2 },
    { to: '/projects', label: t('nav.projects'), icon: FolderKanban, module: 'projects' },
    { to: '/deals', label: t('nav.deals'), icon: Activity, module: 'sales' },
    { to: '/tasks', label: t('nav.tasks'), icon: CheckSquare },
  ];

  const secondaryItems = [
    { to: '/touchpoints', label: t('nav.touchpoints'), icon: Activity },
    { to: '/namecards', label: t('nav.nameCards'), icon: ScanLine },
    // /reports removed 2026-09-09 (Coming Soon) — see docs/nice-to-have-backlog-2026-09-09.md
  ];

  const orgItems = [
    // /team removed 2026-09-09 (Coming Soon) — see docs/nice-to-have-backlog-2026-09-09.md
    { to: '/ai-apps', label: t('nav.aiApps'), icon: Sparkles },
  ];

  const [modules, setModules] = useState<Record<string, boolean>>({});

  const fetchModules = useCallback(async () => {
    try {
      const list: ModuleSetting[] = await apiClient.get('/api/v1/crm/module-settings');
      const map: Record<string, boolean> = {};
      (list || []).forEach(m => { map[m.module_key] = m.enabled; });
      setModules(map);
    } catch {}
  }, []);

  useEffect(() => {
    fetchModules();
    const handler = () => fetchModules();
    window.addEventListener('modules-changed', handler);
    return () => window.removeEventListener('modules-changed', handler);
  }, [fetchModules]);

  // Default to visible when module settings not loaded yet
  const hasSettings = Object.keys(modules).length > 0
  const isVisible = (item: typeof workspaceItems[0]) => {
    if (!item.module) return true;
    if (!hasSettings) return true;
    // Default to visible when no explicit setting exists (mirrors enabled-modules.ts)
    return modules[item.module] !== false;
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <img src="/assets/logo/logo_square.png" alt="PenguinCRM" className="sbv2-logo-icon" />
        <span>{t('app.name')}</span>
      </div>
      <nav className="sidebar-nav">
        <p className="nav-section-label">{t('nav.workspace')}</p>
        {workspaceItems.map(item => isVisible(item) && (
          <NavLink key={item.to} to={item.to} onClick={closeMobileMenu} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            {item.icon && <item.icon size={18} />}
            <span>{item.label}</span>
          </NavLink>
        ))}
        <p className="nav-section-label mt-space-4">{t('nav.records')}</p>
        {secondaryItems.map(item => (
          <NavLink key={item.to} to={item.to} onClick={closeMobileMenu} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <item.icon />
            <span>{item.label}</span>
          </NavLink>
        ))}
        <p className="nav-section-label mt-space-4">{t('nav.organization')}</p>
        {orgItems.map(item => (
          <NavLink key={item.to} to={item.to} onClick={closeMobileMenu} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <item.icon />
            <span>{item.label}</span>
          </NavLink>
        ))}
        <NavLink to="/notifications" onClick={closeMobileMenu} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <SvcIcon name="bell" />
          <span>{t('nav.notifications')}</span>
        </NavLink>
        <NavLink to="/settings" onClick={closeMobileMenu} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          style={{ marginTop: 'var(--space-4)' }}>
          <SvcIcon name="settings" />
          <span>{t('nav.settings')}</span>
        </NavLink>
      </nav>
    </aside>
  );
}

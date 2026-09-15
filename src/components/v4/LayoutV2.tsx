import { useState, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import SidebarV2 from './SidebarV2'
import HeaderV2 from './HeaderV2'
import ChatboxPanel from '../ChatboxPanel'
import MobileNavHost from '../mobile/MobileNavHost'

const COLLAPSE_KEY = 'nexus-sidebar-collapsed'

/* LayoutV2 — wires SidebarV2 + HeaderV2 together, manages
   collapse state (persisted) and mobile drawer/scrim. */

export default function LayoutV2() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')
  const location = useLocation()

  // Close the mobile drawer on every route change
  useEffect(() => {
    document.getElementById('appShell')?.classList.remove('mobile-open')
  }, [location.pathname])

  const toggleCollapse = () => {
    setCollapsed(v => {
      const next = !v
      localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0')
      return next
    })
  }

  useEffect(() => {
    const closeOnResize = () => { if (window.innerWidth >= 1024) document.getElementById('appShell')?.classList.remove('mobile-open') }
    window.addEventListener('resize', closeOnResize)
    return () => window.removeEventListener('resize', closeOnResize)
  }, [])

  return (
    <div id="appShell" className={`nx2-app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <SidebarV2 collapsed={collapsed} onToggleCollapse={toggleCollapse} />
      <div className="nx2-mobile-scrim" onClick={() => document.getElementById('appShell')?.classList.remove('mobile-open')} />
      <div className="nx2-main">
        <HeaderV2 />
        <main className="nx2-content">
          <Outlet />
        </main>
      </div>
      <ChatboxPanel />
      <MobileNavHost />
    </div>
  )
}

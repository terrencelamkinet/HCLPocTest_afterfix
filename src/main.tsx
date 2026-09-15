import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from './lib/AuthContext'
import { ToastProvider } from './components/v4/useToast'
import './index.css'
import './styles/penguincrm-tokens.css'
import './styles/dashboard.css'
import './styles/todo.css'
import './styles/design4-overrides.css'
import './styles/design4-v2-patch.css'
import './styles/nexus-modal-tokens.css'
import './styles/nexus-detail-v2.css'
import './styles/detail-v3.css'
import './styles/nexus-namecards-v2.css'
import './styles/nexus-tag-management.css'
import './styles/nexus-module-shell.css'
import './styles/nexus-topbar-dashboard-v2.css'
import './styles/nexus-crm-editor-v2.css'
import './styles/notes-workspace.css'
import './styles/notes-mobile-layers.css'
import './styles/ai-apps-upgrade.css'
import './styles/mobile-nav-v3.css'
import './i18n/config'; // i18n init — must be before App
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </AuthProvider>
  </StrictMode>,
)

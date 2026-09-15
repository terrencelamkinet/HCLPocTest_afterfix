import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { preloadOpenCv } from './lib/opencvLoader';
import LayoutV2 from './components/v4/LayoutV2';
import AuthGuard from './components/AuthGuard';
import LoginPage from './pages/LoginPage';
import DashboardV2 from './components/v4/DashboardV2';
import ContactsPage from './modules/contacts/ContactsPage';
import ContactDetailPage from './modules/contacts/ContactDetailPage';
import ContactCalendarPage from './modules/contacts/ContactCalendarPage';
import CompaniesPage from './modules/companies/CompaniesPage';
import CompaniesDetailPage from './modules/companies/CompaniesDetailPage';
import ProjectsPage from './modules/projects/ProjectsPage';
import NotesWorkspacePage from './pages/NotesWorkspacePage';
import ProjectsDetailPage from './modules/projects/ProjectsDetailPage';
import TasksPage from './modules/tasks/TasksPage';
// Renewal Radar 頁面刻意唔 import（2026-09-12 隱藏，將來併入 Insurance Agent module）
// import RenewalsPage from './pages/RenewalsPage';
import TaskDetailPage from './modules/tasks/TaskDetailPage';
import TouchpointsPage from './modules/touchpoints/TouchpointsPage';
import TouchpointDetailPage from './modules/touchpoints/TouchpointDetailPage';
import MarketplacePage from './pages/MarketplacePage';
import IntegrationDetailPage from './pages/IntegrationDetailPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import NameCardModuleRouter from './namecards/NameCardModuleRouter';
import SvcIconsPage from './pages/SvcIconsPage';
import SettingsPage from './pages/SettingsPage';
import AIAppsPage from './pages/AIAppsPage';
import NotificationsPage from './pages/NotificationsPage';
import SearchPage from './pages/SearchPage';
import AiPage from './pages/AiPage';
import DeepLinkEventPage from './pages/DeepLinkEventPage';
import ProjectGate from './components/ProjectGate';
import { useTranslation } from 'react-i18next';

function App() {
  const { t } = useTranslation()
  /* 名片掃描 OpenCV 引擎（13MB）背景預載 — idle 時下載 + wasm init，
     用戶撳「拍卡片」時通常已經 ready（2026-09-10 Terrence: 開掃描等 10s 太麻煩） */
  useEffect(() => { preloadOpenCv() }, [])
  return (
    <BrowserRouter>
      <ScrollReflow />
      <Routes>
        {/* Public routes — no auth needed */}
        <Route path="/sign-in" element={<LoginPage />} />
        {/* /login 統一 serve React LoginPage（2026-09-07 cutover — 舊 public/login/index.html 已刪 — 唔再雙重 maintain；hash #sa= 保留 — LoginPage 自處理） */}
        <Route path="/login" element={<LoginPage />} />

        {/* OAuth callback — standalone, no layout (runs in popup) */}
        <Route path="/marketplace/oauth/callback" element={<OAuthCallbackPage />} />

        {/* Protected routes — wrapped in AuthGuard */}
        <Route
          path="/"
          element={
            <AuthGuard>
              <LayoutV2 />
            </AuthGuard>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardV2 />} />
          {/* IM push deep links — WhatsApp briefing links resolve to real pages */}
          <Route path="l/dashboard" element={<Navigate to="/dashboard" replace />} />
          <Route path="l/t/:id" element={<DeepLinkTask />} />
          <Route path="l/m/:id" element={<DeepLinkEventPage mode="prep" />} />
          <Route path="l/note/:id" element={<DeepLinkEventPage mode="note" />} />
          <Route path="contacts" element={<ContactsPage />} />
          <Route path="calendar" element={<ContactCalendarPage />} />
          <Route path="contacts/:id" element={<ContactDetailPage />} />
          <Route path="companies" element={<CompaniesPage />} />
          <Route path="companies/:id" element={<CompaniesDetailPage />} />
          <Route path="projects" element={<ProjectGate><ProjectsPage /></ProjectGate>} />
          <Route path="projects/:id" element={<ProjectGate><ProjectsDetailPage /></ProjectGate>} />
          <Route path="shipping" element={
            <div className="p-8">
              <h1 className="text-2xl font-bold c-text">Shipping</h1>
              <p className="c-text-muted">Shipping module coming soon</p>
            </div>
          } />
          <Route path="touchpoints" element={<TouchpointsPage />} />
          <Route path="touchpoints/:id" element={<TouchpointDetailPage />} />
          <Route path="tasks" element={<TasksPage />} />
          {/* Renewal Radar 刻意收埋（2026-09-12，Terrence 指示）—— 將來併入 Insurance Agent module */}
          {/* <Route path="renewals" element={<RenewalsPage />} /> */}
          <Route path="tasks/:id" element={<TaskDetailPage />} />
          <Route path="namecards/*" element={<NameCardModuleRouter />} />
          <Route path="newicon" element={<SvcIconsPage />} />
          <Route path="reports" element={
            <div className="p-8">
              <h1 className="text-2xl font-bold text-slate-900">{t('pages.reports.title')}</h1>
              <p className="text-slate-500 mt-2">{t('common.comingSoon')}</p>
            </div>
          } />
          <Route path="marketplace" element={<MarketplacePage />} />
          <Route path="marketplace/:id" element={<IntegrationDetailPage />} />
          <Route path="team" element={
            <div className="p-8">
              <h1 className="text-2xl font-bold c-text">{t('pages.team.title')}</h1>
              <p className="c-text-muted">{t('common.comingSoon')}</p>
            </div>
          } />
          <Route path="ai-apps" element={<AIAppsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          {/* 2026-09-14（用戶指示）：Notes index page（KPI + Notebook 卡）用途不大 → 移除，
              /notes 直接入 All Notes。新增 Notebook 已喺 workspace rail 做（NotesWorkspacePage）。 */}
          <Route path="notes" element={<Navigate to="/notes/n/all" replace />} />
          {/* Notes v2 T1.3/T1.4 — 3-pane workspace. notebookId = all | uncat | <uuid> */}
          <Route path="notes/n/:notebookId" element={<NotesWorkspacePage />} />
          {/* 2026-09-13：search／command palette／AI 結果嘅 note url 係 /notes/<id>
              （backend /crm/search 同新 search_notes tool 都出呢個 shape）→ 加 deep link
               route，入 workspace 後自動揀嗰篇（見 NotesWorkspacePage 嘅 deepNoteId effect） */}
          <Route path="notes/:noteId" element={<NotesWorkspacePage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="ai" element={<AiPage />} />
        </Route>

        {/* Catch-all → redirect to dashboard */}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

/** Deep link /l/t/{id} → real task detail page (from WhatsApp briefing) */
function DeepLinkTask() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/tasks/${id}`} replace />;
}

/**
 * Global route-change reflow (iOS Safari URL-bar fix, Layer 3).
 * Forces the browser to re-measure layout on every navigation so the
 * collapsed/expanded URL bar never leaves a stale "dropped a layer" gap.
 */
function ScrollReflow() {
  const { pathname } = useLocation();
  useEffect(() => {
    requestAnimationFrame(() => window.scrollTo(0, window.scrollY));
  }, [pathname]);
  return null;
}

export default App;

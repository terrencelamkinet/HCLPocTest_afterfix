import '../styles/dashboard.css'
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { Truck, UsersRound, DollarSign, Layout, Activity, Building2, Calendar, CheckSquare, FolderKanban, LayoutDashboard, Sparkles, TrendingUp, Users } from 'lucide-react'
import SvcIcon from '../components/SvcIcon'
import SlideDrawer from '../components/SlideDrawer'
import AIBriefingDrawer, { hktNow } from '../components/AIBriefingDrawer'
import WidgetAskAI from '../components/WidgetAskAI'

interface Task { id: string; title: string; priority: string; status: string; due_date: string | null; area?: string; custom_fields?: Record<string, any> }
interface Company { id: string; name: string; category?: string; industry?: string }
interface Touchpoint { id: string; type: string; title: string; description: string | null; company?: { name: string } | null; contact?: { name: string } | null; created_at: string }
interface Deal { id: string; name: string; amount: number | null; stage_id: string; probability: number; company?: { name: string } | null }
interface Contact { id: string; name: string; email: string | null; phone: string | null; position: string | null; company?: { name: string } | null }

// ── Demo data fallbacks ──
const demoContacts: Contact[] = [
  { id: 'demo-cont-1', name: 'David Chen', email: 'david@example.com', phone: '+852 9876 5432', position: 'CEO', company: { name: 'TechCorp' } },
  { id: 'demo-cont-2', name: 'Sarah Wong', email: 'sarah@example.com', phone: '+852 9123 4567', position: 'CTO', company: { name: 'Innovate Ltd' } },
  { id: 'demo-cont-3', name: 'Michael Lau', email: 'michael@example.com', phone: '+852 9000 1111', position: 'VP Sales', company: { name: 'Growth Inc' } },
]
const demoTasks: Task[] = [
  { id: 'demo-t-1', title: 'Follow up with TechCorp proposal', priority: 'P0', status: 'pending', due_date: new Date().toISOString(), area: '💼 Work' },
  { id: 'demo-t-2', title: 'Review Q3 pipeline report', priority: 'P1', status: 'in_progress', due_date: new Date().toISOString(), area: '💼 Work' },
  { id: 'demo-t-3', title: 'Prepare client presentation', priority: 'P1', status: 'pending', due_date: new Date(Date.now() + 86400000).toISOString(), area: '💼 Work' },
  { id: 'demo-t-4', title: 'Update CRM contact records', priority: 'P2', status: 'pending', due_date: null, area: '📚 Learning' },
  { id: 'demo-t-5', title: 'Schedule team sync meeting', priority: 'P2', status: 'done', due_date: new Date().toISOString(), area: '💼 Work' },
]
const demoDeals: Deal[] = [
  { id: 'demo-d-1', name: 'TechCorp Enterprise Plan', amount: 120000, stage_id: 'negotiation', probability: 70, company: { name: 'TechCorp' } },
  { id: 'demo-d-2', name: 'Innovate Ltd Platform', amount: 85000, stage_id: 'proposal', probability: 50, company: { name: 'Innovate Ltd' } },
  { id: 'demo-d-3', name: 'Growth Inc SaaS', amount: 45000, stage_id: 'qualification', probability: 30, company: { name: 'Growth Inc' } },
  { id: 'demo-d-4', name: 'DataSync Solutions', amount: 200000, stage_id: 'negotiation', probability: 60, company: { name: 'DataSync' } },
  { id: 'demo-d-5', name: 'CloudBase Migration', amount: 95000, stage_id: 'closed_won', probability: 100, company: { name: 'CloudBase' } },
]
const demoTPs: Touchpoint[] = [
  { id: 'demo-tp-1', type: 'meeting', title: 'Q3 Review with TechCorp', description: 'Discussed quarterly performance', company: { name: 'TechCorp' }, contact: { name: 'David Chen' }, created_at: new Date().toISOString() },
  { id: 'demo-tp-2', type: 'call', title: 'Discovery Call - Innovate Ltd', description: 'Initial product demo', company: { name: 'Innovate Ltd' }, contact: { name: 'Sarah Wong' }, created_at: new Date(Date.now() - 86400000).toISOString() },
  { id: 'demo-tp-3', type: 'email', title: 'Proposal sent to Growth Inc', description: 'Sent enterprise proposal', company: { name: 'Growth Inc' }, contact: { name: 'Michael Lau' }, created_at: new Date(Date.now() - 172800000).toISOString() },
]

const todayStr = (lang: string) => {
  // HKT 牆鐘時間 — Intl timeZone 自動轉換,唔好手動 +8 (會雙重 offset)
  const opts: Intl.DateTimeFormatOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'Asia/Hong_Kong' }
  if (lang === 'en') {
    return new Date().toLocaleDateString('en-US', opts)
  }
  return new Date().toLocaleDateString('zh-TW', opts)
}

/** HKT-based greeting key — 唔可以硬編碼 morning,要按 HKT 牆鐘時間 */
const hktGreetingKey = (): 'morning' | 'afternoon' | 'evening' | 'lateNight' => {
  const now = hktNow()
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes()
  if (mins >= 18 * 60) return 'evening'
  if (mins >= 12 * 60) return 'afternoon'
  if (mins >= 7 * 60) return 'morning'
  return 'lateNight'
}

/** Format ISO timestamp as HKT date (timezone-independent of browser). */
const fmtHKTDate = (iso: string, lang: string): string => {
  const locale = lang === 'en' ? 'en-US' : 'zh-TW'
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: 'long', day: 'numeric', timeZone: 'Asia/Hong_Kong',
  }).format(new Date(iso))
}

/** Format ISO timestamp as HKT date + time (timezone-independent of browser). */
const fmtHKTDateTime = (iso: string, lang: string): string => {
  const locale = lang === 'en' ? 'en-US' : 'zh-TW'
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Hong_Kong',
  }).format(new Date(iso))
}

const stages: Record<string, { label: string; color: string }> = {
  qualification: { label: 'Qualification', color: 'var(--color-blue)' },
  proposal: { label: 'Proposal', color: 'var(--color-warning)' },
  negotiation: { label: 'Negotiation', color: 'var(--color-purple)' },
  closed_won: { label: 'Closed Won', color: 'var(--color-success)' },
  closed_lost: { label: 'Closed Lost', color: 'var(--color-text-faint)' },
}
const stageKeys = ['qualification', 'proposal', 'negotiation', 'closed_won']

// ── ALL 37 design01 WIDGETS + 10 legacy widgets ──
type WidgetKey = string
interface WidgetDef { label: string; span: number }
// ── Unified size levels 1–7 for both axes — badge shows "(w,h)" e.g. (1,1) (1,2) ──
// Width level → grid column span; Height level → px. Same 1–7 scale on both axes.
// Width spans bumped up (2026-08-07): (n,n) was taller than wide — low levels
// now render closer to square on typical dashboard widths.
const SPAN_BY_LEVEL: Record<number, number> = { 1: 3, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12, 7: 12 }
const HEIGHT_BY_LEVEL: Record<number, number> = { 1: 160, 2: 200, 3: 240, 4: 280, 5: 320, 6: 400, 7: 480 }
const SIZE_LEVELS = [1, 2, 3, 4, 5, 6, 7]
// snap a raw value to the nearest level's value in the given map
const snapToLevel = (val: number, map: Record<number, number>): number => {
  let best = SIZE_LEVELS[0]
  for (const lv of SIZE_LEVELS) {
    if (Math.abs(val - map[lv]) < Math.abs(val - map[best])) best = lv
  }
  return map[best]
}
// reverse: which level is a stored value closest to (for the (w,h) badge)
const levelOf = (val: number, map: Record<number, number>): number => {
  let best = SIZE_LEVELS[0]
  for (const lv of SIZE_LEVELS) {
    if (Math.abs(val - map[lv]) < Math.abs(val - map[best])) best = lv
  }
  return best
}
const allWidgets: Record<string, WidgetDef> = {
  // Legacy (real data) widgets — keep for backward compat
  kpi_contacts: { label: 'Contacts', span: 6 },
  kpi_companies: { label: 'Companies', span: 6 },
  kpi_deals: { label: 'Deal Count', span: 6 },
  kpi_tasks: { label: 'Tasks', span: 6 },
  pipeline: { label: 'Deal Pipeline', span: 8 },
  tasks: { label: "Today's Tasks", span: 4 },
  touchpoints: { label: 'Recent Touchpoints', span: 4 },
  dealvalue: { label: 'Total Deal Value', span: 4 },
  aiinsight: { label: 'AI Insight', span: 4 },
  activity_feed: { label: 'Activity Feed', span: 12 },
  // ── Contacts (icon: Users) ──
  c1: { label: 'c1', span: 4 },
  c2: { label: 'c2', span: 4 },
  c3: { label: 'c3', span: 3 },
  c4: { label: 'c4', span: 4 },
  c5: { label: 'c5', span: 3 },
  // ── Companies (icon: Building2) ──
  co1: { label: 'co1', span: 3 },
  co2: { label: 'co2', span: 4 },
  co3: { label: 'co3', span: 4 },
  co4: { label: 'co4', span: 4 },
  co5: { label: 'co5', span: 3 },
  // ── Deals (icon: TrendingUp) ──
  d1: { label: 'd1', span: 3 },
  d2: { label: 'd2', span: 6 },
  d3: { label: 'd3', span: 4 },
  d4: { label: 'd4', span: 4 },
  d5: { label: 'd5', span: 4 },
  // ── Projects (icon: FolderKanban) ──
  p1: { label: 'p1', span: 3 },
  p2: { label: 'p2', span: 4 },
  p3: { label: 'p3', span: 6 },
  p4: { label: 'p4', span: 4 },
  // ── Tasks (icon: CheckSquare) ──
  t1: { label: 't1', span: 4 },
  t2: { label: 't2', span: 4 },
  t3: { label: 't3', span: 4 },
  t4: { label: 't4', span: 3 },
  // ── Calendar (icon: Calendar) ──
  cal1: { label: 'cal1', span: 4 },
  cal2: { label: 'cal2', span: 4 },
  cal3: { label: 'cal3', span: 4 },
  // ── Shipping (icon: Truck) ──
  s1: { label: 's1', span: 4 },
  s2: { label: 's2', span: 4 },
  s3: { label: 's3', span: 4 },
  s4: { label: 's4', span: 4 },
  s5: { label: 's5', span: 4 },
  // ── Team (icon: UsersRound) ──
  te1: { label: 'te1', span: 4 },
  te2: { label: 'te2', span: 3 },
  te3: { label: 'te3', span: 4 },
  te4: { label: 'te4', span: 4 },
  // ── Business (icon: Activity) ──
  b1: { label: 'b1', span: 4 },
  b2: { label: 'b2', span: 4 },
  ask_ai: { label: 'Ask AI', span: 4 },
}

// Widgets hidden from the dashboard (2026-08-07): all deal-related widgets are
// hidden per product direction — module-additive: defs/bodies stay in code for
// backward compat, but they are excluded from the grid render, the picker, and
// the default layout. To re-enable later, remove the key from this set.
const HIDDEN_WIDGETS: ReadonlySet<WidgetKey> = new Set([
  'kpi_deals', 'pipeline', 'dealvalue',
  'd1', 'd2', 'd3', 'd4', 'd5',
])

const defaultOrder: WidgetKey[] = [
  'kpi_contacts', 'kpi_companies', 'kpi_tasks',
  't1', 'ask_ai', 'c2', 'co3', 's1', 'te2', 'cal1', 'activity_feed',
]

interface ModuleWidget { key: string; name: string; desc: string }
interface ModuleData { id: string; name: string; widgets: ModuleWidget[] }
const modulesData: ModuleData[] = [
  { id: 'contacts', name: 'Contacts', widgets: [
    { key: 'c1', name: 'c1', desc: 'desc_c1' },
    { key: 'c2', name: 'c2', desc: 'desc_c2' },
    { key: 'c3', name: 'c3', desc: 'desc_c3' },
    { key: 'c4', name: 'c4', desc: 'desc_c4' },
    { key: 'c5', name: 'c5', desc: 'desc_c5' },
  ]},
  { id: 'companies', name: 'Companies', widgets: [
    { key: 'co1', name: 'co1', desc: 'desc_co1' },
    { key: 'co2', name: 'co2', desc: 'desc_co2' },
    { key: 'co3', name: 'co3', desc: 'desc_co3' },
    { key: 'co4', name: 'co4', desc: 'desc_co4' },
    { key: 'co5', name: 'co5', desc: 'desc_co5' },
  ]},
  { id: 'deals', name: 'Deals', widgets: [
    { key: 'd1', name: 'd1', desc: 'desc_d1' },
    { key: 'd2', name: 'd2', desc: 'desc_d2' },
    { key: 'd3', name: 'd3', desc: 'desc_d3' },
    { key: 'd4', name: 'd4', desc: 'desc_d4' },
    { key: 'd5', name: 'd5', desc: 'desc_d5' },
  ]},
  { id: 'projects', name: 'Projects', widgets: [
    { key: 'p1', name: 'p1', desc: 'desc_p1' },
    { key: 'p2', name: 'p2', desc: 'desc_p2' },
    { key: 'p3', name: 'p3', desc: 'desc_p3' },
    { key: 'p4', name: 'p4', desc: 'desc_p4' },
  ]},
  { id: 'tasks', name: 'Tasks', widgets: [
    { key: 't1', name: 't1', desc: 'desc_t1' },
    { key: 't2', name: 't2', desc: 'desc_t2' },
    { key: 't3', name: 't3', desc: 'desc_t3' },
    { key: 't4', name: 't4', desc: 'desc_t4' },
  ]},
  { id: 'calendar', name: 'Calendar', widgets: [
    { key: 'cal1', name: 'cal1', desc: 'desc_cal1' },
    { key: 'cal2', name: 'cal2', desc: 'desc_cal2' },
    { key: 'cal3', name: 'cal3', desc: 'desc_cal3' },
  ]},
  { id: 'shipping', name: 'Shipping', widgets: [
    { key: 's1', name: 's1', desc: 'desc_s1' },
    { key: 's2', name: 's2', desc: 'desc_s2' },
    { key: 's3', name: 's3', desc: 'desc_s3' },
    { key: 's4', name: 's4', desc: 'desc_s4' },
    { key: 's5', name: 's5', desc: 'desc_s5' },
  ]},
  { id: 'team', name: 'Team', widgets: [
    { key: 'te1', name: 'te1', desc: 'desc_te1' },
    { key: 'te2', name: 'te2', desc: 'desc_te2' },
    { key: 'te3', name: 'te3', desc: 'desc_te3' },
    { key: 'te4', name: 'te4', desc: 'desc_te4' },
  ]},
  { id: 'business', name: 'Business', widgets: [
    { key: 'b1', name: 'b1', desc: 'desc_b1' },
    { key: 'b2', name: 'b2', desc: 'desc_b2' },
  ]},
  { id: 'legacy', name: 'Core Stats', widgets: [
    { key: 'kpi_contacts', name: 'Contacts Count', desc: 'desc_kpi_contacts' },
    { key: 'kpi_companies', name: 'Companies Count', desc: 'desc_kpi_companies' },
    { key: 'kpi_deals', name: 'Deal Count', desc: 'desc_kpi_deals' },
    { key: 'kpi_tasks', name: 'Task Count', desc: 'desc_kpi_tasks' },
    { key: 'pipeline', name: 'Deal Pipeline', desc: 'desc_pipeline' },
    { key: 'tasks', name: "Today's Tasks", desc: 'desc_tasks' },
    { key: 'touchpoints', name: 'Recent Touchpoints', desc: 'desc_touchpoints' },
    { key: 'dealvalue', name: 'Total Deal Value', desc: 'desc_dealvalue' },
    { key: 'aiinsight', name: 'AI Insight', desc: 'desc_aiinsight' },
    { key: 'activity_feed', name: 'Activity Feed', desc: 'desc_activity_feed' },
    { key: 'ask_ai', name: 'Ask AI', desc: 'desc_ask_ai' },
  ]},
]

/** Map widget keys to i18n label keys for display */
const widgetLabelKey: Record<string, string> = {
  c1: 'dashboard.widgets.newContacts',
  c2: 'dashboard.widgets.pendingContacts',
  c3: 'dashboard.widgets.dataCompleteness',
  c4: 'dashboard.widgets.recentInteractions',
  c5: 'dashboard.widgets.sourceDistribution',
  co1: 'dashboard.widgets.totalCompanies',
  co2: 'dashboard.widgets.clientTier',
  co3: 'dashboard.widgets.renewalReminders',
  co4: 'dashboard.widgets.healthScore',
  co5: 'dashboard.widgets.industryDistribution',
  d1: 'dashboard.widgets.pipelineTotal',
  d2: 'dashboard.widgets.stageDistribution',
  d3: 'dashboard.widgets.stagnationAlerts',
  d4: 'dashboard.widgets.forecastRate',
  d5: 'dashboard.widgets.recentWon',
  p1: 'dashboard.widgets.activeProjects',
  p2: 'dashboard.widgets.milestoneTracking',
  p3: 'dashboard.widgets.progressOverview',
  p4: 'dashboard.widgets.resourceAllocation',
  t1: 'dashboard.widgets.todayTodos',
  t2: 'dashboard.widgets.overdueTasks',
  t3: 'dashboard.widgets.priorityList',
  t4: 'dashboard.widgets.completionRate',
  cal1: 'dashboard.widgets.upcomingMeetings',
  cal2: 'dashboard.widgets.meetingDensity',
  cal3: 'dashboard.widgets.visitSchedule',
  s1: 'dashboard.widgets.pendingOrders',
  s2: 'dashboard.widgets.delayAlerts',
  s3: 'dashboard.widgets.statusDistribution',
  s4: 'dashboard.widgets.routePerformance',
  s5: 'dashboard.widgets.shippingCostOverview',
  te1: 'dashboard.widgets.workloadDistribution',
  te2: 'dashboard.widgets.onlineStatus',
  te3: 'dashboard.widgets.targetRate',
  te4: 'dashboard.widgets.leaderboard',
  b1: 'dashboard.widgets.subscriptionStatus',
  b2: 'dashboard.widgets.systemUsage',
  kpi_contacts: 'dashboard.widgets.totalCustomers',
  kpi_companies: 'dashboard.widgets.totalCompanies',
  kpi_deals: 'dashboard.widgets.activeDeals',
  kpi_tasks: 'dashboard.widgets.tasksDue',
  pipeline: 'dashboard.widgets.pipeline',
  tasks: 'dashboard.widgets.tasksDue',
  touchpoints: 'dashboard.widgets.recentActivity',
  dealvalue: 'dashboard.widgets.dealTotal',
  aiinsight: 'dashboard.widgets.aiInsight',
  activity_feed: 'dashboard.widgets.recentActivity',
}

export default function DashboardNew() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [modules, setModules] = useState<Record<string, boolean>>({})
  const aiOn = modules['ai_assistant'] ?? true
  const [editing, setEditing] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const newRef = useRef<HTMLDivElement>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [widgetSearch, setWidgetSearch] = useState('')
  // Drag state
  const dragKey = useRef<string | null>(null)
  const dragPending = useRef(false)
  const gridRef = useRef<HTMLDivElement>(null)
  // Widget order — persists via API (cross-browser)
  const [order, setOrder] = useState<WidgetKey[]>([...defaultOrder])
  // Per-widget size levels 1–7 (user-resized only). Width level → span,
  // height level → aspect ratio (w/h), so (n,n) is ALWAYS square at any
  // viewport width — height derives from width, not fixed px.
  const [wLevels, setWLevels] = useState<Record<string, number>>({})
  const [hLevels, setHLevels] = useState<Record<string, number>>({})
  // Grid stays hidden until server layout (order/spans/heights) is loaded —
  // avoids flash of default-size widgets before user's saved sizes arrive.
  const [layoutReady, setLayoutReady] = useState(false)
  const orderLoaded = useRef(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined as any)
  // When order is set from a server load (not a user action), skip the save
  // effect — otherwise every page load re-PUTs the order, and a stale GET can
  // silently revert the user's just-saved layout.
  const skipSaveRef = useRef(false)
  // ── Compact detection — KPI stat cards become 2-per-row squares.
  // Triggered on any non-desktop surface: ≤1024px viewports OR touch devices
  // (phones/tablets in desktop-mode webviews can report >1024px).
  const COMPACT_MQ = '(max-width: 1024px), (pointer: coarse)'
  const [isCompact, setIsCompact] = useState(() => window.matchMedia(COMPACT_MQ).matches)
  useEffect(() => {
    const mq = window.matchMedia(COMPACT_MQ)
    const h = (e: MediaQueryListEvent) => setIsCompact(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  // Phone detection — ≤640px single-column grid. KPI cards must NOT keep the
  // 1:1 inline aspect on phones (CSS `aspect-ratio: auto` loses to inline
  // styles), otherwise they render as huge full-width squares.
  const PHONE_MQ = '(max-width: 640px)'
  const [isPhone, setIsPhone] = useState(() => window.matchMedia(PHONE_MQ).matches)
  useEffect(() => {
    const mq = window.matchMedia(PHONE_MQ)
    const h = (e: MediaQueryListEvent) => setIsPhone(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  // Data
  const [stats, setStats] = useState({ contacts: 0, deals: 0, dealValue: '', tasks: 0, companies: 0 })
  const [tasks, setTasks] = useState<Task[]>([])
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [deals, setDeals] = useState<Deal[]>([])
  const [companyList, setCompanyList] = useState<Company[]>([])
  const [projectsTotal, setProjectsTotal] = useState(0)
  const [projects, setProjects] = useState<any[]>([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [calendarEvents, setCalendarEvents] = useState<any[]>([])

  // ── Drawer state ──
  const [detailDrawer, setDetailDrawer] = useState(false)
  const [drawerTitle, setDrawerTitle] = useState('')
  const [drawerContent, setDrawerContent] = useState<React.ReactNode>(null)
  const openDrawer = (title: string, content: React.ReactNode) => {
    setDrawerTitle(title)
    setDrawerContent(content)
    setDetailDrawer(true)
  }

  useEffect(() => {
    const h = (e: MouseEvent) => { if (newRef.current && !newRef.current.contains(e.target as Node)) setNewOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const fetchData = useCallback(async () => {
    try {
      const [cRes, coRes, dRes, tRes, tpRes, coListRes, pRes, contRes, calRes] = await Promise.all([
        apiClient.get<{ total: number }>('/api/v1/crm/contacts?limit=1'),
        apiClient.get<{ total: number }>('/api/v1/crm/companies?limit=1'),
        apiClient.get<{ items: Deal[]; total: number }>('/api/v1/crm/deals?limit=100'),
        apiClient.get<{ items: Task[]; total: number }>('/api/v1/crm/tasks?limit=10'),
        apiClient.get<{ items: Touchpoint[]; total: number }>('/api/v1/crm/touchpoints?limit=10'),
        apiClient.get<{ items: Company[]; total: number }>('/api/v1/crm/companies?limit=50'),
        apiClient.get<{ items: any[]; total: number }>('/api/v1/crm/projects?limit=50').catch(() => ({ items: [], total: 0 })),
        apiClient.get<{ items: Contact[]; total: number }>('/api/v1/crm/contacts?limit=10').catch(() => ({ items: [], total: 0 })),
        apiClient.get<any[]>('/api/v1/crm/calendar-events').catch(() => []),
      ])
      const dealsList = dRes.items || demoDeals
      const totalVal = dealsList.reduce((s: number, d: Deal) => s + (d.amount || 0), 0)
      const fmt = (n: number) => n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${(n / 1e3).toFixed(0)}K` : `$${n}`
      setStats({
        contacts: cRes.total || demoContacts.length, deals: dealsList.length,
        dealValue: totalVal ? fmt(totalVal) : '$545K', tasks: tRes.total || demoTasks.length, companies: coRes.total || demoContacts.length,
      })
      setTasks(tRes.items?.length ? tRes.items : demoTasks)
      setTouchpoints((tpRes.items?.length ? tpRes.items : demoTPs).slice(0, 5))
      setDeals(dealsList)
      setCompanyList(coListRes.items || [])
      setProjectsTotal(pRes.total || 0)
      setProjects(pRes.items || [])
      setContacts(contRes.items?.length ? contRes.items : demoContacts)
      const evtList: any[] = Array.isArray(calRes) ? calRes : []
      const nowMs = Date.now()
      setCalendarEvents(evtList.filter((e: any) => e && e.start && new Date(e.start).getTime() >= nowMs - 60000).sort((a: any, b: any) => new Date(a.start).getTime() - new Date(b.start).getTime()).slice(0, 3))
    } catch {
      // Fallback to demo data
      setStats({ contacts: 3, deals: 5, dealValue: '$545K', tasks: 5, companies: 3 })
      setTasks(demoTasks)
      setTouchpoints(demoTPs.slice(0, 5))
      setDeals(demoDeals)
      setContacts(demoContacts)
    }
  }, [])
  useEffect(() => { fetchData() }, [fetchData])

  // ── Dashboard layout persistence + module settings (single API call) ──
  useEffect(() => {
    const loadAll = async () => {
      try {
        const list: any[] = await apiClient.get('/api/v1/crm/module-settings')
        // module enable map
        const map: Record<string, boolean> = {}
        ;(list || []).forEach((m: any) => { map[m.module_key] = m.enabled })
        setModules(map)
        // dashboard widget order + resize levels (w,h) with legacy span/px migration
        const dash = (list || []).find((m: any) => m.module_key === 'dashboard')
        if (dash?.settings) {
          // server-loaded state must never trigger a write-back
          skipSaveRef.current = true
          if (dash.settings.widgetOrder?.length) {
            // Strip hidden (deal) widgets from the persisted order once, so the
            // next save writes back a clean order without hidden keys.
            setOrder(dash.settings.widgetOrder.filter((k: string) => !HIDDEN_WIDGETS.has(k)))
          }
          const wl: Record<string, number> = {}
          const hl: Record<string, number> = {}
          const lv = dash.settings.widgetLevels
          if (lv) {
            Object.entries(lv).forEach(([k, v]) => {
              if (Array.isArray(v) && v.length >= 2) { wl[k] = v[0]; hl[k] = v[1] }
            })
          }
          // legacy v4.5–v4.8: widgetSpans/widgetHeights (px) → nearest level
          const lw = dash.settings.widgetSpans
          const lh = dash.settings.widgetHeights
          if (lw) Object.entries(lw).forEach(([k, span]) => { if (!(k in wl)) wl[k] = levelOf(span as number, SPAN_BY_LEVEL) })
          if (lh) Object.entries(lh).forEach(([k, px]) => { if (!(k in hl)) hl[k] = levelOf(px as number, HEIGHT_BY_LEVEL) })
          if (Object.keys(wl).length) setWLevels(wl)
          if (Object.keys(hl).length) setHLevels(hl)
        }
      } catch { /* use defaults */ }
      orderLoaded.current = true
      setLayoutReady(true)
    }
    loadAll()
    const handler = () => loadAll()
    window.addEventListener('modules-changed', handler)
    return () => window.removeEventListener('modules-changed', handler)
  }, [])

  // Debounced save when order / levels change (user actions only —
  // server-loaded state sets skipSaveRef so it never triggers a write-back)
  useEffect(() => {
    if (!orderLoaded.current) return
    if (skipSaveRef.current) { skipSaveRef.current = false; return }
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      try {
        // persist as widgetLevels: { key: [wLevel, hLevel] }
        const levelPairs: Record<string, [number, number]> = {}
        Object.keys(wLevels).forEach(k => { levelPairs[k] = [wLevels[k], hLevels[k] ?? 1] })
        await apiClient.put('/api/v1/crm/module-settings/dashboard', {
          module_key: 'dashboard',
          enabled: true,
          settings: { widgetOrder: order, widgetLevels: levelPairs },
        })
      } catch { /* silent */ }
    }, 600)
    return () => clearTimeout(saveTimer.current)
  }, [order, wLevels, hLevels])

  // ── Build Detail Functions ──
  const buildTaskDetail = (task: Task) => (
    <div style={{padding:4,fontSize:13.5,lineHeight:1.6}}>
      <div style={{fontSize:16,fontWeight:700,marginBottom:12}}>{task.title}</div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('tasks.priority')}</span><span className={`badge ${task.priority==='P0'?'warn':task.priority==='P1'?'':'ok'}`}>{task.priority||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('tasks.status')}</span><span>{task.status||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('tasks.dueDate')}</span><span>{task.due_date ? fmtHKTDate(task.due_date, i18n.language) : '—'}</span></div>
      {task.area && <div className="stage-row"><span style={{fontWeight:600}}>Area</span><span>{task.area}</span></div>}
    </div>
  )
  const buildDealDetail = (deal: Deal) => (
    <div style={{padding:4,fontSize:13.5,lineHeight:1.6}}>
      <div style={{fontSize:16,fontWeight:700,marginBottom:12}}>{deal.name}</div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('deals.amount')}</span><span>${deal.amount?.toLocaleString()||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('deals.stage')}</span><span style={{color:stages[deal.stage_id]?.color||'inherit'}}>{stages[deal.stage_id]?.label||deal.stage_id}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('pages.deals.probability')}</span><span>{deal.probability}%</span></div>
      {deal.company?.name && <div className="stage-row"><span style={{fontWeight:600}}>{t('contacts.company')}</span><span>{deal.company.name}</span></div>}
    </div>
  )
  const buildContactDetail = (contact: Contact) => (
    <div style={{padding:4,fontSize:13.5,lineHeight:1.6}}>
      <div style={{fontSize:16,fontWeight:700,marginBottom:12}}>{contact.name}</div>

      {/* Quick actions: call / email / WhatsApp (NovaCRM-style architecture) */}
      <div className="quick-actions">
        {contact.phone && (
          <a href={`tel:${String(contact.phone).replace(/[^\d+]/g, '')}`} className="btn-secondary">
            <SvcIcon name="phone" className="w-3.5 h-3.5" /> {t('common.call')}
          </a>
        )}
        {contact.email && (
          <a href={`mailto:${contact.email}`} className="btn-secondary">
            <SvcIcon name="mail" className="w-3.5 h-3.5" /> {t('common.email')}
          </a>
        )}
        {contact.phone && (
          <a href={`https://wa.me/${String(contact.phone).replace(/[^\d]/g, '')}`} target="_blank" rel="noopener noreferrer" className="btn-secondary">
            <SvcIcon name="message-circle" className="w-3.5 h-3.5" /> {t('common.message')}
          </a>
        )}
      </div>

      {/* Label:value info list */}
      <div className="info-list">
        {contact.email && (
          <div className="info-row">
            <span className="info-label">{t('common.email')}</span>
            <span className="info-value">{contact.email}</span>
          </div>
        )}
        {contact.phone && (
          <div className="info-row">
            <span className="info-label">{t('common.phone')}</span>
            <span className="info-value">{contact.phone}</span>
          </div>
        )}
        {contact.position && (
          <div className="info-row">
            <span className="info-label">{t('contacts.jobTitle')}</span>
            <span className="info-value">{contact.position}</span>
          </div>
        )}
        {contact.company?.name && (
          <div className="info-row">
            <span className="info-label">{t('common.company')}</span>
            <span className="info-value">{contact.company.name}</span>
          </div>
        )}
      </div>

      {/* Full profile link */}
      <button className="btn-secondary" style={{marginTop:8}} onClick={() => { setDetailDrawer(false); navigate(`/contacts/${contact.id}`) }}>
        <SvcIcon name="external-link" className="w-3.5 h-3.5" /> {t('common.viewFullProfile')}
      </button>
    </div>
  )
  const buildTouchpointDetail = (tp: Touchpoint) => (
    <div style={{padding:4,fontSize:13.5,lineHeight:1.6}}>
      <div style={{fontSize:16,fontWeight:700,marginBottom:12}}>{tp.title}</div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('touchpoint.type')}</span><span className="badge" style={{background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',color:'var(--color-primary)'}}>{tp.type}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('contacts.name')}</span><span>{tp.contact?.name||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('contacts.company')}</span><span>{tp.company?.name||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('touchpoint.notes')}</span><span>{tp.description||'—'}</span></div>
      <div className="stage-row"><span style={{fontWeight:600}}>{t('touchpoint.type')}</span><span>{fmtHKTDateTime(tp.created_at, i18n.language)}</span></div>
    </div>
  )

  const pipeline = stageKeys.map(k => {
    const items = deals.filter(d => d.stage_id === k)
    return {
      key: k, label: stages[k]?.label || k, count: items.length,
      total: items.reduce((s, d) => s + (d.amount || 0), 0),
      color: stages[k]?.color || 'var(--color-primary)',
    }
  })
  const maxPipelineTotal = Math.max(1, ...pipeline.map(p => p.total))

  // Widget icon helper
  const addWidget = (k: string) => {
    if (order.includes(k)) return
    setOrder([...order, k])
    setDrawerOpen(false)
  }
  const removeW = (k: string) => {
    setOrder(order.filter(x => x !== k))
  }
  // Mobile/touch-friendly reorder — HTML5 DnD doesn't work on touch devices,
  // so provide ↑/↓ buttons as the reliable path (kept alongside desktop drag).
  const moveW = (k: string, dir: -1 | 1) => {
    setOrder(prev => {
      const i = prev.indexOf(k)
      if (i < 0) return prev
      const j = i + dir
      if (j < 0 || j >= prev.length) return prev
      const next = [...prev]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }
  // RAF-throttled drag
  const handleDragStart = (k: string) => { dragKey.current = k; dragPending.current = false }
  const handleDragOver = (e: React.DragEvent, k: string) => {
    if (!editing || !dragKey.current || dragKey.current === k) return
    e.preventDefault()
    if (dragPending.current) return
    dragPending.current = true
    requestAnimationFrame(() => {
      dragPending.current = false
      const grid = gridRef.current
      if (!grid) return
      const dragged = grid.querySelector(`[data-key="${dragKey.current}"]`) as HTMLElement
      const target = e.currentTarget as HTMLElement
      if (!dragged || dragged === target) return
      const rect = target.getBoundingClientRect()
      const before = (e.clientX - rect.left) < rect.width / 2
      grid.insertBefore(dragged, before ? target : target.nextSibling)
    })
  }
  const handleDragEnd = () => {
    dragKey.current = null
    const grid = gridRef.current
    if (!grid) return
    const domKeys: string[] = []
    grid.querySelectorAll('[data-key]').forEach(el => {
      const key = el.getAttribute('data-key')
      if (key) domKeys.push(key)
    })
    if (domKeys.length > 0) setOrder(domKeys)
  }

  // ── Drawer detail content builders ──
  const widgetBodies: Record<string, () => React.ReactElement> = {
    // ── Legacy widgets (real data) ──
    kpi_contacts: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{fontSize:isCompact ? 48 : 36,color:'var(--color-blue)',cursor:'pointer'}} onClick={() => openDrawer(t('contacts.title'), <div>{contacts.map(c => <div key={c.id} className="list-row" style={{cursor:'pointer'}} onClick={() => openDrawer(c.name, buildContactDetail(c))}><SvcIcon name="users" size={14} style={{color:'var(--color-blue)',flexShrink:0}} /><span className="name">{c.name}</span><span className="meta">{c.company?.name||''}</span></div>)}</div>)}>{stats.contacts}</span>
        <span style={{fontSize:13.5,color:'var(--color-text-muted)',fontWeight:500}}>{t(widgetLabelKey.kpi_contacts)}</span>
      </div>
    ),
    kpi_companies: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8,cursor:'pointer'}} onClick={() => openDrawer(`${t('companies.title')} (${companyList.length})`, <div>{companyList.length === 0
        ? <div style={{padding:'16px 20px',fontSize:12,color:'var(--color-text-faint)'}}>{t('companies.empty')}</div>
        : companyList.map(c => (
            <div key={c.id} className="list-row" style={{cursor:'pointer'}} onClick={() => { navigate(`/companies/${c.id}`); setDetailDrawer(false) }}>
              <SvcIcon name="building-2" size={14} style={{color:'var(--color-purple)',flexShrink:0}} />
              <span className="name">{c.name}</span>
              <span className="meta">{c.industry || c.category || '—'}</span>
            </div>
          ))
      }</div>)}>
        <span className="kpi-val" style={{fontSize:isCompact ? 48 : 36,color:'var(--color-purple)'}}>{stats.companies}</span>
        <span style={{fontSize:13.5,color:'var(--color-text-muted)',fontWeight:500}}>{t(widgetLabelKey.kpi_companies)}</span>
      </div>
    ),
    kpi_deals: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{fontSize:isCompact ? 48 : 36,color:'var(--color-primary)',cursor:'pointer'}} onClick={() => openDrawer(t('deals.title'), <div>{deals.map(d => <div key={d.id} className="list-row" style={{cursor:'pointer'}} onClick={() => openDrawer(d.name, buildDealDetail(d))}><SvcIcon name="trending-up" size={14} style={{color:'var(--color-primary)',flexShrink:0}} /><span className="name">{d.name}</span><span className="meta">${d.amount?.toLocaleString()||''}</span></div>)}</div>)}>{stats.deals}</span>
        <span style={{fontSize:13.5,color:'var(--color-text-muted)',fontWeight:500}}>{t(widgetLabelKey.kpi_deals)}</span>
      </div>
    ),
    kpi_tasks: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{fontSize:isCompact ? 48 : 36,color:'var(--color-warning)',cursor:'pointer'}} onClick={() => openDrawer(t('tasks.title'), <div>{tasks.map(t => <div key={t.id} className="list-row" style={{cursor:'pointer'}} onClick={() => openDrawer(t.title, buildTaskDetail(t))}><SvcIcon name="check-square" size={14} style={{color:'var(--color-warning)',flexShrink:0}} /><span className="name">{t.title}</span><span className="meta">{t.priority||''}</span></div>)}</div>)}>{stats.tasks}</span>
        <span style={{fontSize:13.5,color:'var(--color-text-muted)',fontWeight:500}}>{t(widgetLabelKey.kpi_tasks)}</span>
      </div>
    ),
    tasks: () => {
      const areaSymbol = (area?: string) => {
        if (!area) return null
        const a = area.toLowerCase()
        if (a.includes('work') || a.includes('💼')) return <span style={{marginRight:4}}>💼</span>
        if (a.includes('personal') || a.includes('home') || a.includes('🏠')) return <span style={{marginRight:4}}>🏠</span>
        if (a.includes('jesus') || a.includes('church') || a.includes('✝️')) return <span style={{marginRight:4}}>✝️</span>
        if (a.includes('learning') || a.includes('study') || a.includes('📚')) return <span style={{marginRight:4}}>📚</span>
        return null
      }
      const isOverdue = (t: Task) => t.due_date && new Date(t.due_date) < hktNow() && t.status !== 'done'
      return (
        tasks.length === 0
          ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('pages.tasks.empty')}</div>
          : <>{tasks.slice(0,5).map(task => (
              <div key={task.id} className="list-row" onClick={() => openDrawer(task.title, buildTaskDetail(task))} style={{cursor:'pointer'}}>
                <SvcIcon name="check-square" size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                {areaSymbol(task.area)}
                <span className="name">{task.title}</span>
                {isOverdue(task) && <span className="badge" style={{background:'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))',color:'var(--color-notification)',marginLeft:4,flexShrink:0}}>{t('dashboard.widgets.overdue')}</span>}
                <span className="badge" style={{
                  background: task.priority==='P0'?'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))':task.priority==='P1'?'color-mix(in oklch,var(--color-warning)18%,var(--color-surface))':'color-mix(in oklch,var(--color-success)18%,var(--color-surface))',
                  color: task.priority==='P0'?'var(--color-notification)':task.priority==='P1'?'var(--color-warning)':'var(--color-success)'
                }}>{task.custom_fields?.notion_priority || task.priority || 'P3'}</span>
              </div>
            ))}</>
      )
    },
    touchpoints: () => (
      touchpoints.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('common.noResults')}</div>
        : <>{touchpoints.map(tp => (
            <div key={tp.id} className="list-row" onClick={() => openDrawer(tp.title, buildTouchpointDetail(tp))} style={{cursor:'pointer'}}>
              <SvcIcon name="activity" size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} />
              <span className="name">{tp.title}</span>
              <span className="meta">{tp.company?.name||''}</span>
            </div>
          ))}</>
    ),
    pipeline: () => (
      <>{pipeline.map(p => (
        <div key={p.key} className="stage-row" style={{cursor:'pointer'}} onClick={() => {
          const filtered = deals.filter(d => d.stage_id === p.key)
          openDrawer(p.label, <div>{filtered.map(d => <div key={d.id} className="list-row" style={{cursor:'pointer'}} onClick={() => openDrawer(d.name, buildDealDetail(d))}><SvcIcon name="trending-up" size={14} style={{color:p.color,flexShrink:0}} /><span className="name">{d.name}</span><span className="meta">${d.amount?.toLocaleString()||''}</span></div>)}</div>)
        }}>
          <div className="stage-label">
            <span>{p.label}</span>
            <span>{p.count} {t('deals.title')} · ${p.total.toLocaleString()}</span>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{width:`${(p.total/maxPipelineTotal)*100}%`,background:p.color}} />
          </div>
        </div>
      ))}</>
    ),
    dealvalue: () => (
      <><div className="kpi-val" style={{fontSize:26,color:'var(--color-primary)',cursor:'pointer'}} onClick={() => {
        const closedWon = deals.filter(d => d.stage_id === 'closed_won')
        openDrawer(t('pages.deals.won') + ' ' + t('deals.title'), <div>{closedWon.map(d => <div key={d.id} className="list-row" style={{cursor:'pointer'}} onClick={() => openDrawer(d.name, buildDealDetail(d))}><SvcIcon name="trending-up" size={14} style={{color:'var(--color-success)',flexShrink:0}} /><span className="name">{d.name}</span><span className="meta">${d.amount?.toLocaleString()||''}</span></div>)}</div>)
      }}>{stats.dealValue||'—'}</div>
      <div className="kpi-delta" style={{color:'var(--color-success)'}}>↑ {deals.filter(d=>d.stage_id==='closed_won').length} {t('status.won')}</div></>
    ),
    aiinsight: () => {
      const overdueCount = tasks.filter(t => t.due_date && new Date(t.due_date) < hktNow() && t.status !== 'done').length
      const p0Count = tasks.filter(t => t.priority === 'P0').length
      const todayDue = tasks.filter(t => {
        if (!t.due_date) return false
        const d = new Date(t.due_date)
        const today = hktNow()
        return d.getUTCDate() === today.getUTCDate() && d.getUTCMonth() === today.getUTCMonth() && d.getUTCFullYear() === today.getUTCFullYear()
      }).length
      return (
        <div style={{fontSize:13,lineHeight:1.5,color:'var(--color-text-muted)'}}>
          <p>• {stats.contacts} {t('contacts.title').toLowerCase()} {t('status.active')}</p>
          <p>• {stats.tasks} {t('tasks.title').toLowerCase()} {t('status.pending')}</p>
          <p>• {overdueCount} {t('dashboard.widgets.overdue')}, {p0Count} P0 {t('priority.urgent')}</p>
          <p>• {todayDue} {t('tasks.title').toLowerCase()} {t('tasks.dueDate')}</p>
        </div>
      )
    },
    activity_feed: () => (
      <div style={{fontSize:13}}>
        {touchpoints.length === 0
          ? <div style={{padding:'16px 0',textAlign:'center',fontSize:12,color:'var(--color-text-faint)'}}>{t('common.noResults')}</div>
          : <table style={{width:'100%',borderCollapse:'collapse',fontSize:12.5}}>
              <thead>
                <tr style={{color:'var(--color-text-faint)',fontWeight:600,borderBottom:'1px solid var(--color-divider)'}}>
                  <th style={{textAlign:'left',padding:'6px 4px'}}>{t('touchpoint.type')}</th>
                  <th style={{textAlign:'left',padding:'6px 4px'}}>{t('touchpoint.title')}</th>
                  <th style={{textAlign:'left',padding:'6px 4px'}}>{t('contacts.company')}</th>
                  <th style={{textAlign:'right',padding:'6px 4px'}}>{t('touchpoint.type')}</th>
                </tr>
              </thead>
              <tbody>
                {touchpoints.map(tp => (
                  <tr key={tp.id} style={{borderBottom:'1px solid var(--color-divider)',cursor:'pointer'}} onClick={() => navigate(`/touchpoints/${tp.id}`)}>
                    <td style={{padding:'8px 4px'}}><span className="badge" style={{background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',color:'var(--color-primary)'}}>{tp.type}</span></td>
                    <td style={{padding:'8px 4px',fontWeight:500}}>{tp.title}</td>
                    <td style={{padding:'8px 4px',color:'var(--color-text-muted)'}}>{tp.company?.name||'—'}</td>
                    <td style={{padding:'8px 4px',textAlign:'right',color:'var(--color-text-faint)'}}>{fmtHKTDate(tp.created_at, i18n.language)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
        }
      </div>
    ),
    // ── Contacts (demo data) ──
    c1: () => {
      const total = contacts.length || stats.contacts
      const newCount = Math.min(12, Math.max(0, total))
      const barPct = total > 0 ? Math.min(100, Math.round((newCount / Math.max(12, total)) * 100)) : 0
      return (
        <div style={{display:'flex',flexDirection:'column',gap:12}}>
          <div className="kpi-row">
            <span className="kpi-val" style={{color:'var(--color-blue)'}}>{total}</span>
            <span className="kpi-delta up" style={{marginLeft:8}}>{t('contacts.title')}</span>
          </div>
          <div className="list-row"><span className="name">{t('contacts.title')}</span></div>
          <div className="bar-track" style={{marginTop:4}}><div className="bar-fill" style={{width:`${barPct}%`,background:'var(--color-blue)'}} /></div>
        </div>
      )
    },
    c2: () => (
      <><div className="list-row"><SvcIcon name="check-square" size={14} style={{color:'var(--color-warning)',flexShrink:0}} /><span className="name">旭輝空運 — 跟進續約</span><span className="badge warn">{t('priority.urgent')}</span></div>
      <div className="list-row"><SvcIcon name="check-square" size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">深圳華良物流 — 報價回覆</span></div>
      <div className="list-row"><SvcIcon name="check-square" size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">林海珊 — 會議跟進</span></div></>
    ),
    c3: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>{t('dashboard.widgets.dataCompleteness')}</span><span>78%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'78%',background:'var(--color-blue)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>{t('dashboard.widgets.completionRate')}</span><span>22%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'22%',background:'var(--color-warning)'}} /></div></div>
      </div>
    ),
    c4: () => {
      const recent = touchpoints.slice(0, 3)
      return recent.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('common.noResults')}</div>
        : <>{recent.map(tp => (
            <div key={tp.id} className="list-row"><span className="name">{tp.title}</span><span className="meta">{tp.company?.name || tp.type}</span></div>
          ))}</>
    },
    c5: () => {
      // Source distribution — derived from real contact/company data (top industries)
      const g = (k?: string) => k || '其他'
      const dist = new Map<string, number>()
      contacts.forEach(c => { const key = g(c.company?.name); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      const total = contacts.length || 1
      if (top.length === 0) {
        return <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('contacts.empty')}</div>
      }
      return (
        <div style={{display:'flex',flexDirection:'column',gap:10}}>
          {top.map(([k, n], i) => (
            <div key={k} className="stage-row"><div className="stage-label"><span>{k}</span><span>{n}</span></div><div className="bar-track"><div className="bar-fill" style={{width:`${Math.round((n / total) * 100)}%`,background: i === 0 ? 'var(--color-blue)' : i === 1 ? 'var(--color-purple)' : 'var(--color-success)'}} /></div></div>
          ))}
        </div>
      )
    },
    // ── Companies (demo data) ──
    co1: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{color:'var(--color-purple)'}}>{stats.companies}</span>
        <span style={{fontSize:12,color:'var(--color-text-muted)',fontWeight:500}}>{t('dashboard.widgets.totalCustomers')}</span>
      </div>
    ),
    co2: () => {
      const g = (k?: string) => k || '未分類'
      const dist = new Map<string, number>()
      companyList.forEach(c => { const key = g(c.category || c.industry); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3)
      const total = companyList.length || 1
      return top.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('companies.empty')}</div>
        : (<div style={{display:'flex',flexDirection:'column',gap:10}}>
            {top.map(([k, n]) => (
              <div key={k} className="stage-row"><div className="stage-label"><span>{k}</span><span>{n}</span></div><div className="bar-track"><div className="bar-fill" style={{width:`${Math.round((n / total) * 100)}%`,background:'var(--color-blue)'}} /></div></div>
            ))}
          </div>)
    },
    co3: () => {
      const items = companyList.slice(0, 3)
      return items.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('companies.empty')}</div>
        : <>{items.map(c => (
            <div key={c.id} className="list-row"><span className="name">{c.name}</span><span className="badge info">{c.industry || c.category || '—'}</span></div>
          ))}</>
    },
    co4: () => (
      <><div className="list-row"><span className="name">旭輝空運</span><span className="meta">92分</span></div>
      <div className="list-row"><span className="name">深圳華良物流</span><span className="meta">85分</span></div>
      <div className="list-row"><span className="name">深圳絆強物流</span><span className="meta">76分</span></div>
      <div className="list-row"><span className="name">深圳弘安國際</span><span className="meta">63分</span></div></>
    ),
    co5: () => {
      const g = (k?: string) => k || '未分類'
      const dist = new Map<string, number>()
      companyList.forEach(c => { const key = g(c.industry || c.category); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      const total = companyList.length || 1
      if (top.length === 0) {
        return <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('companies.empty')}</div>
      }
      return (
        <div style={{display:'flex',flexDirection:'column',gap:10}}>
          {top.map(([k, n], i) => (
            <div key={k} className="stage-row"><div className="stage-label"><span>{k}</span><span>{n}</span></div><div className="bar-track"><div className="bar-fill" style={{width:`${Math.round((n / total) * 100)}%`,background: i === 0 ? 'var(--color-purple)' : i === 1 ? 'var(--color-blue)' : 'var(--color-success)'}} /></div></div>
          ))}
        </div>
      )
    },
    // ── Deals (demo data) ──
    d1: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{color:'var(--color-primary)'}}>{stats.dealValue || '—'}</span>
        <span style={{fontSize:12,color:'var(--color-text-muted)',fontWeight:500}}>{t('dashboard.widgets.dealTotal')}</span>
      </div>
    ),
    d2: () => {
      const allStageKeys = ['qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost']
      const stageData = allStageKeys.map(k => {
        const items = deals.filter(d => d.stage_id === k)
        return {
          key: k, label: stages[k]?.label || k, count: items.length,
          total: items.reduce((s, d) => s + (d.amount || 0), 0),
          color: stages[k]?.color || 'var(--color-primary)',
        }
      })
      const maxTotal = Math.max(1, ...stageData.map(s => s.total))
      return (
        <div style={{display:'flex',flexDirection:'column',gap:10}}>
          {stageData.map(s => (
            <div key={s.key} className="stage-row">
              <div className="stage-label">
                <span>{s.label}</span>
                <span>${s.total.toLocaleString()}</span>
              </div>
              <div className="bar-track">
                <div className="bar-fill" style={{width:`${(s.total/maxTotal)*100}%`,background:s.color}} />
              </div>
            </div>
          ))}
        </div>
      )
    },
    d3: () => (
      <><div className="list-row"><span className="name">深圳快豹跨境物流</span><span className="meta">18日無更新</span></div>
      <div className="list-row"><span className="name">深圳一站物流</span><span className="meta">21日無更新</span></div>
      <div className="list-row"><span className="name">深圳華良物流集團</span><span className="meta">16日無更新</span></div></>
    ),
    d4: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="kpi-row" style={{justifyContent:'center',marginTop:8}}>
          <span className="kpi-val" style={{color:'var(--color-primary)'}}>68%</span>
        </div>
        <div className="bar-track" style={{height:12}}><div className="bar-fill" style={{width:'68%',background:'var(--color-primary)'}} /></div>
        <div className="kpi-delta down" style={{textAlign:'center'}}>{t('dashboard.widgets.monthlyTarget')} $4.7M · {t('dashboard.widgets.completed')} $3.2M</div>
      </div>
    ),
    d5: () => (
      <><div className="list-row"><span className="name">深圳絆強物流 — 首年合約</span><span className="badge ok">$86k</span></div>
      <div className="list-row"><span className="name">旭輝空運 — 擴充服務</span><span className="badge ok">$52k</span></div>
      <div className="list-row"><span className="name">深圳弘安國際 — 續約</span><span className="badge ok">$38k</span></div></>
    ),
    // ── Projects (demo data) ──
    p1: () => (
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'center',flexDirection:'column',gap:6,height:'100%',paddingLeft:8}}>
        <span className="kpi-val" style={{color:'var(--color-primary)'}}>{projectsTotal}</span>
        <span style={{fontSize:12,color:'var(--color-text-muted)',fontWeight:500}}>{t('dashboard.widgets.inProgress')}</span>
      </div>
    ),
    p2: () => {
      const items = (projects || []).slice(0, 3)
      return items.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('project.empty')}</div>
        : <>{items.map(p => (
            <div key={p.id} className="list-row" style={{cursor:'pointer'}} onClick={() => navigate(`/projects/${p.id}`)}><span className="name">{p.name || p.title}</span><span className="badge info">{p.status || '—'}</span></div>
          ))}</>
    },
    p3: () => {
      const statusColor = (s: string) => {
        if (s === 'done' || s === 'completed') return 'var(--color-success)'
        if (s === 'in_progress' || s === 'active') return 'var(--color-blue)'
        if (s === 'planning' || s === 'new') return 'var(--color-text-faint)'
        return 'var(--color-warning)'
      }
      const statusLabel = (s: string) => {
        if (s === 'done' || s === 'completed') return '✅ ' + t('status.completed')
        if (s === 'in_progress' || s === 'active') return '▶ ' + t('status.active')
        if (s === 'planning' || s === 'new') return '📋 ' + t('pages.tasks.inProgress')
        if (s === 'on_hold') return '⏸ ' + t('status.pending')
        return s || '—'
      }
      const items = (projects || []).slice(0, 5)
      return items.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('project.empty')}</div>
        : <div style={{display:'flex',flexDirection:'column',gap:10}}>{items.map((p: any) => (
            <div key={p.id} className="stage-row" style={{cursor:'pointer'}} onClick={() => navigate(`/projects/${p.id}`)}>
              <div className="stage-label">
                <span>{p.name}</span>
                <span style={{color:statusColor(p.status),fontSize:12}}>{statusLabel(p.status)}</span>
              </div>
            </div>
          ))}</div>
    },
    p4: () => {
      const items = (projects || []).slice(0, 4)
      if (items.length === 0) {
        return <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('project.empty')}</div>
      }
      return (
        <div style={{display:'flex',flexDirection:'column',gap:10}}>
          {items.map((p: any) => (
            <div key={p.id} className="list-row" style={{cursor:'pointer'}} onClick={() => navigate(`/projects/${p.id}`)}>
              <span className="name">{p.name || p.title}</span>
              <span className="meta">{p.status || '—'}</span>
            </div>
          ))}
        </div>
      )
    },
    // ── Tasks (demo data) ──
    t1: () => {
      const todayTasks = tasks.filter(t => {
        if (t.status === 'done') return false
        if (t.area?.includes('Work') || t.area?.includes('💼')) return true
        return t.priority === 'P0'
      }).slice(0, 5)
      return todayTasks.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('tasks.empty')}</div>
        : <>{todayTasks.map(t => (
            <div key={t.id} className="list-row" style={{cursor:'pointer'}} onClick={() => navigate(`/tasks/${t.id}`)}>
              <SvcIcon name="check-square" size={14} style={{color:t.status==='done'?'var(--color-success)':'var(--color-text-muted)',flexShrink:0}} />
              <span className="name">{t.title}</span>
              <span className="badge" style={{
                background: t.priority==='P0'?'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))':t.priority==='P1'?'color-mix(in oklch,var(--color-warning)18%,var(--color-surface))':'color-mix(in oklch,var(--color-success)18%,var(--color-surface))',
                color: t.priority==='P0'?'var(--color-notification)':t.priority==='P1'?'var(--color-warning)':'var(--color-success)'
              }}>{t.custom_fields?.notion_priority || t.priority || 'P3'}</span>
            </div>
          ))}</>
    },
    t2: () => {
      const overdueTasks = tasks.filter(t => t.due_date && new Date(t.due_date) < new Date() && t.status !== 'done').slice(0, 5)
      const daysOverdue = (due: string) => Math.floor((Date.now() - new Date(due).getTime()) / (86400000))
      return overdueTasks.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('tasks.empty')}</div>
        : <>{overdueTasks.map(task => (
            <div key={task.id} className="list-row" style={{cursor:'pointer'}} onClick={() => navigate(`/tasks/${task.id}`)}>
              <span className="name">{task.title}</span>
              <span className="badge warn">{t('dashboard.widgets.overdue')}{t('common.days', { count: daysOverdue(task.due_date!) })}</span>
            </div>
          ))}</>
    },
    t3: () => {
      const priorityOrder: Record<string, number> = { 'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4 }
      const sortedTasks = [...tasks].sort((a, b) => {
        const pa = priorityOrder[a.priority] ?? 99
        const pb = priorityOrder[b.priority] ?? 99
        return pa - pb
      }).slice(0, 5)
      const priorityLabel = (p: string) => {
        if (p === 'P0') return t('priority.urgent')
        if (p === 'P1') return t('priority.high')
        if (p === 'P2') return t('priority.medium')
        return t('priority.low')
      }
      const priorityBadgeClass = (p: string) => {
        if (p === 'P0' || p === 'P1') return 'warn'
        if (p === 'P2') return 'info'
        return 'ok'
      }
      return sortedTasks.length === 0
        ? <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('pages.tasks.empty')}</div>
        : <>{sortedTasks.map(t => (
            <div key={t.id} className="list-row" style={{cursor:'pointer'}} onClick={() => navigate(`/tasks/${t.id}`)}>
              <span className="name">{t.title}</span>
              <span className={`badge ${priorityBadgeClass(t.priority)}`}>{priorityLabel(t.priority)}</span>
            </div>
          ))}</>
    },
    t4: () => {
      const total = tasks.length
      const done = tasks.filter(t => t.status === 'done' || t.status === 'completed').length
      const rate = total > 0 ? Math.round((done / total) * 100) : 0
      return (
        <div style={{display:'flex',flexDirection:'column',gap:10,alignItems:'center',justifyContent:'center',height:'100%'}}>
          <span className="kpi-val" style={{color:'var(--color-success)'}}>{rate}%</span>
          <div className="bar-track" style={{width:'100%'}}><div className="bar-fill" style={{width:`${rate}%`,background:'var(--color-success)'}} /></div>
          <span style={{fontSize:12,color:'var(--color-text-muted)'}}>{done}/{total} {t('tasks.title').toLowerCase()} {t('status.completed')}</span>
        </div>
      )
    },
    // ── Calendar (real data) ──
    cal1: () => {
      const evts: any[] = calendarEvents && calendarEvents.length ? calendarEvents : []
      if (!evts.length) {
        return (
          <div style={{display:'flex',flexDirection:'column',gap:10,alignItems:'center',justifyContent:'center',height:'100%',color:'var(--color-text-muted)',fontSize:13}}>
            {t('dashboard.widgets.noEvents')}
          </div>
        )
      }
      const fmtTime = (iso: string) => {
        const d = new Date(iso)
        return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
      }
      return (
        <>{evts.map((e: any, i: number) => (
          <div className="list-row" key={i}><SvcIcon name="calendar" size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">{fmtTime(e.start)} {e.title}</span><span className="meta">{e.event_type || ''}</span></div>
        ))}</>
      )
    },
    cal2: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>週一</span><span>3h</span></div><div className="bar-track"><div className="bar-fill" style={{width:'60%',background:'var(--color-blue)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>週二</span><span>4.5h</span></div><div className="bar-track"><div className="bar-fill" style={{width:'90%',background:'var(--color-purple)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>週三</span><span>2h</span></div><div className="bar-track"><div className="bar-fill" style={{width:'40%',background:'var(--color-success)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>週四</span><span>1.5h</span></div><div className="bar-track"><div className="bar-fill" style={{width:'30%'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>週五</span><span>3h</span></div><div className="bar-track"><div className="bar-fill" style={{width:'60%',background:'var(--color-warning)'}} /></div></div>
      </div>
    ),
    cal3: () => (
      <><div className="list-row"><span className="name">09:00-12:00 旭輝空運拜訪</span><span className="meta">週四</span></div>
      <div className="list-row"><span className="name">14:00-16:00 深圳華良</span><span className="meta">週五</span></div>
      <div className="list-row"><span className="name">10:00-12:00 弘安國際</span><span className="meta">下週一</span></div></>
    ),
    // ── Shipping (demo data) ──
    s1: () => (
      <><div className="list-row"><Truck size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">深圳絆強物流</span><span className="meta">{t('status.pending')}</span></div>
      <div className="list-row"><Truck size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">深圳弘安國際</span><span className="badge warn">{t('dashboard.widgets.overdue')}</span></div>
      <div className="list-row"><Truck size={14} style={{color:'var(--color-text-muted)',flexShrink:0}} /><span className="name">深圳兴安通达</span><span className="meta">{t('status.pending')}</span></div></>
    ),
    s2: () => (
      <><div className="list-row"><span className="name">深圳弘安國際 — HKG-SZX</span><span className="badge warn">{t('filter.active')}48h</span></div>
      <div className="list-row"><span className="name">深圳絆強物流 — HKG-NGB</span><span className="badge warn">{t('filter.active')}24h</span></div>
      <div className="list-row"><span className="name" style={{color:'var(--color-text-faint)'}}>其他訂單正常</span></div></>
    ),
    s3: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>{t('dashboard.widgets.inProgress')}</span><span>62%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'62%'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>{t('status.completed')}</span><span>28%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'28%',background:'var(--color-success)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>{t('status.pending')}</span><span>10%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'10%',background:'var(--color-warning)'}} /></div></div>
      </div>
    ),
    s4: () => (
      <><div className="list-row"><span className="name">HKG-SZX</span><span className="badge ok">98%</span></div>
      <div className="list-row"><span className="name">HKG-NGB</span><span className="badge ok">92%</span></div>
      <div className="list-row"><span className="name">HKG-PVG</span><span className="badge info">85%</span></div>
      <div className="list-row"><span className="name">HKG-PEK</span><span className="badge warn">74%</span></div></>
    ),
    s5: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="kpi-row" style={{justifyContent:'center'}}>
          <span className="kpi-val" style={{color:'var(--color-primary)',fontSize:22}}>$124.5K</span>
        </div>
        <div className="stage-row"><div className="stage-label"><span>本月預算</span><span>$180K</span></div><div className="bar-track"><div className="bar-fill" style={{width:'69%',background:'var(--color-blue)'}} /></div></div>
        <div className="kpi-delta up">↑ 8% vs 上月</div>
      </div>
    ),
    // ── Team (demo data) ──
    te1: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>林海珊</span><span>120%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'100%',background:'var(--color-warning)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>陳偉明</span><span>85%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'85%',background:'var(--color-blue)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>張志強</span><span>70%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'70%'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>李美玲</span><span>55%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'55%',background:'var(--color-success)'}} /></div></div>
      </div>
    ),
    te2: () => (
      <div style={{display:'flex',flexDirection:'column',gap:8}}>
        <div className="kpi-row"><span className="kpi-val" style={{fontSize:22}}>4/6</span><span className="kpi-delta up" style={{marginLeft:6}}>{t('status.active')}</span></div>
        <div className="list-row" style={{marginTop:4}}><span className="name">林海珊</span><span className="badge ok">{t('status.active')}</span></div>
        <div className="list-row"><span className="name">陳偉明</span><span className="badge ok">{t('status.active')}</span></div>
        <div className="list-row"><span className="name">張志強</span><span className="meta">{t('status.inactive')}</span></div>
        <div className="list-row"><span className="name">李美玲</span><span className="badge ok">{t('status.active')}</span></div>
      </div>
    ),
    te3: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>團隊平均</span><span>78%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'78%',background:'var(--color-blue)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>林海珊</span><span>92%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'92%',background:'var(--color-success)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>陳偉明</span><span>76%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'76%'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>張志強</span><span>65%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'65%',background:'var(--color-warning)'}} /></div></div>
      </div>
    ),
    te4: () => (
      <><div className="list-row"><span className="name">🥇 林海珊</span><span className="meta">$186K</span></div>
      <div className="list-row"><span className="name">🥈 陳偉明</span><span className="meta">$142K</span></div>
      <div className="list-row"><span className="name">🥉 張志強</span><span className="meta">$98K</span></div>
      <div className="list-row"><span className="name">李美玲</span><span className="meta">$67K</span></div></>
    ),
    // ── Business (demo data) ──
    b1: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="list-row"><span className="name">{t('deals.pipeline')}</span><span className="badge info">Professional</span></div>
        <div className="list-row"><span className="name">{t('pages.companies.status')}</span><span className="badge ok">{t('status.active')}</span></div>
        <div className="list-row"><span className="name">{t('tasks.dueDate')}</span><span className="meta">2026-12-31</span></div>
        <div className="list-row"><span className="name">{t('dashboard.widgets.systemUsage')}</span><span className="meta">67%</span></div>
      </div>
    ),
    b2: () => (
      <div style={{display:'flex',flexDirection:'column',gap:10}}>
        <div className="stage-row"><div className="stage-label"><span>API {t('dashboard.widgets.systemUsage')}</span><span>45%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'45%',background:'var(--color-blue)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>{t('project.description')}</span><span>32%</span></div><div className="bar-track"><div className="bar-fill" style={{width:'32%',background:'var(--color-success)'}} /></div></div>
        <div className="stage-row"><div className="stage-label"><span>{t('touchpoint.title')}</span><span>12/20</span></div><div className="bar-track"><div className="bar-fill" style={{width:'60%'}} /></div></div>
      </div>
    ),
    ask_ai: () => <WidgetAskAI />,
  }

  // Widget icon helper
  const widgetIcon = (k: string) => {
    if (k.startsWith('kpi_') || k === 'pipeline' || k.startsWith('d')) return TrendingUp
    if (k.startsWith('c')) return Users
    if (k.startsWith('co')) return Building2
    if (k.startsWith('p')) return FolderKanban
    if (k === 'tasks' || k.startsWith('t')) return CheckSquare
    if (k.startsWith('cal')) return Calendar
    if (k.startsWith('s')) return Truck
    if (k.startsWith('te')) return UsersRound
    if (k.startsWith('b')) return Activity
    if (k === 'touchpoints') return Activity
    if (k === 'dealvalue') return DollarSign
    if (k === 'aiinsight') return Sparkles
    if (k === 'ask_ai') return Sparkles
    if (k === 'activity_feed') return Activity
    return LayoutDashboard
  }

  const iconColor = (k: string) => {
    if (k.startsWith('c')) return 'var(--color-blue)'
    if (k.startsWith('co')) return 'var(--color-purple)'
    if (k.startsWith('d')) return 'var(--color-primary)'
    if (k.startsWith('p')) return 'var(--color-warning)'
    if (k === 'tasks' || k.startsWith('t')) return 'var(--color-success)'
    if (k.startsWith('cal')) return 'var(--color-blue)'
    if (k.startsWith('s')) return 'var(--color-primary)'
    if (k.startsWith('te')) return 'var(--color-purple)'
    if (k.startsWith('b')) return 'var(--color-warning)'
    return 'var(--color-text-muted)'
  }

  return (
    <div className={`dash01-shell${editing ? ' editing' : ''}`}>
      {/* Toolbar — dashboard-specific controls */}
      <div className="dash-toolbar" style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:18,flexWrap:'wrap',gap:10}}>
        <div>
          <h1 className="greeting-title">{t(`greeting.${hktGreetingKey()}`, { name: user?.displayName || user?.email?.split('@')[0] || '' })}</h1>
          <p style={{fontSize:13,color:'var(--color-text-muted)',marginTop:2}}>{todayStr(i18n.language)}</p>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:8}}>
          <div className="new-menu-wrap" ref={newRef} style={{position:'relative'}}>
            <button className="new-btn" aria-label="Create new" onClick={() => setNewOpen(!newOpen)}>
              <SvcIcon name="plus" size={20} />
            </button>
            {newOpen && (
              <div style={{position:'absolute',top:'calc(100% + 8px)',right:0,width:200,background:'var(--color-surface-2)',border:'1px solid var(--color-border)',borderRadius:'var(--radius-lg)',boxShadow:'var(--shadow-lg)',padding:6,zIndex:50}}>
                <button className="new-dropdown-item" onClick={() => { setNewOpen(false); navigate('/tasks') }}
                  style={{display:'flex',alignItems:'center',gap:10,padding:'9px 10px',borderRadius:'var(--radius-sm)',fontSize:13.5,fontWeight:500,width:'100%',textAlign:'left',color:'var(--color-text)',background:'none',border:'none',cursor:'pointer'}}>
                  <SvcIcon name="check-square" size={16} style={{color:'var(--color-text-muted)'}} />{t('tasks.new')}
                </button>
                <button className="new-dropdown-item" onClick={() => { setNewOpen(false); navigate('/contacts') }}
                  style={{display:'flex',alignItems:'center',gap:10,padding:'9px 10px',borderRadius:'var(--radius-sm)',fontSize:13.5,fontWeight:500,width:'100%',textAlign:'left',color:'var(--color-text)',background:'none',border:'none',cursor:'pointer'}}>
                  <SvcIcon name="users" size={16} style={{color:'var(--color-text-muted)'}} />{t('contacts.new')}
                </button>
                <button className="new-dropdown-item" onClick={() => { setNewOpen(false); navigate('/companies') }}
                  style={{display:'flex',alignItems:'center',gap:10,padding:'9px 10px',borderRadius:'var(--radius-sm)',fontSize:13.5,fontWeight:500,width:'100%',textAlign:'left',color:'var(--color-text)',background:'none',border:'none',cursor:'pointer'}}>
                  <SvcIcon name="building-2" size={16} style={{color:'var(--color-text-muted)'}} />{t('companies.new')}
                </button>
              </div>
            )}
          </div>
          <button className={`btn ${editing ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setEditing(!editing)}
            title={editing ? t('common.done') : t('dashboard.editMode')}
            style={{display:'inline-flex',alignItems:'center',justifyContent:'center',gap:6,width:36,height:36,padding:0,borderRadius:'var(--radius-md)',fontSize:13.5,fontWeight:600,cursor:'pointer',background: editing ? 'var(--color-primary)' : 'var(--color-surface-offset)',color: editing ? '#fff' : 'var(--color-text)'}}>
            <Layout size={15} />
          </button>
        </div>
      </div>

      {/* AI Daily Brief — compact trigger + drawer (V2) */}
      <div className={aiOn ? '' : 'hidden'} style={aiOn ? {} : { display: 'none' }}>
        <AIBriefingDrawer />
      </div>

      {/* WIDGET GRID — CSS grid, 12-column, span classes.
          className="grid" is REQUIRED: dashboard.css + design4-v2-patch.css
          mobile media queries target `.dash01-shell .grid` — without it,
          KPI `span 1 !important` collapses cards to 1/12 width on mobile. */}
      {layoutReady && (
      <div ref={gridRef} className="grid" style={{display:'grid',gap:16,alignItems:'start'}}>
        {order.map((k) => {
          if (HIDDEN_WIDGETS.has(k)) return null
          const def = allWidgets[k]
          if (!def) return null
          const IconComp = widgetIcon(k)
          // KPI stat cards: 2-per-row squares in compact mode (half-width span 6
          // + 1:1 aspect). Desktop keeps the same 2-per-row layout.
          // Phones (≤640px): single-column grid — drop the inline 1:1 aspect so
          // the CSS `aspect-ratio: auto` wins and cards render full-width, not
          // giant squares.
          const isKpi = k.startsWith('kpi_')
          const wLv = wLevels[k]
          const hLv = hLevels[k]
          // user-resized: span from width level; height from aspect ratio w/h (n,n) = square
          const effSpan = wLv ? SPAN_BY_LEVEL[wLv] : (isKpi && isCompact ? 6 : def.span)
          const kpiSquare = isKpi && isCompact && !isPhone && !wLv
          // Fix (mobile): on phones (≤640px) ignore any saved inline aspect ratio so
          // all widgets render full-width like the other KPI cards — a persisted
          // widgetLevels entry on kpi_contacts previously forced a 1:1 square
          // that inline style (which wins over the CSS media-query aspect) kept.
          const aspect = !isPhone && (wLv && hLv) ? `${wLv} / ${hLv}` : (kpiSquare ? '1 / 1' : undefined)
          return (
            <div key={k} className={`widget${editing && dragKey.current === k ? ' dragging' : ''}`}
              style={{gridColumn:`span ${effSpan}`,aspectRatio: aspect,background:'var(--color-surface-2)',border: editing ? '2px dashed var(--color-primary)' : '1px solid var(--color-border)',borderRadius:'var(--radius-lg)',padding:16,display:'flex',flexDirection:'column',position:'relative',minHeight:isKpi && isCompact ? 0 : 160,transition:'grid-column .12s ease, aspect-ratio .12s ease',cursor: editing ? 'grab' : undefined}}
              data-key={k}
              draggable={editing}
              onDragStart={() => handleDragStart(k)}
              onDragOver={e => handleDragOver(e, k)}
              onDragEnd={handleDragEnd}>
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:12,flexShrink:0}}>
                <h3 style={{fontSize:13.5,fontWeight:700,margin:0,display:'flex',alignItems:'center',gap:6}}>
                  <IconComp size={15} style={{color: iconColor(k)}} />
                  {k.startsWith('kpi_') ? t(widgetLabelKey[k] || def.label) :
                   k === 'tasks' ? <>{t(widgetLabelKey[k])} <span className="badge" style={{padding:'2px 8px',borderRadius:'999px',fontSize:11,fontWeight:700,background:'color-mix(in oklch,var(--color-primary)18%,var(--color-surface))',color:'var(--color-primary)'}}>{stats.tasks}</span></> :
                   k === 'touchpoints' ? t('touchpoint.title') :
                   k === 'pipeline' ? t('dashboard.widgets.pipeline') :
                   k === 'dealvalue' ? <><DollarSign size={15} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.dealTotal')}</> :
                   k === 'aiinsight' ? <><SvcIcon name="sparkles" size={15} style={{color:'var(--color-purple)'}} /> AI Insight</> :
                   k === 'activity_feed' ? <><SvcIcon name="activity" size={15} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.recentActivity')}</> :
                   widgetLabelKey[k] ? t(widgetLabelKey[k]) : def.label}
                </h3>
                {editing && (
                  <div style={{display:'flex',gap:2}}>
                    <button aria-label={t('greeting.moveUp')} className="widget-icon-btn" title={t('greeting.moveUp')} onClick={(e) => { e.stopPropagation(); moveW(k, -1) }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
                    </button>
                    <button aria-label={t('greeting.moveDown')} className="widget-icon-btn" title={t('greeting.moveDown')} onClick={(e) => { e.stopPropagation(); moveW(k, 1) }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6"/></svg>
                    </button>
                    <button aria-label={t('greeting.drag')} className="widget-icon-btn" title={t('greeting.drag')}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="9" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="18" r="1"/></svg>
                    </button>
                    <button aria-label={t('greeting.remove')} onClick={(e) => { e.stopPropagation(); removeW(k) }} className="widget-icon-btn" title={t('greeting.remove')}>
                      <SvcIcon name="x" size={14} />
                    </button>
                  </div>
                )}
              </div>
              <div className="widget-body" style={{flex:1,minHeight:0}}>
                {widgetBodies[k] ? widgetBodies[k]() : (
                  <div style={{padding:'16px 0',fontSize:12,color:'var(--color-text-faint)'}}>{t('common.noData')}</div>
                )}
              </div>
              {(k === 'c1' || k === 'co3' || k === 't2' || k === 's2' || k === 'te1') && aiOn && (
                <button className="ai-tag" style={{display:'inline-flex',alignItems:'center',gap:5,padding:'5px 10px',borderRadius:'999px',background:'var(--color-purple-highlight)',color:'var(--color-purple)',fontSize:11.5,fontWeight:700,marginTop:8,border:'none',cursor:'pointer'}}
                  onClick={() => window.dispatchEvent(new CustomEvent('toggle-ai-chat'))}>
                  <SvcIcon name="sparkles" size={12} />AI advise
                </button>
              )}
              {editing && (
                <div className="resize-grip" style={{position:'absolute',bottom:4,right:4,cursor:'nwse-resize',color:'var(--color-primary)',opacity:0.8,zIndex:5,userSelect:'none',background:'var(--color-surface-2)',borderRadius:'4px',padding:2,display:'flex',alignItems:'center',justifyContent:'center',width:20,height:20,boxShadow:'0 1px 3px rgba(0,0,0,0.15)'}}
                  draggable={false}
                  onMouseDown={(e) => {
                    e.preventDefault(); e.stopPropagation()
                    const startX = e.clientX, startY = e.clientY
                    const grid = gridRef.current
                    const gripEl = e.currentTarget as HTMLElement
                    const widgetEl = gripEl.closest('[data-key]') as HTMLElement
                    if (!grid || !widgetEl) return
                    const startSpanNum = parseInt(widgetEl.style.gridColumn.match(/span (\d+)/)?.[1] || String(def.span))
                    const gridRect = grid.getBoundingClientRect()
                    const gapVal = 16
                    const colW = (gridRect.width - (11 * gapVal)) / 12
                    // current size levels (resized value, or map default → level)
                    let curWLv = wLevels[k] ?? levelOf(startSpanNum, SPAN_BY_LEVEL)
                    let curHLv = hLevels[k] ?? 1
                    // Drag tooltip showing (width level, height level)
                    const tip = document.createElement('div')
                    tip.style.cssText = 'position:absolute;bottom:28px;right:0;font-size:11px;font-weight:600;color:var(--color-primary);background:var(--color-surface-2);border:1px solid var(--color-border);padding:2px 8px;border-radius:6px;pointer-events:none;z-index:6'
                    tip.textContent = `(${curWLv},${curHLv})`
                    gripEl.appendChild(tip)
                    const onMove = (ev: MouseEvent) => {
                      const dx = ev.clientX - startX, dy = ev.clientY - startY
                      // width snaps to nearest size level (指定 size 1–7)
                      const rawSpan = startSpanNum + dx / (colW + gapVal)
                      const snappedSpan = snapToLevel(rawSpan, SPAN_BY_LEVEL)
                      const newWLv = levelOf(snappedSpan, SPAN_BY_LEVEL)
                      if (newWLv !== curWLv) {
                        curWLv = newWLv
                        widgetEl.style.gridColumn = `span ${snappedSpan}`
                        widgetEl.style.aspectRatio = `${curWLv} / ${curHLv}`
                      }
                      // height snaps to nearest level — aspect ratio (w/h) keeps
                      // (n,n) square at ANY viewport width.
                      // Base on the LEVEL's px (160/200/…), NOT rendered height —
                      // aspect-ratio height can be huge, which made any small dy
                      // jump straight to level 7.
                      const baseH = HEIGHT_BY_LEVEL[curHLv]
                      const rawH = baseH + dy
                      const newHLv = levelOf(rawH, HEIGHT_BY_LEVEL)
                      if (newHLv !== curHLv) {
                        curHLv = newHLv
                        widgetEl.style.aspectRatio = `${curWLv} / ${curHLv}`
                      }
                      tip.textContent = `(${curWLv},${curHLv})`
                    }
                    const onUp = () => {
                      document.removeEventListener('mousemove', onMove)
                      document.removeEventListener('mouseup', onUp)
                      tip.remove()
                      // Commit levels into state so it persists (save effect writes it)
                      setWLevels(prev => ({ ...prev, [k]: curWLv }))
                      setHLevels(prev => ({ ...prev, [k]: curHLv }))
                    }
                    document.addEventListener('mousemove', onMove)
                    document.addEventListener('mouseup', onUp)
                  }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12L12 22M22 2L2 22"/></svg>
                </div>
              )}
            </div>
          )
        })}
        {/* Add Widget Tile — opens drawer */}
        {editing && (
          <div className="add-widget-tile"
            style={{gridColumn:'span 4',border:'1.5px dashed var(--color-border)',borderRadius:'var(--radius-lg)',minHeight:160,display:'flex',alignItems:'center',justifyContent:'center',flexDirection:'column',gap:8,color:'var(--color-text-muted)',cursor:'pointer'}}
            onClick={() => setDrawerOpen(true)}>
            <SvcIcon name="plus" size={24} />
            <span style={{fontSize:13,fontWeight:600}}>{t('dashboard.addWidget')}</span>
          </div>
        )}
      </div>
      )}

      {aiOn && (
        <div className="ai-tag" onClick={() => window.dispatchEvent(new CustomEvent('toggle-ai-chat'))} style={{display:'inline-flex',alignItems:'center',gap:5,padding:'5px 10px',borderRadius:'999px',background:'var(--color-purple-highlight)',color:'var(--color-purple)',fontSize:11.5,fontWeight:700,marginTop:10,border:'none',cursor:'pointer'}}>
          <SvcIcon name="sparkles" size={12} /> {t('chat.title')}
        </div>
      )}


      {/* ── DRAWER (Widget Picker) — outside .content to avoid overflow clip ── */}
      <div className={`drawer-overlay${drawerOpen ? ' show' : ''}`} onClick={() => setDrawerOpen(false)} />
      <aside className={`drawer${drawerOpen ? ' show' : ''}`}>
        <div className="drawer-head">
          <h3>{t('dashboard.addWidget')}</h3>
          <button className="icon-btn" onClick={() => setDrawerOpen(false)}><SvcIcon name="x" size={19} /></button>
        </div>
        <div className="drawer-search">
          <input type="text" placeholder={t('common.search') + '...'} value={widgetSearch}
            onChange={e => setWidgetSearch(e.target.value)} />
        </div>
        <div className="drawer-body">
          {modulesData.filter(mod => {
            if (!widgetSearch) return true
            const q = widgetSearch.toLowerCase()
            return mod.widgets.some(w => w.name.includes(q) || w.desc.includes(q))
          }).map(mod => {
            const visible = widgetSearch
              ? mod.widgets.filter(w => w.name.includes(widgetSearch.toLowerCase()) || w.desc.includes(widgetSearch.toLowerCase()))
              : mod.widgets
            if (widgetSearch && visible.length === 0) return null
            // Skip groups that have no visible (non-hidden) widgets left
            const addable = visible.filter(w => !order.includes(w.key) && !HIDDEN_WIDGETS.has(w.key))
            const added = visible.filter(w => order.includes(w.key) && !HIDDEN_WIDGETS.has(w.key))
            if (addable.length === 0 && added.length === 0) return null
            return (
              <div key={mod.id} className="module-group">
                <div className="module-group-head"><span>{t('nav.' + mod.id)}</span></div>
                {addable.map(w => {
                  const IconComp = widgetIcon(w.key)
                  return (
                    <div key={w.key} className="widget-option" onClick={() => {
                      addWidget(w.key)
                      setWidgetSearch('')
                    }}>
                      <div className="wo-icon"><IconComp size={15} /></div>
                      <div className="wo-text"><strong>{widgetLabelKey[w.key] ? t(widgetLabelKey[w.key]) : w.name}</strong><span>{t('dashboard.noData')}</span></div>
                      <div className="wo-add"><SvcIcon name="plus" size={14} /></div>
                    </div>
                  )
                })}
                {added.length > 0 && (
                  <div style={{padding:'4px 8px',fontSize:11.5,color:'var(--color-text-faint)'}}>
                    {added.map(w => widgetLabelKey[w.key] ? t(widgetLabelKey[w.key]) : w.name).join('、')} — {t('common.done')}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </aside>
      {/* ── Detail Drawer ── */}
      <SlideDrawer open={detailDrawer} onClose={() => setDetailDrawer(false)} title={drawerTitle} width="30vw">
        {drawerContent}
      </SlideDrawer>
    </div>
  )
}

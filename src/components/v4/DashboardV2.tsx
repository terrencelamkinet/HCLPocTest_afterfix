import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Percent } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import { useToast } from './useToast'
import { sectionIcon, sectionRouteWithItemFallback } from './briefingRoutes'
import WidgetAskAI from '../WidgetAskAI'

/* ═══════════════════════════════════════════════════════════
   DashboardV2 — AI-integrated, fully-interactive widget grid.

   GRID MATH (audited — no wasted space, no forced wraps):
     Row 1: AI(span6)   + Stat(span3) + Stat(span3)     = 12
     Row 2: Stat(span3) + Stat(span3) + List(span6)     = 12
     Row 3: List(span6) + List(span6)                    = 12
     Row 4: Table(span12)                                 = 12
   Default DOM order below is intentional: AI, 4×Stat, 3×List, Table.
   In customize mode the user can drag to reorder — CSS grid auto-flows
   spans per widget class, so reordering never breaks the packing.

   Every button below has a real handler + visible feedback
   (toast / modal / drawer / inline expand / checkbox state).
   ═══════════════════════════════════════════════════════════ */

interface Stats { contacts: number; companies: number; tasksDue: number; dealsOpen?: number; dealsValue?: number }
interface AiSection { header: string; items: string[] }
interface AiInsight { headline: string; sections: AiSection[]; slot?: string; generatedAt?: string; source: 'generated' | 'fallback' }
interface Todo { id: string; title: string; priority: number; due_time?: string; done?: boolean }

// ── IM markdown briefing → portal sections (system auto-applies portal style) ──
function parseBriefing(content: string): { title: string; sections: AiSection[] } {
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean)
  const title = lines[0] || ''
  const sections: AiSection[] = []
  let cur: AiSection | null = null
  for (const line of lines.slice(1)) {
    if (line.startsWith('**') && line.endsWith('**')) {
      cur = { header: line.replace(/\*\*/g, ''), items: [] }
      sections.push(cur)
    } else if (line.startsWith('- ') || line.startsWith('• ')) {
      if (!cur) { cur = { header: '', items: [] }; sections.push(cur) }
      cur.items.push(line.replace(/^[-•]\s*/, ''))
    } else if (cur) {
      cur.items.push(line)
    } else {
      cur = { header: '', items: [line] }
      sections.push(cur)
    }
  }
  return { title, sections }
}

/* ═══════════════════════════════════════════════════════════
   v6.92 LayeredBriefing — 4-layer dashboard AI card
   Layer 1: 狀態異常置頂（conflicts 紅卡 + overdue amber 卡）
   Layer 2: 今日核心指標（2×2 stat grid）
   Layer 3: 脈絡與趨勢（weather + news，可收合）
   Layer 4: 延伸內容（bible，預設收合）
   ═══════════════════════════════════════════════════════════ */
function LayeredBriefing({ layers, weather, summary, pendingQs, pqIndex, navigate, i18nLang, onDismiss, onDot, customFor, customText, onCustomFor, onCustomText, onChip, onCustomSubmit, onCustomOpen }: {
  layers: any
  weather: any
  summary: string
  pendingQs: any[]
  pqIndex: number
  navigate: (to: string) => void
  i18nLang: string
  onDismiss: (id: string) => void
  onDot: (i: number) => void
  // v7.06: inline input（自己輸入 / 前綴 chip）state + handlers
  customFor: string | null
  customText: string
  onCustomFor: (id: string | null) => void
  onCustomText: (v: string) => void
  onChip: (q: any, a: string) => void
  onCustomSubmit: (q: any) => void
  onCustomOpen: (id: string) => void
}) {
  const { t } = useTranslation()
  const conflicts: any[] = layers?.conflicts || []
  const overdue: any[] = layers?.overdue || []
  const stats: any = layers?.stats || {}
  const news: any[] = layers?.news || []
  const bible: any = layers?.bible || {}
  const hasAlerts = conflicts.length > 0 || overdue.length > 0
  const navigateTo = (to: string) => { navigate(to) }

  const fmtDue = (d: string) => {
    if (!d) return ''
    const dt = new Date(d)
    if (isNaN(dt.getTime())) return String(d).slice(0, 10)
    return dt.toLocaleDateString(i18nLang, { month: 'numeric', day: 'numeric' })
  }

  return (
    <div className="dv2-layered">
      {/* ── AI Summary · 置頂整合（briefing 4 次/日預生成，跟用戶語言）── */}
      {summary && (
        <div className="dv2-summary-card">
          <div className="dv2-summary-head">
            <span className="dv2-summary-icon">✨</span>
            <span className="dv2-summary-title">{t('dashboard.aiSummary', { defaultValue: 'AI 摘要' })}</span>
          </div>
          <div className="dv2-summary-text">{summary}</div>
        </div>
      )}

      {/* ── Layer 0 · AI 主動提問（Calendar + Record Awareness 輪播）── */}
      {pendingQs.length > 0 && (() => {
        const q = pendingQs[pqIndex % pendingQs.length]
        const customPlaceholder = String(q.source || '').includes('touchpoint_contact')
          ? t('dashboard.customInputTouchpointContact', { defaultValue: '輸入聯繫人姓名或 email…' })
          : {
            calendar: t('dashboard.customInputCalendar', { defaultValue: '例如：加地點：尖沙咀辦公室' }),
            contact: t('dashboard.customInputContact', { defaultValue: '例如：加電話：9123 4567' }),
            company: t('dashboard.customInputCompany', { defaultValue: '例如：加網址：kinet.com' }),
            touchpoint: t('dashboard.customInputTouchpoint', { defaultValue: '例如：加備註：傾咗 budget' }),
            project: t('dashboard.customInputProject', { defaultValue: '例如：加 deadline：2026-09-01' }),
          }[String(q.context_type)] || t('dashboard.customInputDefault', { defaultValue: '輸入你想寫入嘅內容…' })
        return (
          <div className="dv2-pq-card" key={q.id}>
            <div className="dv2-pq-head">
              <span className="dv2-pq-icon">💬</span>
              <span className="dv2-pq-title">{t('dashboard.aiPrompt', { defaultValue: 'AI 管家提問' })}</span>
              <button type="button" className="dv2-pq-dismiss" onClick={() => onDismiss(q.id)} aria-label={t('dashboard.dismissIssue', { defaultValue: '忽略此問題' })}>✕</button>
            </div>
            <div className="dv2-pq-body">
              <div className="dv2-pq-question">{q.question}</div>
              {customFor === q.id ? (
                <div className="dv2-pq-agenda">
                  <input
                    className="dv2-pq-agenda-input"
                    value={customText}
                    onChange={e => onCustomText(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') onCustomSubmit(q) }}
                    placeholder={customPlaceholder}
                    autoFocus
                  />
                  <button type="button" className="dv2-pq-chip dv2-pq-agenda-save" onClick={() => onCustomSubmit(q)} disabled={!customText.trim() || customText.trim().endsWith('：') || customText.trim().endsWith(':')}>{t('dashboard.saveAgenda', { defaultValue: '儲存 ✓' })}</button>
                  <button type="button" className="dv2-pq-chip" onClick={() => onCustomFor(null)}>{t('dashboard.cancel', { defaultValue: '取消' })}</button>
                </div>
              ) : (
                <>
                  <div className="dv2-pq-chips">
                    {(q.suggested_answers || []).map((a: string) => (
                      <button key={a} type="button" className="dv2-pq-chip" onClick={() => onChip(q, a)}>{a}</button>
                    ))}
                  </div>
                  <button type="button" className="dv2-pq-custom-btn" onClick={() => onCustomOpen(q.id)}>
                    ✏️ {t('dashboard.customInput', { defaultValue: '自己輸入' })}
                  </button>
                </>
              )}
              {pendingQs.length > 1 && (
                <div className="dv2-pq-dots">
                  {pendingQs.map((_, i) => (
                    <span key={i} className={`dv2-pq-dot ${i === pqIndex % pendingQs.length ? 'on' : ''}`} onClick={() => onDot(i)} />
                  ))}
                </div>
              )}
            </div>
          </div>
        )
      })()}

      {/* ── Layer 1 · 需要立即處理 ── */}
      {hasAlerts && (
        <div className="dv2-layer-label">{t('dashboard.layer1Urgent', { defaultValue: '🌙 Layer 1 · 需要立即處理' })}</div>
      )}
      {conflicts.length > 0 && (
        <div className="dv2-status-card dv2-status-danger">
          <div className="dv2-status-head">
            <span className="dv2-status-icon">🚨</span>
            <span className="dv2-status-title">{t('dashboard.conflictDetection', { defaultValue: '行程衝突偵測' })}</span>
            <button type="button" className="dv2-status-go" onClick={() => navigateTo('/calendar')}>{t('dashboard.viewCalendarLink', { defaultValue: '查看行事曆 ›' })}</button>
            <span className="dv2-chip dv2-chip-danger">{t('dashboard.highRisk', { defaultValue: '高風險' })}</span>
          </div>
          <div className="dv2-status-body">
            {conflicts.map((c, i) => (
              <div key={i} className="dv2-status-row">
                <span className="dv2-status-dot" style={{ background: '#EF4444' }} />
                <span className="dv2-status-text">
                  {t('dashboard.overlapsWith', { defaultValue: '{{a}} 與 {{b}} 重疊', a: c.event_a, b: c.event_b })}
                  <span className="dv2-tag dv2-tag-overdue">{t('dashboard.conflictTag', { defaultValue: '衝突' })}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {overdue.length > 0 && (
        <div className="dv2-status-card dv2-status-warn">
          <div className="dv2-status-head">
            <span className="dv2-status-icon">⏰</span>
            <span className="dv2-status-title">{t('dashboard.overdueItems', { defaultValue: '逾期事項' })}</span>
            <button type="button" className="dv2-status-go" onClick={() => navigateTo('/tasks')}>{t('dashboard.viewTasksLink', { defaultValue: '查看任務 ›' })}</button>
            <span className="dv2-chip dv2-chip-warn">{t('dashboard.itemsOverdue', { defaultValue: '{{count}} 項逾期', count: overdue.length })}</span>
          </div>
          <div className="dv2-status-body">
            {overdue.map((o, i) => (
              <div key={i} className="dv2-status-row">
                <span className="dv2-status-dot" style={{ background: '#F59E0B' }} />
                <span className="dv2-status-text">
                  <b>{o.title}</b>
                  {o.due_date && <span className="dv2-tag dv2-tag-overdue">{t('dashboard.originalDue', { defaultValue: '原定 {{date}}', date: fmtDue(o.due_date) })}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Layer 2 · 今日核心指標 ── */}
      {(stats.tasks_today != null || stats.contacts_total != null) && (
        <div className="dv2-layer-label">{t('dashboard.layer2Core', { defaultValue: '📊 Layer 2 · 今日核心指標' })}</div>
      )}
      <div className="dv2-l2-grid">
        {stats.tasks_today != null && (
          <div className="dv2-stat-card">
            <div className="dv2-stat-label">{t('dashboard.todayTodos', { defaultValue: '✅ 今日待辦' })}</div>
            <div className="dv2-stat-value" style={{ color: 'var(--color-blue, #2563EB)' }}>{stats.tasks_today}</div>
            {stats.tasks_p1 > 0 && <div className="dv2-stat-sub">{t('dashboard.p1Priority', { defaultValue: '{{count}} 項 P1 優先', count: stats.tasks_p1 })}</div>}
          </div>
        )}
        {stats.meetings_today != null && (
          <div className="dv2-stat-card">
            <div className="dv2-stat-label">{t('dashboard.todayMeetings', { defaultValue: '📅 今日會議' })}</div>
            <div className="dv2-stat-value" style={{ color: 'var(--color-purple, #7C3AED)' }}>{stats.meetings_today}</div>
            {stats.next_meeting && <div className="dv2-stat-sub">{String(stats.next_meeting).slice(0, 22)}</div>}
          </div>
        )}
        {stats.contacts_total != null && (
          <div className="dv2-stat-card">
            <div className="dv2-stat-label">{t('dashboard.contacts', { defaultValue: '👥 聯絡人' })}</div>
            <div className="dv2-stat-value" style={{ color: 'var(--color-blue, #2563EB)' }}>{stats.contacts_total}</div>
            <div className="dv2-stat-sub">Total Contacts</div>
          </div>
        )}
        {stats.companies_total != null && (
          <div className="dv2-stat-card">
            <div className="dv2-stat-label">{t('dashboard.companies', { defaultValue: '🏢 公司' })}</div>
            <div className="dv2-stat-value" style={{ color: 'var(--color-purple, #7C3AED)' }}>{stats.companies_total}</div>
            <div className="dv2-stat-sub">Total Companies</div>
          </div>
        )}
      </div>

      {/* ── Layer 3 · 脈絡與趨勢（可收合） ── */}
      {(weather?.temp != null || news.length > 0) && (
        <div className="dv2-layer-label">{t('dashboard.layer3Trends', { defaultValue: '🗂 Layer 3 · 脈絡與趨勢' })}</div>
      )}
      {weather?.temp != null && (
        <details className="dv2-collapsible" open>
          <summary>
            <span>{t('dashboard.weather', { defaultValue: '☀️ 天氣' })}</span>
            <span className="dv2-coll-chev">▸</span>
          </summary>
          <div className="dv2-coll-content">
            <div className="dv2-weather-row">
              <span className="dv2-weather-temp">{weather.temp}°C</span>
              <span className="dv2-weather-desc">
                {weather.desc || weather.condition || ''}
                {weather.condition ? ` · ${weather.condition}` : ''}
              </span>
            </div>
          </div>
        </details>
      )}
      {news.length > 0 && (
        <details className="dv2-collapsible">
          <summary>
            <span>{t('dashboard.industryNews', { defaultValue: '📰 行業新聞摘要' })}</span>
            <span className="dv2-coll-chev">▸</span>
          </summary>
          <div className="dv2-coll-content">
            {news.map((n, i) => (
              <div key={i} className="dv2-news-item">
                <span className="dv2-news-src">{String(n.feed || '').replace('www.', '').split('.')[0]}</span>
                <span className="dv2-news-title">{n.title}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* ── Layer 4 · 延伸內容（預設收合） ── */}
      {bible?.reference && (
        <>
          <div className="dv2-layer-label">{t('dashboard.layer4Extended', { defaultValue: '📖 Layer 4 · 延伸內容' })}</div>
          <details className="dv2-collapsible">
            <summary>
              <span>{t('dashboard.devotion', { defaultValue: '🙏 靈修 · {{reference}}', reference: bible.reference })}</span>
              <span className="dv2-coll-chev">▸</span>
            </summary>
            <div className="dv2-coll-content">
              {bible.summary && <p className="dv2-bible-summary">{bible.summary}</p>}
              {(bible.links?.bible_com || bible.links?.we_devote) && (
                <div className="dv2-bible-links">
                  {bible.links?.bible_com && (
                    <a href={bible.links.bible_com} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>{t('dashboard.openRev', { defaultValue: '📖 打開和合本修訂版' })}</a>
                  )}
                  {bible.links?.we_devote && (
                    <a href={bible.links.we_devote} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>{t('dashboard.readWithMicro', { defaultValue: '📱 用微讀細讀經文' })}</a>
                  )}
                </div>
              )}
            </div>
          </details>
        </>
      )}
    </div>
  )
}

const SLOT_LABELS: Record<string, { emoji: string; labelKey: string }> = {
  morning: { emoji: '🌅', labelKey: 'dashboard.slotLabels.morning' },
  noon: { emoji: '☀️', labelKey: 'dashboard.slotLabels.noon' },
  evening: { emoji: '🌆', labelKey: 'dashboard.slotLabels.evening' },
  night: { emoji: '🌙', labelKey: 'dashboard.slotLabels.night' },
}

const ALL_WIDGETS = [
  // ── 2026-09-09 清理（用戶拍板）：假數據/名不符實/重複 widgets 移除 ──
  // ❌ 假數據：s5 運費成本概覽（$124.5K hardcode）
  // ⚠️ 名不符實：c3 資料完整度（allCompanies[0] 單一公司）、co3 續約提醒（冇續約邏輯）、
  //    co4 健康分數（completeness 扮）、te2 在線狀態（冇真 online status）、
  //    p2/p3/p4 里程碑/進度/資源（3 個內容一樣 = projects list）
  // 🔁 重複：interactions/touchpoints（= activity）、cal3 拜訪行程（= events）
  // 全部記錄 docs/nice-to-have-backlog-2026-09-09.md NTH-05 + Notion tasks
  { id: 'ai', labelKey: 'dashboard.aiInsight', group: 'ai', required: true },
  { id: 'todos', labelKey: 'dashboard.widgets.todayTodos', group: 'core' },
  { id: 'events', labelKey: 'dashboard.upcoming', group: 'core' },
  { id: 'activity', labelKey: 'dashboard.recentActivityTable', group: 'core' },
  { id: 'ask_ai', labelKey: 'dashboard.askAi', group: 'core' },
  { id: 'c1', labelKey: 'dashboard.addContact', group: 'contacts' },
  { id: 'c2', labelKey: 'dashboard.pendingContacts', group: 'contacts' },
  { id: 'c5', labelKey: 'dashboard.sourceDistribution', group: 'contacts' },
  { id: 'co1', labelKey: 'dashboard.totalCompanies', group: 'companies' },
  { id: 'co2', labelKey: 'dashboard.clientTier', group: 'companies' },
  { id: 'co5', labelKey: 'dashboard.industryDistribution', group: 'companies' },
  { id: 'p1', labelKey: 'dashboard.activeProjects', group: 'projects' },
  { id: 't2', labelKey: 'dashboard.overdueTodos', group: 'tasks' },
  { id: 't3', labelKey: 'dashboard.priorityList', group: 'tasks' },
  { id: 't4', labelKey: 'dashboard.completionRate', group: 'tasks' },
  { id: 'cal2', labelKey: 'dashboard.meetingDensity', group: 'calendar' },
]
const WIDGET_GROUPS: { key: string; labelKey: string }[] = [
  { key: 'ai', labelKey: 'dashboard.widgetGroups.ai' },
  { key: 'core', labelKey: 'dashboard.widgetGroups.core' },
  { key: 'contacts', labelKey: 'dashboard.widgetGroups.contacts' },
  { key: 'companies', labelKey: 'dashboard.widgetGroups.companies' },
  { key: 'projects', labelKey: 'dashboard.widgetGroups.projects' },
  { key: 'tasks', labelKey: 'dashboard.widgetGroups.tasks' },
  { key: 'calendar', labelKey: 'dashboard.widgetGroups.calendar' },
  { key: 'team', labelKey: 'dashboard.widgetGroups.team' },
  { key: 'cost', labelKey: 'dashboard.widgetGroups.cost' },
]
const WIDGET_PREF_KEY = 'nexus-dashboard-widgets-v2'
const WIDGET_ORDER_KEY = 'nexus-dashboard-widget-order-v2'
/* 2026-09-10 Terrence（G08 less is more）: 首頁由 26 個 widget 精簡到 3 個重點
   （AI 洞察摘要永遠置頂，唔喺呢個 list）。其餘 widget 唔係刪咗 —— 用戶喺
   「新增小工具」仍然可以隨時加返。 */
const DEFAULT_ORDER = ['todos', 'events', 'activity']

const WIDGET_SIZE_KEY = 'nexus-dashboard-widget-sizes'

const SPAN_BY_LEVEL: Record<number, number> = { 1: 3, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12, 7: 12 }
const HEIGHT_BY_LEVEL: Record<number, number> = { 1: 160, 2: 200, 3: 240, 4: 280, 5: 320, 6: 400, 7: 480 }
const SIZE_LEVELS = [1, 2, 3, 4, 5, 6, 7]
const snapToLevel = (val: number, map: Record<number, number>): number => {
  let best = SIZE_LEVELS[0]
  for (const lv of SIZE_LEVELS) {
    if (Math.abs(val - map[lv]) < Math.abs(val - map[best])) best = lv
  }
  return map[best]
}
const levelOf = (val: number, map: Record<number, number>): number => {
  let best = SIZE_LEVELS[0]
  for (const lv of SIZE_LEVELS) {
    if (Math.abs(val - map[lv]) < Math.abs(val - map[best])) best = lv
  }
  return best
}

export default function DashboardV2() {
  // shell 先、內容後（見 docs/bug-mobile-nav-first-load.md）：
  // DashboardV2 呢個 subtree 係登入後首次 render 最重嘅部分（40+ widget）。
  // 第一格唔 render，令 LayoutV2 嘅 sidebar + bottom nav 即刻 paint 得成；
  // widget grid 下一格（rAF）才上。gate 喺下面 return 之前（全部 hooks 之後）。
  const [contentReady, setContentReady] = useState(false);
  useEffect(() => {
    const r = requestAnimationFrame(() => setContentReady(true));
    return () => cancelAnimationFrame(r);
  }, []);
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const fmtDT = (d: string) => {
    if (!d) return '—'
    const dt = new Date(d)
    if (isNaN(dt.getTime())) return String(d).slice(0, 10)
    return dt.toLocaleString(i18n.language, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }
  const fmtDay = (d: string) => {
    if (!d) return ''
    const dt = new Date(d)
    if (isNaN(dt.getTime())) return String(d).slice(0, 10)
    return dt.toLocaleDateString(i18n.language, { month: 'numeric', day: 'numeric' })
  }
  const { showToast } = useToast()
  const [stats, setStats] = useState<Stats>({ contacts: 0, companies: 0, tasksDue: 0 })
  const [todos, setTodos] = useState<Todo[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [activity, setActivity] = useState<any[]>([])
  const [pendingContacts, setPendingContacts] = useState<any[]>([])
  const [, setCompanies3] = useState<any[]>([])
  const [allCompanies, setAllCompanies] = useState<any[]>([])
  const [allContacts, setAllContacts] = useState<any[]>([])
  const [, setProjects] = useState<any[]>([])
  const [projectsTotal, setProjectsTotal] = useState(0)
  const [overdueTasks, setOverdueTasks] = useState<any[]>([])
  const [taskTotal, setTaskTotal] = useState(0)
  const [doneTaskTotal, setDoneTaskTotal] = useState(0)
  const [, setTeamUsers] = useState<any[]>([])
  const [aiInsight, setAiInsight] = useState<AiInsight | null>(null)
  const [aiWeather, setAiWeather] = useState<any>(null)
  const [aiLoading, setAiLoading] = useState(true)
  // v6.92: structured layered briefing data (Layer 1-4 cards) from backend
  const [aiLayers, setAiLayers] = useState<any>(null)
  // v6.95: AI 整合摘要（置頂 — briefing 4 次/日預生成，跟用戶語言）
  const [aiSummary, setAiSummary] = useState('')
  // v6.96: briefing 最後生成時間（4 次/日，唔係即時更新）
  const [aiGenAt, setAiGenAt] = useState('')
  // v6.94: calendar awareness — AI 主動提問（pending questions 輪播）
  const [pendingQs, setPendingQs] = useState<any[]>([])
  const [pqIndex, setPqIndex] = useState(0)
  // v7.05: AI 管家提問 → inline input（打內容 → 加到 record；v7.06 支援所有 context type）
  const [customFor, setCustomFor] = useState<string | null>(null)
  const [customText, setCustomText] = useState('')

  const [customizeMode, setCustomizeMode] = useState(false)
  const [isPhone, setIsPhone] = useState(() => (typeof window !== 'undefined' ? window.matchMedia('(max-width: 640px)').matches : false))
  const [wLevels, setWLevels] = useState<Record<string, number>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(WIDGET_SIZE_KEY) || 'null')
      const out: Record<string, number> = {}
      for (const k of Object.keys(saved || {})) {
        const v = saved[k]
        if (Array.isArray(v) && typeof v[0] === 'number' && SIZE_LEVELS.includes(v[0])) out[k] = v[0]
      }
      return out
    } catch { return {} }
  })
  const [hLevels, setHLevels] = useState<Record<string, number>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(WIDGET_SIZE_KEY) || 'null')
      const out: Record<string, number> = {}
      for (const k of Object.keys(saved || {})) {
        const v = saved[k]
        if (Array.isArray(v) && typeof v[1] === 'number' && SIZE_LEVELS.includes(v[1])) out[k] = v[1]
      }
      return out
    } catch { return {} }
  })
  const [addWidgetOpen, setAddWidgetOpen] = useState(false)
  const [widgetSearch, setWidgetSearch] = useState('')
  const [enabledWidgets, setEnabledWidgets] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(WIDGET_PREF_KEY) || 'null') || DEFAULT_ORDER }
    catch { return DEFAULT_ORDER }
  })
  const [widgetOrder, setWidgetOrder] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(WIDGET_ORDER_KEY) || 'null')
      if (Array.isArray(saved) && saved.length === DEFAULT_ORDER.length) return saved
    } catch { /* ignore */ }
    return DEFAULT_ORDER
  })
  const [todosExpanded, setTodosExpanded] = useState(false)
  const [activityDrawer, setActivityDrawer] = useState<any | null>(null)
  const [aiExpanded, setAiExpanded] = useState(false)

  // ── Typewriter for AI headline (plays once per mount, then instant) ──
  const [typedHeadline, setTypedHeadline] = useState('')
  const [headlineTyping, setHeadlineTyping] = useState(false)
  const headlineTypedRef = useRef(false)
  const typeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!aiExpanded || !aiInsight) return
    const full = aiInsight.headline || ''
    if (headlineTypedRef.current || full.length === 0) { setTypedHeadline(full); return }
    setHeadlineTyping(true)
    setTypedHeadline('')
    let i = 0
    typeTimerRef.current = setInterval(() => {
      i += 2
      setTypedHeadline(full.slice(0, i))
      if (i >= full.length) {
        if (typeTimerRef.current) clearInterval(typeTimerRef.current)
        typeTimerRef.current = null
        setHeadlineTyping(false)
        headlineTypedRef.current = true
      }
    }, 24)
    return () => { if (typeTimerRef.current) clearInterval(typeTimerRef.current) }
  }, [aiExpanded, aiInsight])

  // ── Drag reorder (Pointer Events — works desktop + touch) ──
  const [dragWid, setDragWid] = useState<string | null>(null)
  const dragRef = useRef<{ wid: string; startX: number; startY: number; moved: boolean } | null>(null)
  const MOVE_THRESHOLD = 6

  const onDragMove = (e: PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    if (!d.moved && Math.hypot(e.clientX - d.startX, e.clientY - d.startY) < MOVE_THRESHOLD) return
    d.moved = true
    setDragWid(d.wid)
    const widgets = [...document.querySelectorAll<HTMLElement>('.dv2-grid .dv2-widget[data-wid]')]
    let best: HTMLElement | null = null
    let bestDist = Infinity
    for (const w of widgets) {
      const r = w.getBoundingClientRect()
      const dist = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2))
      if (dist < bestDist) { bestDist = dist; best = w }
    }
    const targetWid = best?.dataset.wid
    if (!targetWid || targetWid === d.wid) return
    setWidgetOrder(prev => {
      const from = prev.indexOf(d.wid)
      const to = prev.indexOf(targetWid)
      if (from === -1 || to === -1 || from === to) return prev
      const next = [...prev]
      next.splice(from, 1)
      next.splice(to, 0, d.wid)
      return next
    })
  }

  const onDragEnd = () => {
    document.removeEventListener('pointermove', onDragMove)
    document.removeEventListener('pointerup', onDragEnd)
    if (dragRef.current?.moved) showToast(t('dashboard.layoutUpdated', { defaultValue: '版面順序已更新' }))
    dragRef.current = null
    setDragWid(null)
  }

  const startDrag = (e: React.PointerEvent, wid: string) => {
    if (!customizeMode) return
    e.preventDefault()
    dragRef.current = { wid, startX: e.clientX, startY: e.clientY, moved: false }
    document.addEventListener('pointermove', onDragMove)
    document.addEventListener('pointerup', onDragEnd)
  }

  useEffect(() => {
    localStorage.setItem(WIDGET_ORDER_KEY, JSON.stringify(widgetOrder))
  }, [widgetOrder])

  useEffect(() => {
    localStorage.setItem(WIDGET_SIZE_KEY, JSON.stringify(Object.fromEntries(Object.keys(wLevels).map(k => [k, [wLevels[k], hLevels[k] || 3]]))))
  }, [wLevels, hLevels])

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const onChg = () => setIsPhone(mq.matches)
    mq.addEventListener?.('change', onChg)
    return () => mq.removeEventListener?.('change', onChg)
  }, [])

  useEffect(() => {
    // ── Stats: compose from existing endpoints (no new backend needed) ──
    Promise.all([
      apiClient.get<{ total: number }>('/api/v1/crm/contacts?limit=1').catch(() => ({ total: 0 })),
      apiClient.get<{ total: number }>('/api/v1/crm/companies?limit=1').catch(() => ({ total: 0 })),
      apiClient.get<{ total: number }>('/api/v1/crm/tasks?limit=1').catch(() => ({ total: 0 })),
    ]).then(([c, co, t]) => {
      setStats({ contacts: c?.total || 0, companies: co?.total || 0, tasksDue: t?.total || 0 })
    })
    apiClient.get<{ items: any[]; total: number }>('/api/v1/crm/contacts?limit=1000').then((d: any) => setAllContacts(d?.items || [])).catch(() => {})
    apiClient.get<{ items: any[]; total: number }>('/api/v1/crm/companies?limit=1000').then((d: any) => setAllCompanies(d?.items || [])).catch(() => {})
    apiClient.get<{ items: any[]; total: number }>('/api/v1/crm/projects?limit=50').then((d: any) => { setProjects(d?.items || []); setProjectsTotal(d?.total || 0) }).catch(() => {})
    apiClient.get<{ total: number }>('/api/v1/crm/tasks?status=done&limit=1').then((d: any) => setDoneTaskTotal(d?.total || 0)).catch(() => {})
    apiClient.get<{ items: any[]; total: number }>('/api/v1/crm/tasks?status=pending&limit=20').then((d: any) => {
      const now = Date.now()
      const overdue = (d?.items || []).filter((x: any) => x?.due_date && new Date(x.due_date).getTime() < now)
      setOverdueTasks(overdue.slice(0, 5))
      setTaskTotal(d?.total || 0)
    }).catch(() => {})
    apiClient.get<{ items: Todo[] }>('/api/v1/crm/tasks?due=today&status_not=done&limit=8').then((d: any) => setTodos((d?.items || []).filter((x: any) => x?.status !== 'done'))).catch(() => {})
    apiClient.get<{ items: any[] }>('/api/v1/crm/calendar-events').then((d: any) => setEvents(d?.items || d || [])).catch(() => {})
    apiClient.get<{ items: any[] }>('/api/v1/crm/touchpoints?limit=8').then((d: any) => setActivity(d?.items || [])).catch(() => {})
    // ── New widgets (all real API data — no demo fallback) ──
    apiClient.get<{ items: any[] }>('/api/v1/crm/contacts?status=lead&limit=5').then((d: any) => setPendingContacts(d?.items || [])).catch(() => {})
    apiClient.get<{ items: any[] }>('/api/v1/crm/companies?limit=3').then((d: any) => setCompanies3(d?.items || [])).catch(() => {})
    apiClient.get<any[]>('/api/v1/crm/todo/users').then((d: any) => setTeamUsers(Array.isArray(d) ? d : [])).catch(() => {})
    // ── AI insight: content = same generated briefing as Telegram (portal style applied here) ──
    apiClient.get<any>('/api/v1/ai/briefing').then((d: any) => {
      if (d?.weather && typeof d.weather === 'object') setAiWeather(d.weather)
      // v6.95: AI 整合摘要（置頂）
      if (d?.summary) setAiSummary(d.summary)
      if (d?.generated_at) setAiGenAt(d.generated_at)
      // v6.92: layered card data (Layer 1-4) — when present, render the new
      // layered design; markdown sections remain as fallback.
      if (d?.layers && Object.keys(d.layers).length) setAiLayers(d.layers)
      if (d?.content) {
        // Same content as Telegram → portal rendering
        const parsed = parseBriefing(d.content)
        setAiInsight({
          headline: parsed.title,
          sections: parsed.sections,
          slot: d.slot || '',
          generatedAt: d.generated_at || '',
          source: 'generated',
        })
      } else {
        // Fallback: CRM-core mapping (no generated briefing yet today)
        const tasks = (d?.tasks || []) as any[]
        const risks = tasks.filter((x: any) => x.priority === 'P0' || x.priority === 'P1').slice(0, 3)
        const events = (d?.schedule || []).slice(0, 3)
        const sections: AiSection[] = []
        if (risks.length) sections.push({ header: t('dashboard.risksHeader', { defaultValue: '風險' }), items: risks.map((x: any) => `${x.priority} ${x.title}`) })
        if (events.length) sections.push({ header: t('dashboard.activityHeader', { defaultValue: '活動' }), items: events.map((x: any) => `${x.title}`) })
        setAiInsight({
          headline: d?.ai_tip || t('dashboard.todayFocus', { defaultValue: '今日重點：請查看待辦任務及即將來臨的會議。' }),
          sections,
          slot: d.slot || '',
          generatedAt: d.generated_at || '',
          source: 'fallback',
        })
      }
      setAiLoading(false)
    }).catch(() => setAiLoading(false))
  }, [])

  // ── v6.94: Calendar Awareness — AI 主動提問（pending questions 輪播）──
  useEffect(() => {
    apiClient.get<{ items: any[] }>('/api/v1/ai-secretary/pending-questions')
      .then((d: any) => setPendingQs(d?.items || []))
      .catch(() => {})
  }, [])

  // 輪播 — 每 10 秒轉下一條（用戶 2026-08-26：10s 轉一個 + slider effect）
  useEffect(() => {
    if (pendingQs.length <= 1) return
    const t = setInterval(() => setPqIndex(i => (i + 1) % pendingQs.length), 10000)
    return () => clearInterval(t)
  }, [pendingQs.length])

  const answerPendingQ = async (id: string, answer: string) => {
    try {
      await apiClient.post(`/api/v1/ai-secretary/pending-questions/${id}/answer`, { answer })
      // v7.07: refetch 攞 follow-up questions（例如「加入 Touchpoint」→「同邊個聯繫？」）
      const d = await apiClient.get<{ items: any[] }>('/api/v1/ai-secretary/pending-questions?force_scan=false')
      setPendingQs(d?.items || [])
      setPqIndex(0)
      setCustomFor(null)
      setCustomText('')
      showToast(answer.startsWith('加') ? t('dashboard.recordUpdated', { defaultValue: '已更新到 record ✓' }) : t('dashboard.noted', { defaultValue: '已記錄' }))
    } catch { /* keep the question on failure */ }
  }

  const dismissPendingQ = async (id: string) => {
    try {
      await apiClient.post(`/api/v1/ai-secretary/pending-questions/${id}/dismiss`, {})
      setPendingQs(prev => prev.filter(q => q.id !== id))
      setPqIndex(0)
      setCustomFor(null)
      setCustomText('')
    } catch { /* keep the question on failure */ }
  }

  // v7.06: chip 撳法 — 「唔使」→ dismiss；「：」結尾（前綴 chip）→ 開 inline input 預填；其他 → 直接 answer
  const handleChip = (q: any, a: string) => {
    if (a === '唔使') { dismissPendingQ(q.id); return }
    if (a.endsWith('：') || a.endsWith(':')) {
      setCustomFor(q.id)
      setCustomText(a)
      return
    }
    answerPendingQ(q.id, a)
  }

  // ✏️ 自己輸入 — 開空白 input（用戶自由打字，後端按前綴/keyword/source 解析）
  const openCustomInput = (id: string) => {
    setCustomFor(id)
    setCustomText('')
  }

  const submitCustom = (q: any) => {
    const text = customText.trim()
    // 得個前綴（「加電話：」）冇實際內容 → 唔提交
    if (!text || text.endsWith('：') || text.endsWith(':')) return
    answerPendingQ(q.id, text)
  }

  const hour = new Date().getHours()
  const greeting = hour < 12 ? t('dashboard.goodMorning', { defaultValue: 'Good morning' })
    : hour < 18 ? t('dashboard.goodAfternoon', { defaultValue: 'Good afternoon' })
    : t('dashboard.goodEvening', { defaultValue: 'Good evening' })

  const toggleTodo = (id: string) => {
    const td = todos.find(t => t.id === id)
    const nextDone = !td?.done
    // 完成後即時清除（唔再顯示已完成 item）；重新標記待辦就保留
    setTodos(prev => nextDone ? prev.filter(t => t.id !== id) : prev.map(t => t.id === id ? { ...t, done: false } : t))
    // Persist via existing task update endpoint (status done/pending)
    apiClient.patch(`/api/v1/crm/tasks/${id}`, { status: nextDone ? 'done' : 'pending' }).catch(() => {})
    showToast(nextDone ? t('dashboard.taskCompleted', { defaultValue: '任務已完成 ✓' }) : t('dashboard.reMarkedTodo', { defaultValue: '已重新標記為待辦' }))
  }

  const handleViewAll = (which: string) => {
    if (which === 'todos') setTodosExpanded(v => !v)
    else if (which === 'events') navigate('/calendar')
    else if (which === 'activity') navigate('/touchpoints')
    else showToast(t('dashboard.loadingFullList', { defaultValue: '正在載入完整列表…' }))
  }

  const toggleWidget = (id: string) => {
    const w = ALL_WIDGETS.find(x => x.id === id)
    if (w?.required) { showToast(t('dashboard.coreWidget', { defaultValue: '此小工具為核心元件，無法停用' })); return }
    setEnabledWidgets(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const saveWidgetPrefs = () => {
    localStorage.setItem(WIDGET_PREF_KEY, JSON.stringify(enabledWidgets))
    setAddWidgetOpen(false)
    showToast(t('dashboard.layoutUpdated', { defaultValue: '版面已更新' }))
  }
  const has = (id: string) => enabledWidgets.includes(id)
  const openTaskRow = (tp: any) => setActivityDrawer(tp)

  const dragHandle = (wid: string) => customizeMode ? (
    <span
      className="dv2-drag-handle"
      data-wid={wid}
      onPointerDown={(e) => startDrag(e, wid)}
      aria-label={t('dashboard.dragReorder', { defaultValue: '拖曳調整順序' })}
    ><SvcIcon name="grip-vertical" size={14} /></span>
  ) : null

  const widgetCls = (wid: string) => {
    const kpi = wid.startsWith('stats:') || ['c1', 'co1', 'p1'].includes(wid)
    const span = kpi ? 'dv2-w-stat' : wid === 'activity' ? 'dv2-w-table' : wid === 'ai' ? 'dv2-w-ai dv2-widget-ai' : 'dv2-w-list'
    return `dv2-widget ${span} ${dragWid === wid ? 'dragging' : ''}`
  }

  // ── Widget sizing (resize) — inline overrides when user has a saved size ──
  const widgetStyle = (wid: string): React.CSSProperties => {
    const wl = wLevels[wid]
    if (!wl) return {}
    const style: React.CSSProperties = { gridColumn: `span ${SPAN_BY_LEVEL[wl]}` }
    const hl = hLevels[wid]
    if (hl && !isPhone) style.aspectRatio = `${wl} / ${hl}`
    return style
  }

  // ── Resize (sizing adjust) — user drags grip to snap widget to size levels ──
  const resizeGrip = (wid: string) => (customizeMode && wid !== 'ai') ? (
    <div
      className="dv2-resize-grip"
      draggable={false}
      onMouseDown={(e) => {
        e.preventDefault(); e.stopPropagation()
        const startX = e.clientX, startY = e.clientY
        const gripEl = e.currentTarget as HTMLElement
        const widgetEl = gripEl.closest('[data-wid]') as HTMLElement
        const grid = gripEl.closest('.dv2-grid') as HTMLElement | null
        if (!grid || !widgetEl) return
        const defaultSpan = wid.startsWith('stats:') ? 3 : wid === 'activity' ? 12 : 6
        const startSpanNum = parseInt(widgetEl.style.gridColumn.match(/span (\d+)/)?.[1] || String(defaultSpan))
        const gridRect = grid.getBoundingClientRect()
        const gapVal = 16
        const colW = (gridRect.width - (11 * gapVal)) / 12
        let curWLv = wLevels[wid] ?? levelOf(startSpanNum, SPAN_BY_LEVEL)
        let curHLv = hLevels[wid] ?? 3
        // Drag tooltip showing (width level, height level)
        const tip = document.createElement('div')
        tip.style.cssText = 'position:absolute;bottom:28px;right:0;font-size:11px;font-weight:600;color:var(--color-primary);background:var(--color-surface-2);border:1px solid var(--color-border);padding:2px 8px;border-radius:6px;pointer-events:none;z-index:6'
        tip.textContent = `(${curWLv},${curHLv})`
        gripEl.appendChild(tip)
        const onMove = (ev: MouseEvent) => {
          const dx = ev.clientX - startX, dy = ev.clientY - startY
          const rawSpan = startSpanNum + dx / (colW + gapVal)
          const snappedSpan = snapToLevel(rawSpan, SPAN_BY_LEVEL)
          const newWLv = levelOf(snappedSpan, SPAN_BY_LEVEL)
          if (newWLv !== curWLv) {
            curWLv = newWLv
            widgetEl.style.gridColumn = `span ${snappedSpan}`
            widgetEl.style.aspectRatio = `${curWLv} / ${curHLv}`
          }
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
          setWLevels(prev => ({ ...prev, [wid]: curWLv }))
          setHLevels(prev => ({ ...prev, [wid]: curHLv }))
        }
        document.addEventListener('mousemove', onMove)
        document.addEventListener('mouseup', onUp)
      }}
      aria-label={t('dashboard.dragResize', { defaultValue: '拖曳調整大小' })}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12L12 22M22 2L2 22"/></svg>
    </div>
  ) : null

  const renderWidget = (wid: string) => {
    const kpiCard = (icon: React.ReactNode, label: string, value: React.ReactNode, color: string, onClick: () => void) => (
      <button className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)} onClick={onClick}>
                                {dragHandle(wid)}
                                {resizeGrip(wid)}
        <div className="dv2-widget-header"><div className="dv2-widget-title">{icon} {label}</div></div>
        <div className="dv2-widget-body dv2-stat-body">
          <div className="dv2-stat-value" style={{ color }}>{value}</div>
        </div>
      </button>
    )
    const barRow = (label: string, num: number, denom: number, color: string, right?: string) => {
      const pct = denom > 0 ? Math.round((num / denom) * 100) : 0
      return (
        <div className="dv2-bar-row" key={label}>
          <div className="dv2-bar-label"><span>{label}</span><span>{right ?? num}</span></div>
          <div className="dv2-bar-track"><div className="dv2-bar-fill" style={{ width: `${Math.min(100, pct)}%`, background: color }} /></div>
        </div>
      )
    }
    const listWidget = (title: React.ReactNode, viewAll: () => void, empty: string, rows: React.ReactNode, icon?: React.ReactNode) => (
      <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                {dragHandle(wid)}
                                {resizeGrip(wid)}
        <div className="dv2-widget-header">
          <div className="dv2-widget-title">{icon} {title}</div>
          {viewAll && <button className="dv2-widget-action" onClick={viewAll}>{t('common.viewAll', { defaultValue: '查看全部' })}</button>}
        </div>
        <div className="dv2-widget-body dv2-list-body">{rows || <div className="dv2-empty-mini">{empty}</div>}</div>
      </div>
    )
    // 統一排序：widget list 數據由新到舊（created_at → date → start fallback, 2026-09-09 用戶要求）
    const byNewest = (arr: any[]) => [...arr].sort((a, b) => {
      const ta = new Date(a?.created_at || a?.date || a?.start || 0).getTime()
      const tb = new Date(b?.created_at || b?.date || b?.start || 0).getTime()
      return (isNaN(tb) ? 0 : tb) - (isNaN(ta) ? 0 : ta)
    })
    if (wid.startsWith('stats:')) {
      const i = Number(wid.split(':')[1])
      const cards = [
        { icon: <SvcIcon name="contacts" size={15} />, label: t('dashboard.widgets.totalCustomers', { defaultValue: '累計聯絡人' }), value: stats.contacts, color: 'var(--color-primary)', onClick: () => navigate('/contacts') },
        { icon: <SvcIcon name="companies" size={15} />, label: t('dashboard.widgets.totalCompanies', { defaultValue: '總公司數' }), value: stats.companies, color: 'var(--color-purple, #7c3aed)', onClick: () => navigate('/companies') },
        { icon: <SvcIcon name="tasks" size={15} />, label: t('dashboard.widgets.tasksDue', { defaultValue: '待辦任務' }), value: stats.tasksDue, color: 'var(--color-amber, #d97706)', accent: true, onClick: () => navigate('/tasks') },
        { icon: <SvcIcon name="projects" size={15} />, label: t('dashboard.widgets.activeProjects', { defaultValue: '進行中專案' }), value: projectsTotal, color: 'var(--color-green, #16a34a)', onClick: () => navigate('/projects') },
      ]
      const c = cards[i]
      if (!c) return null
      return (
        <button className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)} onClick={c.onClick}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header"><div className="dv2-widget-title">{c.icon} {c.label}</div></div>
          <div className="dv2-widget-body dv2-stat-body">
            <div className="dv2-stat-value" style={{ color: c.color }}>{c.value}</div>
          </div>
        </button>
      )
    }
    if (wid === 'ai') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-ai-aura" aria-hidden="true" />
          <button
            className="dv2-widget-header dv2-ai-toggle"
            onClick={() => setAiExpanded(v => !v)}
            aria-expanded={aiExpanded}
            title={aiExpanded ? t('dashboard.collapseAiInsight', { defaultValue: '收起 AI 洞察' }) : t('dashboard.expandAiInsight', { defaultValue: '展開 AI 洞察詳情' })}
          >
            <div className="dv2-widget-title"><SvcIcon name="sparkles" size={15} className="dv2-ai-spark" /> {t('dashboard.aiInsight', { defaultValue: 'AI 洞察摘要' })}</div>
            <span className="dv2-ai-toggle-right">
              <span className="dv2-widget-badge">
                {aiGenAt
                  ? `🕐 ${new Date(aiGenAt).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })}`
                  : t('dashboard.aiUpdated', { defaultValue: 'AI 更新' })}
              </span>
              <SvcIcon name="chevron-down" size={16} className={`dv2-ai-chevron ${aiExpanded ? 'open' : ''}`} />
            </span>
          </button>
          {!aiExpanded && aiSummary && (
            <button
              className="dv2-ai-collapsed-summary"
              onClick={() => setAiExpanded(true)}
              title={t('dashboard.aiExpandHint', { defaultValue: '點擊展開詳細資料' })}
            >
              {aiSummary}
            </button>
          )}
          {aiExpanded && (
            <div className="dv2-widget-body dv2-ai-body">
              {aiLoading ? (
                <div className="dv2-ai-skeleton">
                  <div className="dv2-skel-line w70" /><div className="dv2-skel-line w90" /><div className="dv2-skel-line w50" />
                </div>
              ) : aiLayers ? (
                <LayeredBriefing layers={aiLayers} weather={aiWeather} summary={aiSummary} pendingQs={pendingQs} pqIndex={pqIndex} navigate={navigate} i18nLang={i18n.language} onDismiss={dismissPendingQ} onDot={setPqIndex} customFor={customFor} customText={customText} onCustomFor={setCustomFor} onCustomText={setCustomText} onChip={handleChip} onCustomSubmit={submitCustom} onCustomOpen={openCustomInput} />
              ) : aiInsight ? (
                <>
                  <p className="dv2-ai-headline">
                    {typedHeadline}{headlineTyping && <span className="dv2-ai-caret">▍</span>}
                  </p>
                  {!headlineTyping && (
                    <>
                      {aiInsight.sections.length > 0 ? (
                        <div className="dv2-ai-sections">
                          {aiInsight.sections.map((sec, si) => (
                            <div key={si} className="dv2-ai-section">
                              {sec.header && (() => {
                                const kind = sectionIcon(sec.header)
                                return (
                                  <div className="dv2-ai-section-header">
                                    {kind === 'weather' && aiWeather?.icon_emoji ? (
                                      <span className="dv2-ai-weather-emoji">{aiWeather.icon_emoji}</span>
                                    ) : (
                                      <SectionIcon kind={kind} />
                                    )}
                                    <span>{sec.header}</span>
                                  </div>
                                )
                              })()}
                              <div className="dv2-ai-section-body">
                                {sec.items.map((it, ii) => {
                                  const target = sectionRouteWithItemFallback(sec.header, it)
                                  return target ? (
                                    <button
                                      key={ii}
                                      className="dv2-ai-section-item dv2-ai-section-link"
                                      onClick={() => navigate(target)}
                                      title={t('dashboard.goToHeader', { defaultValue: '前往{{header}}', header: sec.header })}
                                    >
                                      <span>{it}</span>
                                      <SvcIcon name="chevron-right" size={13} className="dv2-ai-section-go" />
                                    </button>
                                  ) : (
                                    <div key={ii} className="dv2-ai-section-item">{it}</div>
                                  )
                                })}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="dv2-empty-mini">{t('dashboard.noAiInsight', { defaultValue: '暫無 AI 洞察' })}</div>
                      )}
                      {aiInsight.slot && (
                        <div className="dv2-ai-meta">
                          {SLOT_LABELS[aiInsight.slot]?.emoji || ''} {SLOT_LABELS[aiInsight.slot] ? t(SLOT_LABELS[aiInsight.slot].labelKey, { defaultValue: aiInsight.slot }) : aiInsight.slot}
                          {aiInsight.generatedAt ? ` · ${new Date(aiInsight.generatedAt).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })} 生成` : ''}
                        </div>
                      )}
                    </>
                  )}
                </>
              ) : <div className="dv2-empty-mini">{t('dashboard.noAiInsight', { defaultValue: '暫無 AI 洞察' })}</div>}
            </div>
          )}
        </div>
      )
    }
    if (wid === 'todos') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header">
            <div className="dv2-widget-title"><SvcIcon name="check-square" size={15} /> {t('dashboard.widgets.todaysTodos', { defaultValue: '今日待辦' })}</div>
            <button className="dv2-widget-action" onClick={() => handleViewAll('todos')}>{todosExpanded ? t('dashboard.collapse', { defaultValue: '收起' }) : t('common.viewAll', { defaultValue: '查看全部' })}</button>
          </div>
          <div className="dv2-widget-body dv2-list-body">
            {todos.length === 0 ? <div className="dv2-empty-mini">{t('dashboard.noTasksYet', { defaultValue: '暫無任務' })}</div> :
              (todosExpanded ? byNewest(todos).filter(td => !td.done) : byNewest(todos).filter(td => !td.done).slice(0, 4)).map((td) => (
                <button key={td.id} className="dv2-list-row dv2-list-row-btn" onClick={() => toggleTodo(td.id)}>
                  <span className={`dv2-checkbox ${td.done ? 'checked' : ''}`}>{td.done && <SvcIcon name="check" size={11} />}</span>
                  <span className={`dv2-list-row-title ${td.done ? 'done' : ''}`}>{td.title}</span>
                  <span className="dv2-list-row-meta">{td.due_time || ''}</span>
                </button>
              ))}
          </div>
        </div>
      )
    }
    if (wid === 'events') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header">
            <div className="dv2-widget-title"><SvcIcon name="calendar" size={15} /> {t('dashboard.widgets.upcomingEvents', { defaultValue: '即將舉行' })}</div>
            <button className="dv2-widget-action" onClick={() => handleViewAll('events')}>{t('common.viewAll', { defaultValue: '查看全部' })}</button>
          </div>
          <div className="dv2-widget-body dv2-list-body">
            {events.length === 0 ? <div className="dv2-empty-mini">{t('dashboard.noEvents', { defaultValue: '暫無活動' })}</div> :
              // events: 即將舉行 = 未來 event 由近到遠（最接近而家 = 最「新」排先）
              [...events].sort((a: any, b: any) => new Date(a?.start || a?.time || 0).getTime() - new Date(b?.start || b?.time || 0).getTime())
                .filter((ev: any) => { const s = new Date(ev?.start || ev?.time || 0).getTime(); return !isNaN(s) && s >= Date.now() - 3600e3 })
                .slice(0, 4)
                .map((ev) => (
                <button key={ev.id} className="dv2-list-row dv2-list-row-btn" onClick={() => navigate('/calendar')}>
                  <SvcIcon name="calendar" size={13} className="dv2-list-row-icon" />
                  <span className="dv2-list-row-title">{fmtDay(ev.start || ev.time)} {ev.time} {ev.title}</span>
                  <span className="dv2-list-row-tag">{ev.type}</span>
                </button>
              ))}
          </div>
        </div>
      )
    }
    if (wid === 'activity') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header">
            <div className="dv2-widget-title"><SvcIcon name="activity" size={15} /> {t('dashboard.widgets.recentActivity', { defaultValue: '最近活動' })}</div>
            <button className="dv2-widget-action" onClick={() => handleViewAll('activity')}>{t('common.viewAll', { defaultValue: '查看全部' })}</button>
          </div>
          <div className="dv2-widget-body dv2-table-body">
            <table className="dv2-table">
              <thead><tr><th>{t('touchpoint.type', { defaultValue: '類型' })}</th><th>{t('touchpoint.title', { defaultValue: '標題' })}</th><th>{t('contacts.company', { defaultValue: '公司' })}</th><th>{t('touchpoint.date', { defaultValue: '日期' })}</th></tr></thead>
              <tbody>
                {activity.length === 0 ? (
                  <tr><td colSpan={4} className="dv2-empty-mini">{t('dashboard.noActivity', { defaultValue: '暫無活動記錄' })}</td></tr>
                ) : byNewest(activity).slice(0, 5).map((tp) => (
                  <tr key={tp.id} className="dv2-table-row-clickable" onClick={() => openTaskRow(tp)}>
                    <td><span className="dv2-table-type-tag">{tp.type}</span></td>
                    <td>{tp.title}</td>
                    <td>{tp.company?.name || '—'}</td>
                    <td className="dv2-table-date">{fmtDT(tp.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )
    }
    if (wid === 'ask_ai') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header">
            <div className="dv2-widget-title"><SvcIcon name="sparkles" size={15} /> Ask AI</div>
          </div>
          <div className="dv2-widget-body dv2-list-body" style={{ maxHeight: 260 }}>
            <WidgetAskAI />
          </div>
        </div>
      )
    }
    if (wid === 'c2') {
      return (
        <div className={widgetCls(wid)} data-wid={wid} style={widgetStyle(wid)}>
                                        {dragHandle(wid)}
                                        {resizeGrip(wid)}
          <div className="dv2-widget-header">
            <div className="dv2-widget-title"><SvcIcon name="users" size={15} /> {t('dashboard.widgets.pendingContacts', { defaultValue: '待處理聯絡人' })}</div>
            <button className="dv2-widget-action" onClick={() => navigate('/contacts')}>{t('common.viewAll', { defaultValue: '查看全部' })}</button>
          </div>
          <div className="dv2-widget-body dv2-list-body">
            {pendingContacts.length === 0 ? <div className="dv2-empty-mini">{t('dashboard.noContacts', { defaultValue: '暫無待處理聯絡人' })}</div> :
              byNewest(pendingContacts).slice(0, 5).map((c) => (
                <button key={c.id} className="dv2-list-row dv2-list-row-btn" onClick={() => navigate('/contacts')}>
                  <SvcIcon name="users" size={13} className="dv2-list-row-icon" />
                  <span className="dv2-list-row-title">{c.name}</span>
                  <span className="dv2-list-row-meta">{c.company?.name || c.company || ''}</span>
                </button>
              ))}
          </div>
        </div>
      )
    }
    // ── Legacy KPI widgets ──
    if (wid === 'c1') return kpiCard(<SvcIcon name="users" size={15} />, t('dashboard.widgets.newContacts', { defaultValue: '新增聯絡人' }), stats.contacts, 'var(--color-primary)', () => navigate('/contacts'))
    if (wid === 'co1') return kpiCard(<SvcIcon name="building-2" size={15} />, t('dashboard.widgets.totalCompanies', { defaultValue: '公司總數' }), stats.companies, 'var(--color-purple, #7c3aed)', () => navigate('/companies'))
    if (wid === 'p1') return kpiCard(<SvcIcon name="folder-kanban" size={15} />, t('dashboard.widgets.activeProjects', { defaultValue: '進行中專案' }), projectsTotal, 'var(--color-amber, #d97706)', () => navigate('/projects'))

    // ── Legacy list / bar widgets ──
    if (wid === 'c5') {
      const colors = ['var(--color-blue, #2563eb)', 'var(--color-purple, #7c3aed)', 'var(--color-success, #16a34a)', 'var(--color-amber, #d97706)']
      const g = (k?: string) => k || t('dashboard.other', { defaultValue: '其他' })
      const dist = new Map<string, number>()
      allContacts.forEach((c) => { const key = g(c?.source); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      const total = allContacts.length || 1
      return listWidget(t('dashboard.widgets.sourceDistribution', { defaultValue: '來源分佈' }), () => navigate('/contacts'), t('dashboard.noContactsData', { defaultValue: '暫無聯絡人數據' }),
        top.length === 0 ? null : (
          <div className="dv2-bar-stack">{top.map(([k, n], i) => barRow(k, n, total, colors[i % colors.length]))}</div>
        ), <SvcIcon name="tags" size={15} />)
    }
    if (wid === 'co2') {
      const g = (k?: string) => k || t('dashboard.uncategorized', { defaultValue: '未分類' })
      const dist = new Map<string, number>()
      allCompanies.forEach((c) => { const key = g(c?.category || c?.industry); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      const total = allCompanies.length || 1
      return listWidget(t('dashboard.widgets.clientTier', { defaultValue: '公司分級' }), () => navigate('/companies'), t('dashboard.noCompanies', { defaultValue: '暫無公司' }),
        top.length === 0 ? null : (
          <div className="dv2-bar-stack">{top.map(([k, n]) => barRow(k, n, total, 'var(--color-purple, #7c3aed)'))}</div>
        ), <SvcIcon name="building-2" size={15} />)
    }
    if (wid === 'co5') {
      const g = (k?: string) => k || t('dashboard.uncategorized', { defaultValue: '未分類' })
      const dist = new Map<string, number>()
      allCompanies.forEach((c) => { const key = g(c?.industry || c?.category); dist.set(key, (dist.get(key) || 0) + 1) })
      const top = Array.from(dist.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      const total = allCompanies.length || 1
      return listWidget(t('dashboard.widgets.industryDistribution', { defaultValue: '行業分佈' }), () => navigate('/companies'), t('dashboard.noCompanies', { defaultValue: '暫無公司' }),
        top.length === 0 ? null : (
          <div className="dv2-bar-stack">{top.map(([k, n], i) => barRow(k, n, total, i === 0 ? 'var(--color-purple, #7c3aed)' : 'var(--color-blue, #2563eb)'))}</div>
        ), <SvcIcon name="tags" size={15} />)
    }
    if (wid === 't2') {
      return listWidget(t('dashboard.widgets.overdueTasks', { defaultValue: '逾期待辦' }), () => navigate('/tasks'), t('dashboard.noOverdue', { defaultValue: '暫無逾期待辦' }),
        overdueTasks.length === 0 ? null : byNewest(overdueTasks).slice(0, 5).map((td) => {
          const days = Math.max(1, Math.ceil((Date.now() - new Date(td.due_date).getTime()) / 86400000))
          return <div key={td.id} className="dv2-list-row"><span className="dv2-list-row-title">{td.title}</span><span className="dv2-list-row-meta">{days}日逾期</span></div>
        }), <SvcIcon name="clock" size={15} />)
    }
    if (wid === 't3') {
      const sorted = [...todos]
        .filter((td) => !td.done)
        // 保留 widget 語義：優先級排序；相同優先級內由新到舊（2026-09-09）
        .sort((a, b) => String(a.priority || '').localeCompare(String(b.priority || ''))
          || new Date((b as any)?.created_at || 0).getTime() - new Date((a as any)?.created_at || 0).getTime())
        .slice(0, 5)
      return listWidget(t('dashboard.widgets.priorityList', { defaultValue: '優先級列表' }), () => navigate('/tasks'), t('dashboard.noTasksYet', { defaultValue: '暫無任務' }),
        sorted.length === 0 ? null : sorted.map((td) => (
          <div key={td.id} className="dv2-list-row"><span className="dv2-list-row-title">{td.title}</span><span className="dv2-list-row-tag">{td.priority || ''}</span></div>
        )), <SvcIcon name="check-square" size={15} />)
    }
    if (wid === 't4') {
      const pct = taskTotal > 0 ? Math.round((doneTaskTotal / taskTotal) * 100) : 0
      return listWidget(t('dashboard.widgets.completionRate', { defaultValue: '完成率' }), () => navigate('/tasks'), t('dashboard.noTasksYet', { defaultValue: '暫無任務' }),
        <div className="dv2-bar-stack">
          <div className="dv2-bar-label"><span>{t('dashboard.widgets.completionRate', { defaultValue: '完成率' })}</span><span>{pct}%</span></div>
          <div className="dv2-bar-track"><div className="dv2-bar-fill" style={{ width: `${pct}%`, background: 'var(--color-success, #16a34a)' }} /></div>
        </div>, <Percent size={15} />)
    }
    if (wid === 'cal2') {
      const byDay = new Map<string, number>()
      events.forEach((ev) => {
        const d = new Date(ev?.start || ev?.time || Date.now())
        const day = d.getDay()
        const names = [t('dashboard.daysAbbr.0', { defaultValue: '日' }), t('dashboard.daysAbbr.1', { defaultValue: '一' }), t('dashboard.daysAbbr.2', { defaultValue: '二' }), t('dashboard.daysAbbr.3', { defaultValue: '三' }), t('dashboard.daysAbbr.4', { defaultValue: '四' }), t('dashboard.daysAbbr.5', { defaultValue: '五' }), t('dashboard.daysAbbr.6', { defaultValue: '六' })]
        const key = t('dashboard.weekday', { defaultValue: '週{{day}}', day: names[day] || day })
        byDay.set(key, (byDay.get(key) || 0) + 1)
      })
      const rows = Array.from(byDay.entries()).sort((a, b) => b[1] - a[1])
      const maxN = Math.max(1, ...rows.map(([, n]) => n))
      return listWidget(t('dashboard.widgets.meetingDensity', { defaultValue: '會議密度' }), () => navigate('/calendar'), t('dashboard.noEvents', { defaultValue: '暫無活動' }),
        rows.length === 0 ? null : (
          <div className="dv2-bar-stack">{rows.map(([k, n]) => barRow(k, n, maxN, 'var(--color-primary)', t('dashboard.meetingCount', { defaultValue: '{{count}} 場', count: n })))}</div>
        ), <SvcIcon name="calendar" size={15} />)
    }
    return null
  }

  // shell 先、內容後：第一格唔 render widget grid，令 sidebar + bottom nav 即刻上。
  // 呢個 gate 一定要擺喺全部 hooks 之後（下面已經冇 hooks，全部喺上面）。
  if (!contentReady) return null

  return (
    <div className="dv2-page">
      <div className="dv2-toolbar">
        <div>
          <h1 className="dv2-greeting">{greeting}</h1>
          <p className="dv2-date">{new Date().toLocaleDateString(i18n.language, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
        </div>
      </div>

      {/* AI 洞察摘要 — 頂部全寬獨立 section（唔喺 widget grid 內） */}
      <section className="dv2-ai-hero">
        {renderWidget('ai')}
      </section>

      {/* Default order = Stat×4, List×3, Table, then new widgets (12-col packing).
          In customize mode drag handles reorder — spans are per-class so packing holds. */}
      <div className={`dv2-grid ${customizeMode ? 'customizing' : ''}`}>
        {widgetOrder.map(wid => {
          if (wid === 'ai') return null
          // Key Metrics (stats) widgets removed — skip any stale saved ids
          if (wid.startsWith('stats:')) return null
          // v6.93: project-centric — deal widgets removed; also guard against stale saved widget ids
          if (!ALL_WIDGETS.some(w => w.id === wid) && !wid.startsWith('stats:')) return null
          return has(wid) ? renderWidget(wid) : null
        })}
      </div>

      {/* 底部操作區 — 自訂版面 / 新增小工具（捲到最後先見到） */}
      <div className="dv2-footer-actions">
        <button
          className={`dv2-btn ${customizeMode ? 'dv2-btn-active' : 'dv2-btn-secondary'}`}
          onClick={() => { setCustomizeMode(v => !v); showToast(customizeMode ? t('dashboard.exitCustomize', { defaultValue: '已退出自訂模式' }) : t('dashboard.customizeHint', { defaultValue: '自訂版面模式已開啟，拖曳可調整排序' })) }}
        >
          <SvcIcon name="layout-grid" size={14} /> {customizeMode ? t('dashboard.doneCustomizing', { defaultValue: '完成自訂' }) : t('dashboard.customize', { defaultValue: '自訂版面' })}
        </button>
        <button className="dv2-btn dv2-btn-primary" onClick={() => { setWidgetSearch(''); setAddWidgetOpen(true) }}>
          <SvcIcon name="plus" size={14} /> {t('dashboard.addWidget', { defaultValue: '新增小工具' })}
        </button>
      </div>

      {addWidgetOpen && (
        <div className="dv2-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setAddWidgetOpen(false) }}>
          <div className="dv2-modal">
            <div className="dv2-modal-head">
              <h3>{t('dashboard.manageWidgets', { defaultValue: '管理小工具' })}</h3>
              <button className="dv2-modal-x" onClick={() => setAddWidgetOpen(false)}><SvcIcon name="x" size={16} /></button>
            </div>
            <div className="dv2-modal-body">
              <input
                className="dv2-widget-search"
                placeholder={t('dashboard.searchWidgets', { defaultValue: '搜尋小工具...' })}
                value={widgetSearch}
                onChange={(e) => setWidgetSearch(e.target.value)}
              />
              {WIDGET_GROUPS.map(g => {
                const widgets = ALL_WIDGETS.filter(w => w.group === g.key)
                const visible = widgetSearch ? widgets.filter(w => t(w.labelKey, { defaultValue: w.labelKey }).toLowerCase().includes(widgetSearch.toLowerCase())) : widgets
                if (visible.length === 0) return null
                return (
                  <div key={g.key} className="dv2-widget-group">
                    <div className="dv2-widget-group-title">{t(g.labelKey, { defaultValue: g.labelKey })}</div>
                    {visible.map(w => (
                      <label key={w.id} className="dv2-widget-option">
                        <input type="checkbox" checked={has(w.id)} disabled={w.required} onChange={() => toggleWidget(w.id)} />
                        <span>{t(w.labelKey, { defaultValue: w.labelKey })}</span>
                        {w.required && <span className="dv2-widget-required">{t('dashboard.required', { defaultValue: '必要' })}</span>}
                      </label>
                    ))}
                  </div>
                )
              })}
            </div>
            <div className="dv2-modal-foot">
              <button className="dv2-btn dv2-btn-secondary" onClick={() => setAddWidgetOpen(false)}>{t('common.cancel', { defaultValue: '取消' })}</button>
              <button className="dv2-btn dv2-btn-primary" onClick={saveWidgetPrefs}>{t('common.save', { defaultValue: '儲存' })}</button>
            </div>
          </div>
        </div>
      )}

      {activityDrawer && (
        <div className="dv2-drawer-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setActivityDrawer(null) }}>
          <div className="dv2-drawer">
            <div className="dv2-modal-head">
              <h3>{activityDrawer.title}</h3>
              <button className="dv2-modal-x" onClick={() => setActivityDrawer(null)}><SvcIcon name="x" size={16} /></button>
            </div>
            <div className="dv2-modal-body">
              <div className="dv2-drawer-row"><SvcIcon name="clock" size={14} /><span>{fmtDT(activityDrawer.created_at)}</span></div>
              <div className="dv2-drawer-row"><SvcIcon name="building-2" size={14} /><span>{activityDrawer.company?.name || '—'}</span></div>
              <div className="dv2-drawer-row"><SvcIcon name="activity" size={14} /><span className="dv2-table-type-tag">{activityDrawer.type}</span></div>
              <p className="dv2-drawer-desc">{activityDrawer.description || t('dashboard.noDetailNotes', { defaultValue: '暫無詳細備註。' })}</p>
            </div>
            <div className="dv2-modal-foot">
              <button className="dv2-btn dv2-btn-secondary" onClick={() => setActivityDrawer(null)}>{t('common.close', { defaultValue: '關閉' })}</button>
              <button className="dv2-btn dv2-btn-primary" onClick={() => {
                const url = activityDrawer.id ? `/touchpoints/${activityDrawer.id}` : '/touchpoints'
                setActivityDrawer(null); navigate(url)
              }}>{t('common.viewDetails', { defaultValue: '查看完整記錄' })}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Portal section icon — auto per header keyword (system-applied portal style)
function SectionIcon({ kind }: { kind: string }) {
  const s = 13
  switch (kind) {
    case 'weather': return <SvcIcon name="ai-weather" size={s} style={{ color: 'var(--color-amber, #d97706)' }} />
    case 'calendar': return <SvcIcon name="calendar" size={s} style={{ color: 'var(--color-primary)' }} />
    case 'tasks': return <SvcIcon name="tasks" size={s} style={{ color: 'var(--color-amber, #d97706)' }} />
    case 'risk': return <SvcIcon name="alert-triangle" size={s} style={{ color: 'var(--color-danger, #dc2626)' }} />
    case 'opp': return <SvcIcon name="trending-up" size={s} style={{ color: 'var(--color-green, #16a34a)' }} />
    case 'crm': return <SvcIcon name="building-2" size={s} style={{ color: 'var(--color-purple, #7c3aed)' }} />
    default: return <SvcIcon name="sparkles" size={s} style={{ color: 'var(--ai-glow-1)' }} />
  }
}

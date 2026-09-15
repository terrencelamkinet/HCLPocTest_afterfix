import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import { useSecretarySettings, isInWorkingHours, enabledModuleKeys } from '../hooks/useSecretarySettings'
import SvcIcon from '../components/SvcIcon'

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────
interface Deal {
  id: string
  name: string
  amount: number | null
  status: string
  stage_id: string | null
  expected_close_date: string | null
  company_id: string | null
  updated_at: string
  created_at: string
}

interface Quote {
  id: string
  deal_id: string
  quote_number: string
  status: string
  total: number | null
  valid_until: string | null
  created_at: string
}

interface TaskItem {
  id: string
  title: string
  priority: string
  status: string
  due_date: string | null
}

interface ScheduleEvent {
  id: string
  title: string
  time: string
  location?: string
}

// ── Insight model (after aggregation) ──
interface RiskInsight {
  dealId: string
  dealName: string
  companyName: string
  amount: number
  quoteNumber: string
  daysIdle: number
  reason: string        // tooltip text ("why this?")
}

interface BriefingPayload {
  greeting: string
  summary: string  // compact trigger subtitle (no greeting prefix)
  content: string  // LLM-generated briefing (AI-app pipeline)
  slot: string
  risks: RiskInsight[]
  overdueTasks: TaskItem[]
  todayEvents: ScheduleEvent[]
  riskCount: number
  taskCount: number
  eventCount: number
  // 20-module data (Batch B/C)
  weather: any[]
  news: any[]
  traffic: any[]
  birthdays: any[]
  drafts: any[]
  expenses: any[]
  personal: any[]
  conflicts: any[]
  sentiment: any[]
  unread: any[]
  aiTip: string
}

// ── Helpers ──
const daysSince = (iso: string): number => {
  const d = new Date(iso)
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86400000))
}

const isOverdue = (due: string | null): boolean => {
  if (!due) return false
  const d = new Date(due)
  return d.getTime() < Date.now() - 86400000 // overdue by >1 day
}

const isToday = (time: string): boolean => {
  if (!time) return false
  const t = time.slice(0, 10)
  // HKT 牆鐘日期 (en-CA → YYYY-MM-DD) — 唔可以用 toISOString() (嗰個係 UTC)
  const today = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Asia/Hong_Kong',
  }).format(new Date())
  return t === today
}

const fmtMoney = (n: number | null): string => {
  if (n == null) return ''
  return `$${n.toLocaleString('en-US')}`
}

/**
 * HKO Open Data rhrread weather icon code → emoji.
 * Backend already passes the HKO icon number (e.g. 50=sunny, 53/54=cloudy,
 * 60-64=light rain/overcast with rain, 70-79=rain/thunder). Previously the
 * AI-briefing drawer hard-coded 🌤️ regardless of actual conditions — user
 * reported a sunny/daytime icon that didn't match reality. (2026-08-17)
 */
export function hkoWeatherEmoji(icon: number | string | null | undefined): string {
  const n = typeof icon === 'string' ? parseInt(icon, 10) : Number(icon)
  if (Number.isNaN(n)) return '🌤️'
  if (n <= 0) return '🌤️'
  // HKO icon groups (current-weather icon set, lower = clearer, higher = rainier)
  if (n <= 50) return '☀️'      // 50 = 太陽/天晴
  if (n === 51) return '🌤️'    // 部分時間有陽光
  if (n === 52) return '🌥️'    // 部分多雲
  if (n >= 53 && n <= 55) return '☁️'  // 多雲/密雲/陰
  if (n >= 60 && n <= 65) return '🌦️' // 毛毛雨/微雨/有雨
  if (n >= 70 && n <= 73) return '🌧️' // 雨
  if (n >= 74 && n <= 79) return '⛈️' // 大雨/雷雨
  if (n >= 80 && n <= 88) return '🌫️' // 霧/煙霞
  if (n >= 91) return '💨'      // 大風/強風
  return '☁️'                  // 未知 code → 多雲（保守,唔會誤報晴天）
}

/**
 * HKO rhrread icon code → i18n weather description key.
 * Lets the AI-briefing weather row show a human-readable condition (e.g.
 * 「多雲有雨」) so the temperature/icon clearly match reality instead of a
 * generic sunny label. Keys live under pages.briefing.weatherDesc.*
 */
export function weatherDescKey(icon: number | string | null | undefined): string {
  const n = typeof icon === 'string' ? parseInt(icon, 10) : Number(icon)
  if (Number.isNaN(n) || n <= 0) return 'pages.briefing.weatherDesc.unknown'
  if (n <= 50) return 'pages.briefing.weatherDesc.sunny'
  if (n === 51) return 'pages.briefing.weatherDesc.partlySunny'
  if (n === 52) return 'pages.briefing.weatherDesc.partlyCloudy'
  if (n >= 53 && n <= 55) return 'pages.briefing.weatherDesc.overcast'
  if (n >= 60 && n <= 65) return 'pages.briefing.weatherDesc.rainy'
  if (n >= 70 && n <= 73) return 'pages.briefing.weatherDesc.rain'
  if (n >= 74 && n <= 79) return 'pages.briefing.weatherDesc.thunder'
  if (n >= 80 && n <= 88) return 'pages.briefing.weatherDesc.fog'
  if (n >= 91) return 'pages.briefing.weatherDesc.windy'
  return 'pages.briefing.weatherDesc.overcast'
}

/** HKT (UTC+8) now — 所有 greeting / 日期判斷必須用呢個,唔可以用 browser 本地時間 */
export function hktNow(): Date {
  // Asia/Hong_Kong 無 DST,直接 +8h 再讀 UTC 欄位就係 HKT 牆鐘時間
  return new Date(Date.now() + 8 * 3600 * 1000)
}

/** Pick the active greeting slot for `now` (HKT) from backend slots. */
function currentGreetingSlot(slots: { key: string; emoji: string; start: string }[] | undefined) {
  const list = (slots && slots.length ? slots : [
    { key: 'morning', emoji: '🌅', start: '07:00' },
    { key: 'afternoon', emoji: '☀️', start: '12:00' },
    { key: 'evening', emoji: '🌆', start: '18:00' },
    { key: 'lateNight', emoji: '🌙', start: '00:00' },
  ])
  const toM = (hhmm: string) => {
    const [h, m] = hhmm.split(':').map(Number)
    return h * 60 + m
  }
  const now = hktNow()
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes()
  const sorted = [...list].sort((a, b) => toM(a.start) - toM(b.start))
  let current = sorted[sorted.length - 1]
  for (const s of sorted) {
    if (mins >= toM(s.start)) current = s
    else break
  }
  return current
}

// ── Component ──
export default function AIBriefingDrawer() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const secretary = useSecretarySettings()
  const settings = secretary.settings
  const mods = new Set(enabledModuleKeys(settings.modules))

  // Current greeting slot (from backend greeting_slots) — re-evaluated every minute
  const [greeting, setGreeting] = useState(() => currentGreetingSlot(settings.greeting_slots))
  useEffect(() => {
    const check = () => setGreeting(prev => {
      const next = currentGreetingSlot(settings.greeting_slots)
      return prev.key === next.key ? prev : next
    })
    const timer = setInterval(check, 60_000)
    return () => clearInterval(timer)
  }, [settings.greeting_slots])

  const inWorkingHours = isInWorkingHours(hktNow(), settings)
  const [expanded, setExpanded] = useState(false)
  const [payload, setPayload] = useState<BriefingPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [hasLoaded, setHasLoaded] = useState(false)

  // Typewriter state
  const [typing, setTyping] = useState(false)
  const [typedText, setTypedText] = useState('')
  const [showInsights, setShowInsights] = useState(false)

  // Inline editor state (per-risk)
  const [editorFor, setEditorFor] = useState<string | null>(null) // dealId
  const [drafting, setDrafting] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [sentOk, setSentOk] = useState(false)

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Tick overdue task → mark done (task list) + remove from briefing (delete effect) ──
  const [taskDoneBusy, setTaskDoneBusy] = useState<Record<string, boolean>>({})
  const handleTaskDone = useCallback(async (taskId: string) => {
    if (taskDoneBusy[taskId]) return
    setTaskDoneBusy(prev => ({ ...prev, [taskId]: true }))
    try {
      // Mark done in task list (MS To Do semantics — completed_at set server-side)
      await apiClient.patch(`/api/v1/crm/todo/tasks/${taskId}`, { status: 'done' })
      // Delete effect: drop the task from the overdue list in this briefing
      setPayload(prev => {
        if (!prev) return prev
        const overdueTasks = prev.overdueTasks.filter(t => t.id !== taskId)
        return { ...prev, overdueTasks, taskCount: overdueTasks.length }
      })
    } catch {
      // non-fatal — leave task visible on failure (user can retry)
    } finally {
      setTaskDoneBusy(prev => { const n = { ...prev }; delete n[taskId]; return n })
    }
  }, [taskDoneBusy])

  // ── Load briefing data ──
  const loadBriefing = useCallback(async () => {
    setLoading(true)
    try {
      // 1) existing briefing endpoint (schedule + tasks + ai_tip + LLM content)
      const brief = await apiClient.get<{
        schedule?: ScheduleEvent[]
        tasks?: TaskItem[]
        ai_tip?: string
        content?: string
        slot?: string
      }>('/api/v1/ai/briefing')

      // 2) open deals
      let deals: Deal[] = []
      try {
        const res = await apiClient.get<{ items?: Deal[] }>('/api/v1/crm/deals?status=open&limit=50')
        deals = res?.items || []
      } catch { /* non-fatal */ }

      // 3) sent quotes (pending reply)
      let quotes: Quote[] = []
      try {
        const res = await apiClient.get<{ items?: Quote[] }>('/api/v1/crm/quotes?limit=100')
        quotes = res?.items || []
      } catch { /* non-fatal */ }

      // ── Build insights ──
      // High-risk: deal open + has sent quote + deal idle > 7 days
      const quoteByDeal = new Map<string, Quote[]>()
      quotes.forEach(q => {
        const arr = quoteByDeal.get(q.deal_id) || []
        arr.push(q)
        quoteByDeal.set(q.deal_id, arr)
      })

      const risks: RiskInsight[] = []
      if (inWorkingHours && (mods.has('stale_deals') || mods.has('quote_tracking'))) {
        deals.forEach(d => {
          const dealQuotes = (quoteByDeal.get(d.id) || []).filter(q => q.status === 'sent' || q.status === 'pending')
          const idle = daysSince(d.updated_at || d.created_at)
          if (dealQuotes.length > 0 && idle >= 7) {
            const q = dealQuotes[0]
            risks.push({
              dealId: d.id,
              dealName: d.name,
              companyName: d.company_id || '',
              amount: d.amount != null ? Number(d.amount) : (q.total != null ? Number(q.total) : 0),
              quoteNumber: q.quote_number,
              daysIdle: idle,
              reason: `報價單 ${q.quote_number} 已發出 ${idle} 日未有回覆，金額 ${fmtMoney(q.total)}，建議主動跟進確認意願。`,
            })
          }
        })
      }
      risks.sort((a, b) => b.daysIdle - a.daysIdle)

      // Overdue tasks — task/project items are confined to working hours
      const tasks = inWorkingHours && mods.has('today_tasks')
        ? (brief?.tasks || []).filter(t => t.status !== 'done' && isOverdue(t.due_date)).slice(0, 5)
        : []

      // Today's events
      const events = mods.has('meetings')
        ? (brief?.schedule || []).filter(e => isToday(e.time)).slice(0, 5)
        : []

      // 4) 20-module briefing (Batch B/C — weather/news/traffic/birthdays/etc)
      let extra: Record<string, any[]> = {}
      try {
        const res = await apiClient.get<Record<string, any>>('/api/v1/ai-secretary/briefing')
        extra = (res || {}) as Record<string, any[]>
      } catch { /* non-fatal */ }
      const weather = Array.isArray(extra.weather) ? extra.weather : []
      const news = Array.isArray(extra.news_industry) ? extra.news_industry : []
      const traffic = Array.isArray(extra.traffic_commute) ? extra.traffic_commute : []
      const birthdays = Array.isArray(extra.birthdays) ? extra.birthdays : []
      const drafts = Array.isArray(extra.email_draft_review) ? extra.email_draft_review : []
      const expenses = Array.isArray(extra.expense_reminders) ? extra.expense_reminders : []
      const personal = Array.isArray(extra.personal_reminders) ? extra.personal_reminders : []
      const conflicts = Array.isArray(extra.calendar_conflicts) ? extra.calendar_conflicts : []
      const sentiment = Array.isArray(extra.customer_sentiment) ? extra.customer_sentiment : []
      const unread = Array.isArray(extra.unread_messages) ? extra.unread_messages : []

      const riskCount = risks.length
      const taskCount = tasks.length
      const eventCount = events.length

      const parts: string[] = []
      if (riskCount > 0) parts.push(t('pages.briefing.riskItem', { count: riskCount }))
      if (taskCount > 0) parts.push(t('pages.briefing.taskItem', { count: taskCount }))
      if (eventCount > 0) parts.push(t('pages.briefing.meetingItem', { count: eventCount }))
      if (weather.length > 0) {
        const w = weather[0]
        parts.push(t('pages.briefing.weatherSummary', { temp: w.temperature ?? '', hum: w.humidity ?? '' }))
      }
      if (news.length > 0) parts.push(t('pages.briefing.newsSummary', { count: news.length }))
      if (traffic.length > 0) parts.push(t('pages.briefing.trafficSummary', { count: traffic.length }))
      if (birthdays.length > 0) parts.push(t('pages.briefing.birthdaySummary', { count: birthdays.length }))
      if (drafts.length > 0) parts.push(t('pages.briefing.draftSummary', { count: drafts.length }))
      if (expenses.length > 0) parts.push(t('pages.briefing.expenseSummary', { count: expenses.length }))
      if (personal.length > 0) parts.push(t('pages.briefing.personalSummary', { count: personal.length }))
      if (conflicts.length > 0) parts.push(t('pages.briefing.conflictSummary', { count: conflicts.length }))
      if (sentiment.length > 0 && sentiment[0].negative_pct != null) {
        parts.push(t('pages.briefing.sentimentSummary', { neg: sentiment[0].negative_pct }))
      }
      if (unread.length > 0) parts.push(t('pages.briefing.unreadSummary', { count: unread.length }))
      if (parts.length === 0) parts.push(t('pages.briefing.noItems'))

      setPayload({
        greeting: t(`pages.briefing.${greeting.key}Greeting`, { items: parts.join(i18n.language === 'en' ? ', ' : '，') }),
        summary: parts.join(' · '),
        content: brief?.content || '',
        slot: brief?.slot || '',
        risks,
        overdueTasks: tasks,
        todayEvents: events,
        riskCount,
        taskCount,
        eventCount,
        weather, news, traffic, birthdays, drafts, expenses, personal, conflicts, sentiment, unread,
        aiTip: brief?.ai_tip || '',
      })
    } catch {
      setPayload({
        greeting: t(`pages.briefing.${greeting.key}GreetingError`),
        summary: t(`pages.briefing.${greeting.key}GreetingError`),
        content: '', slot: '',
        risks: [], overdueTasks: [], todayEvents: [],
        riskCount: 0, taskCount: 0, eventCount: 0,
        weather: [], news: [], traffic: [], birthdays: [], drafts: [], expenses: [],
        personal: [], conflicts: [], sentiment: [], unread: [],
        aiTip: '',
      })
    } finally {
      setLoading(false)
    }
  }, [greeting.key, inWorkingHours, mods])

  // ── Typewriter effect when drawer opens ──
  const animationPlayedRef = useRef(false)

  useEffect(() => {
    if (!expanded || !payload) return

    // aiTip 併入 summary — greeting 之後以 💡 換行顯示
    const fullText = payload.greeting + (payload.aiTip ? `\n\n💡 ${payload.aiTip}` : '')

    // If animation already played once, just show full text instantly
    if (animationPlayedRef.current) {
      setTypedText(fullText)
      setShowInsights(true)
      return
    }

    setTyping(true)
    setTypedText('')
    setShowInsights(false)
    let i = 0
    const text = fullText
    timerRef.current = setInterval(() => {
      i += 2
      setTypedText(text.slice(0, i))
      if (i >= text.length) {
        if (timerRef.current) clearInterval(timerRef.current)
        setTyping(false)
        animationPlayedRef.current = true
        setTimeout(() => setShowInsights(true), 250)
      }
    }, 24)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [expanded, payload])

  // ── Toggle expand ──
  const toggleExpand = () => {
    setExpanded(prev => !prev)
    if (!hasLoaded) {
      setHasLoaded(true)
      loadBriefing()
    }
  }

  // Preload briefing on mount so the trigger text is ready
  useEffect(() => {
    loadBriefing()
  }, [loadBriefing])

  // ── Inline draft (simulated AI drafting, graduated autonomy) ──
  const startDraft = (risk: RiskInsight) => {
    setEditorFor(risk.dealId)
    setDrafting(true)
    setDraftText('')
    setSentOk(false)

    const draft = i18n.language === 'en'
      ? `Dear ${risk.companyName} team,\n\nRegarding the quotation ${risk.quoteNumber} (${fmtMoney(risk.amount)}) sent earlier, we would like to follow up on its current status. If you have any questions or require assistance, I am available for a 15-minute call to provide further details.\n\nLooking forward to your reply. Thank you!`
      : `您好，${risk.companyName} 團隊：\n\n關於早前發出的報價單 ${risk.quoteNumber}（${fmtMoney(risk.amount)}），謹此了解目前的進度。如有任何疑問或需要協助，我隨時可以安排 15 分鐘電話詳細說明。\n\n期待您的回覆，謝謝！`
    let j = 0
    timerRef.current = setInterval(() => {
      j += 3
      setDraftText(draft.slice(0, j))
      if (j >= draft.length) {
        if (timerRef.current) clearInterval(timerRef.current)
        setDrafting(false)
      }
    }, 18)
  }

  const cancelDraft = () => {
    if (timerRef.current) clearInterval(timerRef.current)
    setEditorFor(null)
    setDrafting(false)
    setDraftText('')
    setSentOk(false)
  }

  const sendDraft = () => {
    if (timerRef.current) clearInterval(timerRef.current)
    setSentOk(true)
    setDrafting(false)
  }

  // ── Render trigger widget ──
  return (
    <div className={`ai-brief-card ai-card${loading ? ' is-thinking' : ''}`}>
      {/* Trigger widget — compact, non-intrusive */}
      <div
        onClick={toggleExpand}
        role="button"
        aria-expanded={expanded}
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') toggleExpand() }}
        className="ab-trigger"
      >
        {/* Pulse orb */}
        <div className="ab-orb-wrap">
          <div className="ab-orb-pulse" />
          <div className="ab-orb-core">
            <SvcIcon name="sparkles" size={13} className="ab-orb-sparkles" />
          </div>
        </div>
        <div className="ab-trigger-text">
          <div className="ab-trigger-title">
            {greeting.emoji} {t('greeting.' + greeting.key, { name: user?.displayName || user?.email?.split('@')[0] || '' })}
          </div>
          <div className="ab-trigger-summary">
            {loading ? t('common.loading') : payload ? payload.summary : t('pages.briefing.triggerFallback')}
          </div>
        </div>
        <span className="ab-trigger-pill">
          {expanded ? t('pages.briefing.collapse') : t('pages.briefing.more')} <SvcIcon name="chevron-down" size={13} className="ab-chevron" style={{ transform: expanded ? 'rotate(180deg)' : 'none' }} />
        </span>
      </div>

      {/* Expandable panel — push-down (推移式), inline in document flow */}
      <div
        className="ab-panel"
        style={{
          gridTemplateRows: expanded ? '1fr' : '0fr',
        }}
      >
        <div
          className="ab-panel-clip"
          style={{
            visibility: expanded ? 'visible' : 'hidden',
            transition: expanded ? 'visibility 0s' : 'visibility 0s linear 320ms',
          }}
        >
          <div
            aria-hidden={!expanded}
            {...(!expanded ? { inert: true } : {})}
            className="ab-panel-card"
            style={{
            animation: expanded ? 'ai-fadein 0.3s ease' : 'none',
          }}>
          {/* Panel header */}
          <div className="ab-panel-head">
            <span className="ab-panel-title">
              {t('pages.briefing.title')}
            </span>
            <span className="ab-panel-head-spacer" />
            <button
              onClick={e => { e.stopPropagation(); setExpanded(false) }}
              aria-label={t('pages.briefing.collapse')}
              className="ab-close-btn"
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-divider)'; e.currentTarget.style.color = 'var(--color-text)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface-offset)'; e.currentTarget.style.color = 'var(--color-text-faint)' }}
            >
              <SvcIcon name="x" size={14} />
            </button>
          </div>

          {/* Loading skeleton */}
          {loading && !payload && (
            <div className="ab-skeleton-wrap">
              <div className="animate-pulse ab-skeleton-bar" style={{ height: 44 }} />
              <div className="animate-pulse ab-skeleton-bar" style={{ height: 90 }} />
              <div className="animate-pulse ab-skeleton-bar" style={{ height: 90 }} />
            </div>
          )}

          {/* AI conversation summary */}
          {payload && (
            <div className="ab-summary-wrap">
              {typing && (
                <div className="ai-typing-dots ab-typing-dots">
                  <span className="ab-typing-dot" />
                  <span className="ab-typing-dot" />
                  <span className="ab-typing-dot" />
                </div>
              )}
              <p className="ab-summary-text">
                {typedText}
                {typing && <span className="ab-caret">&nbsp;</span>}
              </p>
            </div>
          )}

          {/* Insights (progressive disclosure) */}
          {showInsights && payload && (
            <div className="ab-insights">
              {/* ── High-risk deals ── */}
              {payload.risks.length > 0 && (
                <InsightSection
                  icon={<SvcIcon name="alert-triangle" size={14} className="ab-ic-notification" />}
                  title={t('pages.briefing.riskSection', { count: payload.riskCount })}
                  badge={t('pages.briefing.riskBadge')}
                  badgeColor="var(--color-notification)"
                  defaultOpen
                >
                  {payload.risks.map(risk => (
                    <div key={risk.dealId} className="ab-risk-item">
                      <p className="ab-risk-text">
                        <strong>{risk.dealName}</strong> {t('pages.briefing.riskDesc')}
                        <span
                          className="ab-why"
                          data-tooltip={risk.reason}
                        >
                          <span className="ab-why-badge">?</span>
                          {t('pages.briefing.whyThis')}
                        </span>
                      </p>

                      {editorFor !== risk.dealId ? (
                        <button
                          onClick={() => startDraft(risk)}
                          className="ab-draft-btn"
                          onMouseEnter={e => (e.currentTarget.style.background = 'rgba(124,93,250,0.18)')}
                          onMouseLeave={e => (e.currentTarget.style.background = 'rgba(124,93,250,0.10)')}
                        >
                          ✨ {t('pages.briefing.draftEmail')}
                        </button>
                      ) : (
                        <div className="ab-editor">
                          <div className="ab-editor-head">
                            {sentOk ? t('pages.briefing.sentRecorded') : drafting ? t('pages.briefing.aiDrafting') : t('pages.briefing.draftReady')}
                            <button onClick={cancelDraft} className="ab-editor-close">
                              <SvcIcon name="x" size={13} />
                            </button>
                          </div>
                          <textarea
                            value={draftText}
                            onChange={e => setDraftText(e.target.value)}
                            readOnly={drafting || sentOk}
                            rows={5}
                            className="ab-editor-textarea"
                          />
                          {!sentOk && (
                            <div className="ab-editor-foot">
                              <button
                                onClick={cancelDraft}
                                className="ab-btn-cancel"
                              >
                                {t('pages.briefing.cancel')}
                              </button>
                              <button
                                onClick={sendDraft}
                                disabled={drafting || draftText.trim() === ''}
                                className="ab-btn-send"
                                style={{ opacity: drafting || draftText.trim() === '' ? 0.5 : 1 }}
                              >
                                <SvcIcon name="send" size={12} /> {t('pages.briefing.sendEmail')}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </InsightSection>
              )}

              {/* ── Overdue tasks ── */}
              {payload.overdueTasks.length > 0 && (
                <SectionRow
                  icon={<SvcIcon name="check-square" size={14} className="ab-ic-warning" />}
                  label={t('pages.briefing.taskSection', { count: payload.taskCount })}
                >
                  {payload.overdueTasks.map(task => (
                    <label key={task.id} className="ab-task-row">
                      <input
                        type="checkbox"
                        className="ab-task-check"
                        checked={false}
                        disabled={!!taskDoneBusy[task.id]}
                        onChange={() => handleTaskDone(task.id)}
                      />
                      <span className="ab-task-title">{task.title}</span>
                      <span className="ab-badge-overdue">
                        {task.due_date ? t('pages.briefing.overdueDays', { count: daysSince(task.due_date) }) : t('pages.briefing.overduePlain')}
                      </span>
                    </label>
                  ))}
                </SectionRow>
              )}

              {/* ── Today's events ── */}
              {payload.todayEvents.length > 0 && (
                <SectionRow
                  icon={<SvcIcon name="calendar" size={14} className="ab-ic-blue" />}
                  label={t('pages.briefing.eventSection', { count: payload.eventCount })}
                >
                  {payload.todayEvents.map(ev => (
                    <div key={ev.id} className="ab-event-row">
                      <span className="ab-event-time">
                        {ev.time.length >= 16 ? ev.time.slice(11, 16) : ev.time}
                      </span>
                      <span className="ab-event-title">{ev.title}</span>
                      {ev.location && <span className="ab-event-loc">{ev.location}</span>}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Weather ── */}
              {payload.weather.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">{hkoWeatherEmoji(payload.weather[0]?.icon)}</span>}
                  label={t('pages.briefing.weatherSection')}
                >
                  {payload.weather.slice(0, 2).map((w: any, i: number) => (
                    <div key={i} className="ab-weather-row">
                      <span className="ab-weather-emoji">{hkoWeatherEmoji(w.icon)}</span>
                      <span className="ab-weather-desc">{t(weatherDescKey(w.icon))}</span>
                      <span className="ab-weather-place">
                        {w.place}: {w.temperature != null ? `${w.temperature}°C` : ''}
                      </span>
                      {w.humidity != null && <span className="ab-weather-hum">{t('pages.briefing.weatherHumidity', { hum: w.humidity })}</span>}
                      {w.rainfall_mm != null && <span className="ab-weather-rain">{t('pages.briefing.weatherRain', { mm: w.rainfall_mm })}</span>}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Schedule conflicts ── */}
              {payload.conflicts.length > 0 && (
                <SectionRow
                  icon={<SvcIcon name="alert-triangle" size={14} className="ab-ic-notification" />}
                  label={t('pages.briefing.conflictSection')}
                >
                  {payload.conflicts.map((c: any, i: number) => (
                    <div key={i} className="ab-conflict-item">
                      <span className="ab-conflict-text">
                        <strong>{c.event_a}</strong> ↔ <strong>{c.event_b}</strong>
                      </span>
                      <span className="ab-conflict-meta">
                        {c.overlap_start ? t('pages.briefing.conflictOverlap', { time: c.overlap_start.length >= 16 ? c.overlap_start.slice(11, 16) : c.overlap_start }) : ''}
                      </span>
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Traffic ── */}
              {payload.traffic.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">🚗</span>}
                  label={t('pages.briefing.trafficSection')}
                >
                  {payload.traffic.slice(0, 4).map((tr: any, i: number) => (
                    <div key={i} className="ab-traffic-text">
                      {tr.text || tr.ChinText || tr.EngText || ''}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Birthdays ── */}
              {payload.birthdays.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">🎂</span>}
                  label={t('pages.briefing.birthdaySection')}
                >
                  {payload.birthdays.slice(0, 5).map((b: any) => (
                    <div key={b.id} className="ab-bday-row">
                      <span className="ab-bday-name">{b.name}</span>
                      {b.company_name && <span className="ab-bday-company">{b.company_name}</span>}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Drafts to review ── */}
              {payload.drafts.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">✉️</span>}
                  label={t('pages.briefing.draftSection')}
                >
                  {payload.drafts.slice(0, 5).map((d: any) => (
                    <div key={d.id} className="ab-draft-item">
                      <span className="ab-draft-title">{d.title}</span>
                      <span className="ab-draft-content">
                        {d.content || ''}
                      </span>
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Expenses ── */}
              {payload.expenses.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">🧾</span>}
                  label={t('pages.briefing.expenseSection')}
                >
                  {payload.expenses.slice(0, 5).map((e: any) => (
                    <div key={e.id} className="ab-expense-row">
                      <span className="ab-expense-title">{e.title}</span>
                      <span className="ab-expense-amount">
                        {e.amount != null ? `$${Number(e.amount).toLocaleString()}` : ''} {e.currency || ''}
                      </span>
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Personal reminders ── */}
              {payload.personal.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">📌</span>}
                  label={t('pages.briefing.personalSection')}
                >
                  {payload.personal.slice(0, 5).map((p: any) => (
                    <div key={p.id} className="ab-personal-item">
                      <span className="ab-personal-title">{p.title}</span>
                      {p.content && <span className="ab-personal-content">{p.content}</span>}
                      {p.remind_at && <span className="ab-personal-remind">⏰ {p.remind_at.slice(0, 16).replace('T', ' ')}</span>}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Unread messages ── */}
              {payload.unread.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">💬</span>}
                  label={t('pages.briefing.unreadSection')}
                >
                  {payload.unread.slice(0, 5).map((u: any, i: number) => (
                    <div key={i} className="ab-unread-item">
                      <span className="ab-unread-text">
                        <strong>{u.from || ''}</strong>{u.subject ? ` — ${u.subject}` : ''}
                      </span>
                      {u.snippet && <span className="ab-unread-snippet">{u.snippet}</span>}
                    </div>
                  ))}
                </SectionRow>
              )}

              {/* ── Industry news ── */}
              {payload.news.length > 0 && (
                <SectionRow
                  icon={<span className="ab-emoji-icon">📰</span>}
                  label={t('pages.briefing.newsSection')}
                >
                  {payload.news.slice(0, 5).map((n: any, i: number) => (
                    <a
                      key={i}
                      href={n.link || '#'}
                      target="_blank"
                      rel="noreferrer"
                      className="ab-news-link"
                    >
                      <span className="ab-news-title">{n.title}</span>
                      <span className="ab-news-feed">{n.feed || ''}</span>
                    </a>
                  ))}
                </SectionRow>
              )}

              {/* ── Customer sentiment ── */}
              {payload.sentiment.length > 0 && payload.sentiment[0].total_messages > 0 && (
                <InsightSection
                  icon={<span className="ab-emoji-icon">🙂</span>}
                  title={t('pages.briefing.sentimentSection')}
                  badge={""}
                  badgeColor="var(--color-text-faint)"
                >
                  <div className="ab-sentiment-row">
                    <span>😊 {payload.sentiment[0].positive ?? 0}</span>
                    <span>😐 {payload.sentiment[0].neutral ?? 0}</span>
                    <span>😠 {payload.sentiment[0].negative ?? 0}</span>
                    {payload.sentiment[0].negative_pct != null && payload.sentiment[0].negative_pct >= 30 && (
                      <span className="ab-sentiment-warn">{t('pages.briefing.riskBadge')}</span>
                    )}
                  </div>
                </InsightSection>
              )}

              {/* ── Empty state ── */}
              {payload.risks.length === 0 && payload.overdueTasks.length === 0 && payload.todayEvents.length === 0 &&
                payload.weather.length === 0 && payload.news.length === 0 && payload.traffic.length === 0 &&
                payload.birthdays.length === 0 && payload.drafts.length === 0 && payload.expenses.length === 0 &&
                payload.personal.length === 0 && payload.conflicts.length === 0 && payload.sentiment.length === 0 &&
                payload.unread.length === 0 && (
                <div className="ab-empty">
                  {t('pages.briefing.allGood')}
                </div>
              )}

              {/* Footer */}
              <div className="ab-footer">
                <SvcIcon name="history" size={11} />
                <span>{t('pages.briefing.footer')}</span>
                <button
                  onClick={loadBriefing}
                  disabled={loading}
                  className="ab-refresh-btn"
                >
                  <SvcIcon name="refresh-cw" size={11} style={{ animation: loading ? 'ai-spin 1s linear infinite' : 'none' }} /> {t('pages.briefing.refresh')}
                </button>
              </div>
            </div>
          )}
          </div>
        </div>
      </div>

      {/* Global keyframes + tooltip styles */}
      <style>{`
        @keyframes ai-pulse {
          0% { box-shadow: 0 0 0 0 rgba(20,110,245,0.45); }
          70% { box-shadow: 0 0 0 12px rgba(20,110,245,0); }
          100% { box-shadow: 0 0 0 0 rgba(20,110,245,0); }
        }
        @keyframes ai-bounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
          30% { transform: translateY(-4px); opacity: 1; }
        }
        @keyframes ai-fadein {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes ai-spin { to { transform: rotate(360deg); } }
        [data-tooltip] { position: relative; }
        [data-tooltip]:hover::after {
          content: attr(data-tooltip);
          position: absolute; bottom: calc(100% + 8px); left: 0;
          background: #1e1b2e; color: #e4e4f0;
          font-size: 11px; line-height: 1.5; font-weight: 500;
          padding: 8px 10px; border-radius: 8px;
          width: 240px; z-index: 50;
          box-shadow: 0 4px 16px rgba(0,0,0,0.25);
          white-space: normal;
        }
        [data-tooltip]:hover::before {
          content: ''; position: absolute; bottom: calc(100% + 2px); left: 18px;
          border: 5px solid transparent; border-top-color: #1e1b2e;
        }
      `}</style>
    </div>
  )
}

// ── Insight Section (accordion) ──
function InsightSection({
  icon,
  title,
  badge,
  badgeColor,
  defaultOpen,
  children,
}: {
  icon: React.ReactNode
  title: string
  badge: string
  badgeColor: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(!!defaultOpen)

  return (
    <div className="ab-section">
      <button
        onClick={() => setOpen(!open)}
        className="ab-section-btn"
      >
        {icon}
        <span className="ab-section-title">{title}</span>
        <span
          className="ab-section-badge"
          style={{
            background: `color-mix(in oklch, ${badgeColor} 14%, var(--color-surface))`,
            color: badgeColor,
          }}
        >
          {badge}
        </span>
        <SvcIcon name="chevron-down" size={14} className="ab-section-chevron" style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>
      {open && (
        <div className="ab-section-body">
          {children}
        </div>
      )}
    </div>
  )
}

// ── Section Row (direct-display, DailyBriefingCard style) ──
function SectionRow({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        padding: '10px 12px',
        borderRadius: 'var(--radius-md)',
        cursor: 'default',
        transition: 'background 150ms',
      }}
    >
      <div style={{
        width: 30, height: 30, borderRadius: 'var(--radius-sm)',
        background: 'var(--color-surface-offset)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, marginTop: 1,
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {label}
        </div>
        {children}
      </div>
    </div>
  )
}

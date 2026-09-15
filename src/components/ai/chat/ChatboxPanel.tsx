import { useState, useRef, useEffect, useCallback } from 'react'
import SvcIcon from '../../../components/SvcIcon'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../../lib/api'
import MarkdownMessage from '../../MarkdownRenderer'
import MessageTimestamp from './MessageTimestamp'
import LoadingIndicator from './LoadingIndicator'
import ErrorBanner from './ErrorBanner'
import ChatInput from './ChatInput'
import SessionSidebar from './SessionSidebar'
import type { SessionItem } from './SessionSidebar'
import type { StreamError } from './ErrorBanner'
import SlashMentionMenu from './SlashMentionMenu'
import type { SlashItem } from './SlashMentionMenu'
import ActionPreviewModal from '../../ActionPreviewModal'
import FollowUpChips from './core/FollowUpChips'
import {
  useSecretarySettings,
  useProviderHealth,
  getGreeting,
  isWithinWorkHours,
} from './core/AICoreHooks'
import './core/ai-core-v1.css'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  citations?: CitationSource[]
  followups?: string[]
}

interface CitationSource {
  id: string
  type: string
  title: string
  snippet: string
  updated_at?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DRAFT_KEY = 'nexus_chat_draft'
const MOBILE_BREAKPOINT = 768

const emptyPrompts = [
  '📊 總結今日 CRM 重點',
  '🔍 查詢近期跟進的客戶',
  '📋 今日待辦事項',
  '🎯 最需要關注的 Deal',
]

const suggestedPromptsCache = { prompts: emptyPrompts, ts: 0 }

const SLASH_TRIGGER_PROMPTS: Record<string, string> = {
  summarize: "Summarize today's CRM activity",
  find: 'Find ',
  'create-task': 'Create a task: ',
  'draft-email': 'Draft an email about ',
  pipeline: 'Show me the sales pipeline',
  reset: 'Reset our conversation',
}

let msgCounter = 0
function nextId(): string {
  msgCounter += 1
  return `msg_${Date.now()}_${msgCounter}`
}
function userMessage(content: string): ChatMessage {
  return { id: nextId(), role: 'user', content, timestamp: Date.now() }
}
function assistantMessage(content: string): ChatMessage {
  return { id: nextId(), role: 'assistant', content, timestamp: Date.now() }
}

// ---------------------------------------------------------------------------
// FAB
// ---------------------------------------------------------------------------

export function ChatboxToggleButton({ onClick, open }: { onClick: () => void; open: boolean }) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(false)
  const [pressed, setPressed] = useState(false)
  // Terrence 2026-09-08: Toggle AI chat icon 跟 bottom nav 中間管家 icon —
  // butler 圖 + 未讀通知 badge（同 mnav-center-btn / mnav-center-badge pattern）
  const [unreadCount, setUnreadCount] = useState(0)
  const fetchNotifs = useCallback(() => {
    apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count')
      .then(d => setUnreadCount(d?.unread_count || 0)).catch(() => {});
  }, [])
  useEffect(() => { fetchNotifs(); }, [fetchNotifs])
  useEffect(() => {
    const iv = setInterval(fetchNotifs, 60000)
    const onRead = () => fetchNotifs()
    window.addEventListener('nexus:notif-read', onRead)
    return () => { clearInterval(iv); window.removeEventListener('nexus:notif-read', onRead) }
  }, [fetchNotifs])

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setPressed(false) }}
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
      onTouchStart={() => setPressed(true)}
      onTouchEnd={() => setPressed(false)}
      aria-label={t('common.toggleAiChat')}
      aria-expanded={open}
      className={`fab-btn ${open ? 'fab-btn--open' : ''} cb-fab`}
      id="ai-fab"
      style={{
        transform: `scale(${pressed ? 0.92 : hovered ? 1.08 : 1})`,
        boxShadow: pressed
          ? '0 2px 8px rgba(0,0,0,0.18), 0 1px 3px rgba(0,0,0,0.1)'
          : '0 4px 16px rgba(0,0,0,0.2), 0 2px 6px rgba(0,0,0,0.12)',
      }}
    >
      <span className="cb-fab-icon" style={{
        transform: open ? 'rotate(90deg) scale(0.85)' : 'rotate(0deg) scale(1)',
      }}>
        {open ? <SvcIcon name="x" size={20} /> : (
          <img
            src={unreadCount > 0 ? '/assets/butler/notify_pose.png' : '/assets/butler/butler_idle.png'}
            alt=""
            className="cb-fab-logo"
          />
        )}
      </span>
      {!open && unreadCount > 0 && (
        <span className="cb-fab-badge" aria-label={`${unreadCount} 則未讀通知`}>
          {unreadCount > 9 ? '9+' : unreadCount}
        </span>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Message components
// ---------------------------------------------------------------------------

function UserMessageBubble({ msg, prevMsg }: { msg: ChatMessage; prevMsg?: ChatMessage }) {
  const prevSameRole = prevMsg && prevMsg.role === 'user' && (msg.timestamp - prevMsg.timestamp) < 180000
  return (
    <div className="cb-msg-user" style={{ marginTop: prevSameRole ? -12 : 0 }}>
      {/* Avatar + timestamp */}
      {!prevSameRole && (
        <div className="cb-msg-user-meta">
          <span className="cb-msg-time">
            {formatTime(msg.timestamp)}
          </span>
          <div className="cb-avatar-user">
            T
          </div>
        </div>
      )}
      <div className="cb-msg-user-bubble">
        {msg.content}
      </div>
    </div>
  )
}

function AiMessageBubble({ msg, prevMsg, hovered, onHover, onCopy, onRetry, onFeedback, feedback, isStreaming, onFollowUpSelect }: {
  msg: ChatMessage
  prevMsg?: ChatMessage
  hovered: boolean
  onHover: (v: boolean) => void
  onCopy: () => void
  onRetry: () => void
  onFeedback: (rating: 'up' | 'down') => void
  feedback?: 'up' | 'down'
  isStreaming?: boolean
  onFollowUpSelect?: (q: string) => void
}) {
  const prevSameRole = prevMsg && prevMsg.role === 'assistant' && (msg.timestamp - prevMsg.timestamp) < 180000

  return (
    <div
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      style={{ marginTop: prevSameRole ? -12 : 0 }}
    >
      <div className="cb-msg-ai-row">
        {/* Avatar */}
        {!prevSameRole && (
          <div className="cb-avatar-ai">
            <SvcIcon name="sparkles" size={13} />
          </div>
        )}
        <div className={`cb-msg-ai-body ai-card${isStreaming ? ' is-thinking' : ''}`}>
          {/* Timestamp */}
          {!prevSameRole && (
            <div className="cb-msg-ai-meta">
              <span className="cb-msg-time">
                Penguin AI · {formatTime(msg.timestamp)}
              </span>
            </div>
          )}
          {/* Content */}
          <div className="msg-ai-content cb-msg-ai-content">
            <MarkdownMessage content={msg.content} />
          </div>

          {/* Citations */}
          {msg.citations && msg.citations.length > 0 && (
            <CitationChip citations={msg.citations} />
          )}

          {/* Follow-up suggestions */}
          {!isStreaming && msg.followups && msg.followups.length > 0 && onFollowUpSelect && (
            <FollowUpChips suggestions={msg.followups} onSelect={onFollowUpSelect} />
          )}

          {/* Bottom toolbar */}
          <div
            className="ai-msg-toolbar cb-msg-ai-toolbar"
            style={{ opacity: hovered ? 1 : 0 }}
          >
            <GhostBtn onClick={onCopy} ariaLabel="Copy" icon={
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            } />
            <GhostBtn onClick={onRetry} ariaLabel="Regenerate" icon={
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            } />
            {feedback !== 'up' && (
              <GhostBtn onClick={() => onFeedback('up')} ariaLabel="Like"
                active={false}
                activeColor="var(--color-primary)"
                icon={
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
                }
              />
            )}
            {feedback !== 'down' && (
              <GhostBtn onClick={() => onFeedback('down')} ariaLabel="Dislike"
                active={false}
                activeColor="var(--color-notification)"
                icon={
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
                }
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function GhostBtn({ onClick, icon, ariaLabel, active, activeColor }: {
  onClick: () => void
  icon: React.ReactNode
  ariaLabel: string
  active?: boolean
  activeColor?: string
}) {
  return (
    <button onClick={onClick}
      aria-label={ariaLabel}
      title={ariaLabel}
      className="cb-ghost-btn"
      style={{ color: active ? (activeColor || 'var(--color-primary)') : 'var(--color-text-muted)' }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--color-surface-offset)' }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}
    >
      {icon}
    </button>
  )
}

function CitationChip({ citations }: { citations: CitationSource[] }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="cb-citation-wrap">
      <div className="cb-citation-chip"
        onClick={() => setExpanded(v => !v)}
        onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset-2)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
        Source: {citations.length} record{citations.length > 1 ? 's' : ''}
      </div>
      {expanded && (
        <div className="cb-citation-list">
          {citations.slice(0, 5).map((cit, ci) => (
            <div key={ci}
              onClick={() => {
                // 2026-09-15 SAST：cit.type / cit.id 來自 AI 輸出（唔可信）→ 只准白名單 route，
                // 其他一律唔開（之前 routes[cit.type] || cit.type 會放任意路徑出去）。
                const routes: Record<string, string> = { company: 'companies', contact: 'contacts', deal: 'deals', project: 'projects' }
                const route = routes[cit.type]
                if (!route) return
                window.open(`/${route}/${encodeURIComponent(String(cit.id))}`, '_blank', 'noopener,noreferrer')
              }}
              className="cb-citation-item"
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset-2)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
            >
              <span className="cb-citation-badge">{ci + 1}</span>
              <div className="cb-citation-body">
                <div className="cb-citation-title">
                  {cit.title}
                </div>
                <div className="cb-citation-type">
                  {cit.type}
                </div>
              </div>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="cb-citation-icon">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ prompts, onSelect }: { prompts: string[]; onSelect: (p: string) => void }) {
  return (
    <div className="cb-empty-state">
      <div className="cb-empty-icon">
        ✏️
      </div>
      <h1 className="cb-empty-title">
        How can I help?
      </h1>
      <p className="cb-empty-subtitle">
        Ask me anything about your CRM
      </p>
      <div className="cb-empty-prompts">
        {prompts.map(p => (
          <button key={p} onClick={() => onSelect(p)}
            className="cb-empty-prompt"
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-surface-2)' }}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main ChatboxPanel
// ---------------------------------------------------------------------------

export default function ChatboxPanel() {
  const { t } = useTranslation()

  // ── State ──
  const [isOpen, setIsOpen] = useState(false)
  const [activeContext, setActiveContext] = useState<{ type?: string; name?: string; id?: string } | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [error, setError] = useState<StreamError | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionList, setSessionList] = useState<SessionItem[]>([])
  const [showSidebar, setShowSidebar] = useState(false)
  const [loadingSession, setLoadingSession] = useState(false)
  const [hoveredMsgId, setHoveredMsgId] = useState<string | null>(null)
  const [feedbackMap, setFeedbackMap] = useState<Record<string, 'up' | 'down'>>({})
  const [suggestedPrompts, setSuggestedPrompts] = useState<string[]>(emptyPrompts)
  const [isMobile, setIsMobile] = useState(window.innerWidth < MOBILE_BREAKPOINT)
  const [animPhase, setAnimPhase] = useState<'closed' | 'opening' | 'open' | 'closing'>('closed')
  const [kbHeight, setKbHeight] = useState(0)
  // v2 (2026-09-09): batch drafts — 一個 stream 可以出多個 action events（actionQueue）
  const [actionQueue, setActionQueue] = useState<Array<{ tool_key: string; params: Record<string, unknown>; action_id?: string }>>([])

  // ── Tenant AI admin surfaces (AICore) ──
  // 2026-09-10 Terrence: 只有一個 AI — 移除 agent switcher；subscription 用量
  // 資訊搬去 Settings > 個人資料（ChatboxPanel 唔再顯示 quota bar）。
  const secretary = useSecretarySettings()
  const providers = useProviderHealth()
  const [showBanner, setShowBanner] = useState(true)

  // ── Slash / mention state ──
  const [menuType, setMenuType] = useState<'slash' | 'mention' | null>(null)
  const [menuIndex, setMenuIndex] = useState(0)
  const [menuQuery, setMenuQuery] = useState('')
  const [mentionResults, setMentionResults] = useState<{ id: string; label: string; type: string; sub: string }[]>([])

  // ── Refs ──
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const lastUserTextRef = useRef('')
  const panelRef = useRef<HTMLDivElement>(null)
  const [showCheatsheet, setShowCheatsheet] = useState(false)

  // ── Breakpoint listener ──
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const handler = (e: MediaQueryListEvent | MediaQueryList) => setIsMobile(e.matches)
    handler(mq)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // ── Open / Close animations ──
  const openPanel = useCallback(() => {
    setAnimPhase('opening')
    setIsOpen(true)
    // Start loading the latest session immediately so the panel opens
    // straight into it — no landing-page flash while animating in.
    setLoadingSession(true)
    setTimeout(() => setAnimPhase('open'), 320)
  }, [])

  const closePanel = useCallback(() => {
    setAnimPhase('closing')
    setTimeout(() => {
      setIsOpen(false)
      setAnimPhase('closed')
    }, 360) // must exceed animation duration so the close transition plays
  }, [])

  const togglePanel = useCallback(() => {
    if (animPhase === 'open') closePanel()
    else openPanel()
  }, [animPhase, openPanel, closePanel])

  // ── Auto-scroll ──
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
  }, [messages, isStreaming, streamingContent, isLoading])

  // ── Focus input when panel opens ──
  useEffect(() => {
    if (animPhase === 'open') {
      setTimeout(() => {
        const ta = document.querySelector<HTMLTextAreaElement>('.composer__input-row textarea')
        ta?.focus()
      }, 350)
    }
  }, [animPhase])

  // ── Lock body scroll while panel is open ──
  // (the AI chat is a modal overlay — the background must not scroll
  //  behind it, on desktop or mobile)
  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [isOpen])

  // ── Mobile: keep composer above the on-screen keyboard ──
  // visualViewport shrinks when the keyboard opens; dvh alone doesn't track
  // it reliably, so measure the delta and shrink the panel height accordingly.
  useEffect(() => {
    if (!isMobile || !isOpen) return
    const vv = window.visualViewport
    if (!vv) return
    const adjust = () => {
      const kh = window.innerHeight - vv.height
      setKbHeight(kh > 80 ? kh : 0) // 80px threshold — ignores URL-bar jitter
    }
    vv.addEventListener('resize', adjust)
    adjust()
    return () => vv.removeEventListener('resize', adjust)
  }, [isMobile, isOpen])

  // ── Escape to close ──
  useEffect(() => {
    if (animPhase !== 'open') return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePanel()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [animPhase, closePanel])

  // ── Cmd/Ctrl+K to toggle ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        togglePanel()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [togglePanel])

  // ── Listen for toggle event (from widget etc.) ──
  useEffect(() => {
    const handler = () => {
      if (isMobile) return // mobile 由 AiSearchPanel（企鵝管家）負責
      togglePanel()
    }
    window.addEventListener('toggle-ai-chat', handler)
    return () => window.removeEventListener('toggle-ai-chat', handler)
  }, [togglePanel, isMobile])

  // ── Listen for open-with-context event (Ask AI buttons on detail pages) ──
  useEffect(() => {
    const handler = (e: Event) => {
      // SPEC ask-ai-chat: mobile 由底部 nav 企鵝管家（AiSearchPanel）負責 —
      // 唔好喺度再開第二個 chatbox（兩個 panel 同時 mount 都會收到 event）
      if (isMobile) return
      const detail = (e as CustomEvent).detail
      openPanel()
      if (detail?.context) {
        const c = detail.context
        setActiveContext({ type: c.type || c.entity_type || 'entity', name: c.name || c.company_name || c.title || '此項目', id: c.id })
        // SPEC detail-v3: Ask AI = 開一個新 chat — AI 摘要以對話 message 展示（唔再係 pinned 卡）
        const etype = (c.type || c.entity_type || '').toLowerCase()
        const eid = c.id
        if (etype && eid && ['company', 'contact', 'project', 'task', 'touchpoint'].includes(etype)) {
          apiClient.post<{ summary: string; tags: { label: string; kind: string }[] }>('/api/v1/ai/entity-insight', { entity_type: etype, entity_id: eid })
            .then(r => {
              const name = c.name || c.company_name || c.title || '此項目'
              const tags = r?.tags || []
              const tagLines = tags.map((tg: { label: string; kind: string }) =>
                `${tg.kind === 'opportunity' ? '🎯' : tg.kind === 'risk' ? '⚠️' : 'ℹ️'} ${tg.label}`).join('\n')
              const content = [
                `我幫你整理咗 **${name}** 嘅 AI 摘要：`,
                '',
                r?.summary || '暫時未有摘要 — 可以直接問我',
                tagLines ? `\n${tagLines}` : '',
                '',
                '_仲想知多啲，直接喺度問我 👍_',
              ].join('\n')
              setMessages([assistantMessage(content)])
              setSessionId(null)
            })
            .catch(() => { /* insight 失敗 — chat 維持原狀 */ })
        }
      }
    }
    window.addEventListener('nexus:open-ai-panel', handler)
    return () => window.removeEventListener('nexus:open-ai-panel', handler)
  }, [openPanel, isMobile])

  // ── Load sessions as soon as the panel starts opening ──
  // (fires on 'opening' so the latest session loads during the
  // 320ms open animation → panel opens straight into it, no flash)
  useEffect(() => {
    if (animPhase !== 'opening') return
    loadSessions()
    const age = Date.now() - suggestedPromptsCache.ts
    if (age > 300000) {
      apiClient.get<{ prompts: string[] }>('/api/v1/ai/prompts/suggested')
        .then(r => {
          if (r?.prompts?.length) {
            setSuggestedPrompts(r.prompts)
            suggestedPromptsCache.prompts = r.prompts
            suggestedPromptsCache.ts = Date.now()
          }
        }).catch(() => {})
    } else if (suggestedPromptsCache.prompts.length) {
      setSuggestedPrompts(suggestedPromptsCache.prompts)
    }
    const saved = localStorage.getItem(DRAFT_KEY)
    if (saved) setInput(saved)
  }, [animPhase])

  // ── Load session list ──
  const loadSessions = useCallback(async () => {
    setLoadingSession(true)
    try {
      const resp = await apiClient.get<{ sessions: SessionItem[] }>('/api/v1/ai/sessions')
      const list = resp?.sessions || []
      setSessionList(list)
      const active = list.find(s => s.status === 'active') || list[0]
      // Must await: switchSession clears messages first; if we don't await,
      // the finally below flips loadingSession=false while messages is still
      // empty → landing page flashes before the session content arrives.
      if (active) await switchSession(active.session_id)
      else createNewSession()
    } catch {
      setMessages([assistantMessage("Hi! I'm Penguin AI. How can I help you today?")])
    } finally {
      setLoadingSession(false)
    }
  }, [])

  // ── Switch session ──
  const switchSession = useCallback(async (sid: string) => {
    setSessionId(sid)
    setShowSidebar(false)
    setLoadingSession(true)
    setMessages([])
    try {
      const resp = await apiClient.get<{ messages: any[] }>(`/api/v1/ai/sessions/${sid}/messages`)
      const msgs = resp?.messages || []
      if (msgs.length === 0) {
        setMessages([assistantMessage("Hi! I'm Penguin AI. How can I help you today?")])
      } else {
        setMessages(msgs.map((m: any) => ({
          id: m.id, role: m.role, content: m.content,
          timestamp: new Date(m.created_at || Date.now()).getTime(),
        })))
      }
    } catch {
      setMessages([assistantMessage("Hi! I'm Penguin AI. How can I help you today?")])
    } finally {
      setLoadingSession(false)
    }
  }, [])

  const createNewSession = useCallback(async () => {
    setSessionId(null)
    setMessages([])  // empty → shows the Landing page (EmptyState + suggested prompts)
    setShowSidebar(false)
    setError(null)
  }, [])

  // ── Session actions ──
  const renameSession = useCallback(async (sid: string, title: string) => {
    try { await apiClient.patch(`/api/v1/ai/sessions/${sid}`, { title }) } catch {}
    setSessionList(prev => prev.map(s => s.session_id === sid ? { ...s, title } : s))
  }, [])

  const togglePin = useCallback(async (sid: string, pinned: boolean) => {
    try {
      await apiClient.patch(`/api/v1/ai/sessions/${sid}`, { is_pinned: pinned })
      const resp = await apiClient.get<{ sessions: SessionItem[] }>('/api/v1/ai/sessions')
      if (resp?.sessions) setSessionList(resp.sessions)
    } catch {}
  }, [])

  const deleteSession = useCallback(async (sid: string) => {
    try {
      await apiClient.delete(`/api/v1/ai/sessions/${sid}`)
      setSessionList(prev => {
        const next = prev.filter(s => s.session_id !== sid)
        if (sid === sessionId) {
          const active = next.find(s => s.status === 'active') || next[0]
          if (active) switchSession(active.session_id)
          else createNewSession()
        }
        return next
      })
    } catch {}
  }, [sessionId])

  const exportSession = useCallback(async (sid: string) => {
    try {
      const resp = await apiClient.get<{ messages: any[] }>(`/api/v1/ai/sessions/${sid}/messages`)
      const msgs = resp?.messages || []
      const md = msgs.map((m: any) => `**${m.role}**: ${m.content}`).join('\n\n---\n\n')
      await navigator.clipboard.writeText(`# Chat Export\n\n${md}`)
    } catch {}
  }, [])

  // ── Streaming ──
  const abortStreaming = useCallback(() => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null }
    setIsStreaming(false)
    setIsLoading(false)
  }, [])

  const doStream = useCallback(async (text: string) => {
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const resp = await fetch('/api/v1/ai/chat/stream', {
        method: 'POST',
        // 2026-09-15 SAST：session 喺 httpOnly cookie，唔再手動帶 Authorization
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          messages: activeContext
            ? [{ role: 'system', content: `使用者正在查看 ${activeContext.name}（${activeContext.type}）。請以 CRM 助理身份，基於此客戶/實體背景回答問題。` }, { role: 'user', content: text }]
            : [{ role: 'user', content: text }],
          session_id: sessionId || null,
          agent_id: null,
        }),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
        throw new Error(errBody.detail || `Request failed with status ${resp.status}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''
      let fullReply = ''
      let newSessionId: string | null = null
      const msgCitations: CitationSource[] = []
      let msgFollowups: string[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n').map(l => l.replace('\r', ''))
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.text !== undefined) { fullReply += data.text; setStreamingContent(fullReply) }
              if (data.session_id) newSessionId = data.session_id
              if (data.citations && Array.isArray(data.citations)) {
                const existingIds = new Set(msgCitations.map(c => c.id))
                for (const cit of data.citations) {
                  if (!existingIds.has(cit.id)) { msgCitations.push(cit as CitationSource); existingIds.add(cit.id) }
                }
              }
              if (data.followups && Array.isArray(data.followups)) {
                msgFollowups = data.followups.map(String).slice(0, 3)
              }
              if (data.message) { setError({ type: 'streaming', message: data.message, retryable: true }) }
              if (data.action_id && data.tool_key) {
                const newAction = {
                  tool_key: data.tool_key,
                  params: data.params || {},
                  action_id: data.action_id,
                }
                setActionQueue(prev => {
                  // 一個 stream 多個 action events → 累積；同一 id 唔重複
                  if (prev.some(a => a.action_id === data.action_id)) return prev
                  const next = [...prev, newAction]
                  return next
                })
              }
            } catch { /* skip */ }
          }
        }
      }

      if (fullReply) {
        const reply: ChatMessage = {
          ...assistantMessage(fullReply),
          citations: msgCitations.length > 0 ? msgCitations : undefined,
          followups: msgFollowups.length > 0 ? msgFollowups : undefined,
        }
        setMessages(prev => [...prev, reply])
      }
      if (newSessionId && newSessionId !== sessionId) setSessionId(newSessionId)
      setStreamingContent('')
      try {
        const resp2 = await apiClient.get<{ sessions: SessionItem[] }>('/api/v1/ai/sessions')
        if (resp2?.sessions) setSessionList(resp2.sessions)
      } catch {}
    } catch (err: any) {
      const msg = err?.detail || err?.message || t('chat.errors.server')
      if (err.name === 'AbortError') {
        setError({ type: 'timeout', message: t('chat.errors.timeout'), retryable: true })
      } else if (err.name === 'TypeError' && msg.includes('fetch')) {
        setError({ type: 'network', message: t('chat.errors.network'), retryable: true })
      } else if (msg.includes('401') || msg.includes('Unauthorized') || msg.includes('token')) {
        setError({ type: 'auth', message: t('chat.errors.auth'), retryable: false })
      } else if (msg.includes('500') || msg.includes('503') || msg.includes('502') || msg.includes('service')) {
        setError({ type: 'server', message: msg, retryable: true })
      } else {
        setError({ type: 'streaming', message: msg, retryable: true })
      }
    } finally {
      setIsStreaming(false)
      setIsLoading(false)
      setStreamingContent('')
      abortRef.current = null
    }
  }, [sessionId, t, activeContext])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || isLoading || loadingSession) return
    setMessages(prev => [...prev, userMessage(text)])
    setInput('')
    localStorage.removeItem(DRAFT_KEY)
    lastUserTextRef.current = text
    setError(null)
    setIsLoading(true)
    setIsStreaming(true)
    setStreamingContent('')
    await doStream(text)
  }, [input, isLoading, loadingSession, doStream])

  const retryLastMessage = useCallback(async () => {
    const text = lastUserTextRef.current
    if (!text || isLoading || loadingSession) return
    setMessages(prev => [...prev, userMessage(text)])
    setError(null)
    setIsLoading(true)
    setIsStreaming(true)
    setStreamingContent('')
    await doStream(text)
  }, [isLoading, loadingSession, doStream])

  // ── Input change handler ──
  const handleInputChange = useCallback((val: string) => {
    setInput(val)
    localStorage.setItem(DRAFT_KEY, val)
  }, [])

  // ── Copy / Feedback ──
  const copyMessage = useCallback(async (content: string) => {
    try { await navigator.clipboard.writeText(content) } catch {}
  }, [])

  const sendFeedback = useCallback(async (messageId: string, rating: 'up' | 'down') => {
    setFeedbackMap(prev => ({ ...prev, [messageId]: rating }))
    try { await apiClient.post(`/api/v1/ai/messages/${messageId}/feedback`, { rating }) } catch {}
  }, [])

  const retryMessage = useCallback((msgIdx: number) => {
    const lastUserMsg = messages[msgIdx - 1]
    if (lastUserMsg?.role !== 'user') return
    setInput(lastUserMsg.content)
  }, [messages])

  // ── Slash commands ──
  const SLASH_COMMANDS: SlashItem[] = [
    { key: 'summarize', label: t('chat.slashCommands.summarize'), icon: '📊' },
    { key: 'find', label: t('chat.slashCommands.find'), icon: '🔍' },
    { key: 'create-task', label: t('chat.slashCommands.createTask'), icon: '📋' },
    { key: 'draft-email', label: t('chat.slashCommands.draftEmail'), icon: '✉️' },
    { key: 'pipeline', label: t('chat.slashCommands.pipeline'), icon: '📈' },
    { key: 'reset', label: t('chat.slashCommands.reset'), icon: '🔄' },
  ]

  // ── Panel style by breakpoint ──
  // Driven by animPhase, NOT isOpen — so 'closing' renders the collapsed
  // styles while the transition is still active (isOpen flips later).
  const visible = animPhase !== 'closed'
  const isClosing = animPhase === 'closing'
  const panelStyle: React.CSSProperties = isMobile
    ? {
        transform: isClosing
          ? 'translateY(100%)'
          : 'translateY(0)',
        transition: animPhase === 'opening' || animPhase === 'closing'
          ? 'transform 320ms cubic-bezier(0.16, 1, 0.3, 1)'
          : 'none',
        height: !visible ? 0 : `calc(95dvh - ${kbHeight}px)`,
        boxShadow: visible && !isClosing ? '0 -8px 32px rgba(0,0,0,0.2)' : 'none',
        // Closed (height 0) must also be invisible — otherwise the fixed
        // panel (inset:0; top:8dvh) leaks its header above the fold even
        // when collapsed, because overflow is visible and no opacity applied.
        visibility: visible ? 'visible' : 'hidden',
      }
    : {
        // 2026-09-10 Terrence: desktop panel 由 70dvh/top 15dvh → 95dvh/top 2dvh
        // （同 mobile sheet 一致 — 之前只改咗 mobile，desktop 冇變，用戶見到「冇高到」）
        height: visible ? '95dvh' : 0,
        ...(visible
          ? { top: '2dvh', right: 'max(24px, env(safe-area-inset-right, 24px))' }
          : { top: 0, right: 0 }),
        border: visible ? '1px solid var(--color-border)' : 'none',
        boxShadow: visible && !isClosing ? 'var(--shadow-lg)' : 'none',
        transform: isClosing
          ? 'scale(0.85) translateY(20px)'
          : 'scale(1) translateY(0)',
        opacity: isClosing ? 0 : 1,
        transition: animPhase === 'opening' || animPhase === 'closing'
          ? 'transform 280ms cubic-bezier(0.16, 1, 0.3, 1), opacity 280ms cubic-bezier(0.16, 1, 0.3, 1), height 0s'
          : 'none',
      }

  // ── Render ──
  return (
    <>
      {/* FAB */}
      <ChatboxToggleButton onClick={togglePanel} open={isOpen} />

      {/* Overlay backdrop for mobile */}
      {isMobile && isOpen && (
        <div onClick={closePanel}
          className="cb-backdrop"
        />
      )}

      {/* Panel */}
      <div ref={panelRef}
        className={`cb-panel ${isMobile ? 'cb-panel--mobile' : 'cb-panel--desktop'}`}
        style={panelStyle as React.CSSProperties}
        role="dialog"
        aria-label={t('nav.aiChat')}
        aria-hidden={!isOpen}
      >
        {/* ── Header ── */}
        {isOpen && (
          <div className="cb-header">
            {/* Drag handle for mobile */}
            {isMobile && (
              <div className="cb-header-handle" />
            )}
            <div className="cb-header-logo">
              <SvcIcon name="sparkles" size={14} />
            </div>
            <div className="cb-header-titles">
              <div className="cb-header-title">
                Penguin AI
              </div>
              <div className="cb-header-subtitle">
                CRM Assistant
              </div>
            </div>
            {/* 2026-09-10 Terrence: 只有一個 AI — 移除 agent switcher（原「預設助手」下拉） */}
            <button onClick={createNewSession} aria-label={t('chat.newChat')} title={t('chat.newChat')}
              className="cb-header-btn"
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              <SvcIcon name="plus" size={15} />
            </button>

            {/* Session history toggle — Clock button on mobile, sidebar toggle on desktop */}
            {isMobile ? (
              <button onClick={() => setShowSidebar(v => !v)} aria-label={t('chat.sessionList')} title={t('chat.sessionList')}
                className="cb-header-btn"
                style={{ color: showSidebar ? 'var(--color-primary)' : 'var(--color-text-muted)' }}>
                <SvcIcon name="clock" size={15} />
              </button>
            ) : (
              <SessionSidebar
                sessions={sessionList}
                currentSessionId={sessionId}
                onSwitch={switchSession}
                onNew={createNewSession}
                onRename={renameSession}
                onDelete={deleteSession}
                onPin={togglePin}
                onExport={exportSession}
                isOpen={showSidebar}
                onToggle={() => setShowSidebar(v => !v)}
              />
            )}

            <button onClick={closePanel} aria-label={t('common.close')}
              className="cb-header-btn"
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
            >
              <SvcIcon name="x" size={16} />
            </button>
          </div>
        )}

        {/* ── Secretary banner（個性化問候 + 工作時間提示） ── */}
        {isOpen && showBanner && !showSidebar && (
          <div className="nxc-secretary-banner">
            <span className="nxc-secretary-greeting">{getGreeting(secretary)} 👋</span>
            {!isWithinWorkHours(secretary) && (
              <span className="nxc-secretary-note">{t('chat.offHoursNote', { defaultValue: '目前非工作時間，AI 仍會即時回覆，但同事可能稍後跟進。' })}</span>
            )}
            <button className="nxc-banner-close" onClick={() => setShowBanner(false)} aria-label={t('common.close')}>
              <SvcIcon name="x" size={12} />
            </button>
          </div>
        )}

        {/* ── Mobile session list (full screen) ── */}
        {isMobile && showSidebar && (
          <div className="cb-mobile-sessions">
            <SessionSidebar
              sessions={sessionList}
              currentSessionId={sessionId}
              onSwitch={switchSession}
              onNew={createNewSession}
              onRename={renameSession}
              onDelete={deleteSession}
              onPin={togglePin}
              onExport={exportSession}
              isOpen={true}
              onToggle={() => setShowSidebar(false)}
            />
          </div>
        )}

        {/* ── Sidebar overlay for desktop ── */}
        {!isMobile && showSidebar && (
          <SessionSidebar
            sessions={sessionList}
            currentSessionId={sessionId}
            onSwitch={switchSession}
            onNew={createNewSession}
            onRename={renameSession}
            onDelete={deleteSession}
            onPin={togglePin}
            onExport={exportSession}
            isOpen={true}
            onToggle={() => setShowSidebar(false)}
          />
        )}

        {/* ── Messages area ── */}
        {isOpen && !showSidebar && (
          <div ref={scrollRef} className="cb-messages" style={{
            padding: messages.length === 0 && !loadingSession ? '0' : '16px 16px',
          }}>
            {/* SPEC detail-v3: summary 已對話化 — inject 入 messages（below） */}
            {loadingSession ? (
              <div className="cb-loading">
                <div className="skeleton-line cb-skeleton cb-skeleton--wide" />
                <div className="skeleton-line cb-skeleton cb-skeleton--narrow" />
              </div>
            ) : messages.length === 0 ? (
              <EmptyState prompts={suggestedPrompts} onSelect={(p) => { setInput(p); setTimeout(() => {
                const ta = document.querySelector<HTMLTextAreaElement>('.composer__input-row textarea')
                ta?.focus()
              }, 100) }} />
            ) : (
              <div className="cb-msg-list">
                {messages.map((msg, idx) => {
                  const prev = idx > 0 ? messages[idx - 1] : undefined
                  return (
                    <div key={msg.id}>
                      <MessageTimestamp timestamp={msg.timestamp} prevTimestamp={prev?.timestamp} />
                      {msg.role === 'user' ? (
                        <UserMessageBubble msg={msg} prevMsg={prev} />
                      ) : (
                        <AiMessageBubble
                          msg={msg}
                          prevMsg={prev}
                          hovered={hoveredMsgId === msg.id}
                          onHover={(v) => setHoveredMsgId(v ? msg.id : null)}
                          onCopy={() => copyMessage(msg.content)}
                          onRetry={() => { const mIdx = messages.findIndex(m => m.id === msg.id); retryMessage(mIdx) }}
                          onFeedback={(rating) => sendFeedback(msg.id, rating)}
                          feedback={feedbackMap[msg.id]}
                          isStreaming={isStreaming && idx === messages.length - 1}
                          onFollowUpSelect={(q) => {
                            setInput(q)
                            setTimeout(() => {
                              const ta = document.querySelector<HTMLTextAreaElement>('.composer__input-row textarea')
                              ta?.focus()
                            }, 50)
                          }}
                        />
                      )}
                    </div>
                  )
                })}
                {isStreaming || isLoading ? (
                  <LoadingIndicator isStreaming={isStreaming} />
                ) : null}
                {streamingContent && (
                  <div className="cb-streaming-row">
                    <div className="cb-avatar-ai">
                      <SvcIcon name="sparkles" size={13} />
                    </div>
                    <div className="msg-ai-content cb-msg-ai-body">
                      <MarkdownMessage content={streamingContent} streaming />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Error banner ── */}
        {error && (
          <ErrorBanner
            error={error}
            onDismiss={() => setError(null)}
            onRetry={() => { setError(null); setTimeout(() => retryLastMessage(), 0) }}
          />
        )}

        {/* ── Cheatsheet ── */}
        {showCheatsheet && isOpen && (
          <div onClick={() => setShowCheatsheet(false)}
            className="cb-cheatsheet-overlay">
            <div onClick={e => e.stopPropagation()} className="cb-cheatsheet-card">
              <div className="cb-cheatsheet-title">⌨️ Shortcuts</div>
              <div className="cb-cheatsheet-list">
                {[
                  { keys: '⌘K', desc: 'Open AI panel' },
                  { keys: '⏎', desc: 'Send message' },
                  { keys: '⇧⏎', desc: 'New line' },
                  { keys: 'Esc', desc: 'Close panel' },
                  { keys: '?', desc: 'Toggle shortcuts' },
                ].map(s => (
                  <div key={s.keys} className="cb-cheatsheet-row">
                    <kbd className="cb-kbd">{s.keys}</kbd>
                    <span className="cb-cheatsheet-desc">{s.desc}</span>
                  </div>
                ))}
              </div>
              <button onClick={() => setShowCheatsheet(false)}
                className="cb-cheatsheet-close">
                {t('common.close')}
              </button>
            </div>
          </div>
        )}

        {/* ── Input area ── */}
        {isOpen && !showSidebar && (
          <>
            <SlashMentionMenu
              menuType={menuType}
              menuIndex={menuIndex}
              menuQuery={menuQuery}
              slashCommands={SLASH_COMMANDS}
              mentionResults={mentionResults}
              onSelect={(type, item) => {
                if (type === 'slash') setInput(SLASH_TRIGGER_PROMPTS[item.key])
                else {
                  const ta = document.querySelector<HTMLTextAreaElement>('.composer__input-row textarea')
                  const at = input.lastIndexOf('@', ta?.selectionStart ?? input.length)
                  setInput(input.slice(0, at) + `@${item.label}`)
                }
                setMenuType(null)
                setMentionResults([])
                const ta = document.querySelector<HTMLTextAreaElement>('.composer__input-row textarea')
                ta?.focus()
              }}
              onHover={setMenuIndex}
            />
            {activeContext && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', fontSize: 12, color: 'var(--color-primary, #146EF5)', background: 'rgba(20,110,245,0.08)', borderRadius: 8, margin: '0 12px 6px', flexShrink: 0 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>📎 正在討論: {activeContext.name}</span>
                <button onClick={() => setActiveContext(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: 'inherit', padding: '0 2px', lineHeight: 1 }} aria-label={t('chat.clearContext', { defaultValue: '清除上下文' })}>✕</button>
              </div>
            )}
            <div onPointerDown={(e) => {
              const ta = e.currentTarget.querySelector('textarea')
              if (ta) {
                const selStart = ta.selectionStart ?? input.length
                // Detect slash/mention
                const m = input.slice(0, selStart).match(/(?:^|\s)([/@])(\w*)$/)
                if (m) {
                  setMenuQuery(m[2]); setMenuIndex(0)
                  if (m[1] === '/') { setMenuType('slash'); setMentionResults([]) }
                  else if (m[2].length >= 1) {
                    setMenuType('mention')
                    apiClient.get<{ results: any[] }>(`/api/v1/ai/mentions/search?q=${encodeURIComponent(m[2])}`)
                      .then(r => setMentionResults(r?.results || [])).catch(() => setMentionResults([]))
                  }
                } else if (menuType) { setMenuType(null); setMentionResults([]) }
              }
            }}>
              <ChatInput
                input={input}
                onInputChange={handleInputChange}
                onSend={sendMessage}
                onAbort={abortStreaming}
                isStreaming={isStreaming}
                isLoading={isLoading}
                loadingSession={loadingSession}
              />
              {/* 2026-09-10 Terrence: subscription 用量搬去 Settings > 個人資料 */}
              {/* 2026-09-10 Terrence: 已連接嘅 provider 唔顯示（connected 係預設狀態，
                  冇資訊價值）— 只在有問題（未連接/快到期）時提示 */}
              {providers.some(p => p.status !== 'connected') && (
                <div style={{ padding: '0 14px 6px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {providers.filter(p => p.status !== 'connected').map(p => (
                    <span key={p.provider} className={`nxc-provider-chip ${p.status}`}>
                      {p.provider} · {p.status === 'connected' ? '已連接' : p.status}
                      {p.expires_in_days !== undefined && p.expires_in_days !== null && ` · Key ${p.expires_in_days} 日後到期`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ── AI action draft → confirm/execute（v2 batch）── */}
      <ActionPreviewModal
        isOpen={actionQueue.length > 0}
        onClose={() => setActionQueue([])}
        previews={actionQueue}
        onConfirmAll={async (actionIds: string[]) => {
          await apiClient.post('/api/v1/ai/actions/batch-confirm', { action_ids: actionIds })
          setActionQueue([])
        }}
        onReject={async (actionId: string) => {
          await apiClient.post(`/api/v1/ai/actions/${actionId}/reject`)
          setActionQueue(prev => prev.filter(a => a.action_id !== actionId))
        }}
      />

      {/* ── Global styles ── */}
      <style>{`
        @keyframes thinking-dot {
          0%, 80%, 100% { opacity: .2; transform: translateY(0); }
          40% { opacity: 1; transform: translateY(-3px); }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .skeleton-line { animation: skeleton-pulse 1.5s ease-in-out infinite; }
        @keyframes skeleton-pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
        .fab-btn::after {
          content: ''; position: absolute; top: 2px; right: 2px;
          width: 8px; height: 8px; border-radius: 50%;
          background: #ff3b30; border: 2px solid var(--color-primary);
          display: none;
        }
        .fab-btn--has-unread::after {
          display: block;
        }
        @media (prefers-reduced-motion: reduce) {
          .fab-btn, .typing-dots span, .streaming-caret, .skeleton-line {
            animation-duration: 0.01ms !important;
            transition-duration: 0.01ms !important;
          }
          .fab-btn { transition: none !important; }
        }
        @media (max-width: 767px) {
          .ai-msg-toolbar { opacity: 1 !important; }
        }
      `}</style>
    </>
  )
}

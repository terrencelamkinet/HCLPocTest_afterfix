import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Command, Zap, Activity, Building2, Calendar, CheckSquare, FileText, FolderKanban, ScanLine, Sparkles, Users } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'

/* ═══════════════════════════════════════════════════════════
   CommandPalette — Centralized Smart Search (⌘K)
   Single entry point for: entity search, navigation,
   quick actions, and AI-powered natural language queries.
   ═══════════════════════════════════════════════════════════ */

interface SearchResult { id: string; type: string; label: string; sub: string; url: string }
interface QuickAction { id: string; label: string; icon: any; hint?: string; action: () => void }

const TYPE_ICONS: Record<string, any> = {
  contact: Users, company: Building2, task: CheckSquare,
  project: FolderKanban, touchpoint: Activity, note: FileText, namecard: ScanLine, event: Calendar,
}
const RECENT_KEY = 'nexus-recent-searches'

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [aiAnswer, setAiAnswer] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const [recent, setRecent] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] }
  })
  const inputRef = useRef<HTMLInputElement>(null)
  const reqRef = useRef(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 50) }, [open])
  useEffect(() => { if (!open) { setQuery(''); setResults([]); setAiAnswer(null); setActiveIndex(0) } }, [open])

  const quickActions: QuickAction[] = [
    { id: 'new-contact', label: t('quickAction.newContact', { defaultValue: '新增聯絡人' }), icon: Users, hint: 'N C', action: () => navigate('/contacts?new=1') },
    { id: 'new-task', label: t('quickAction.newTask', { defaultValue: '新增任務' }), icon: CheckSquare, hint: 'N T', action: () => navigate('/tasks?new=1') },
    { id: 'scan-namecard', label: t('quickAction.scanNameCard', { defaultValue: '掃描名片' }), icon: ScanLine, action: () => navigate('/namecards?upload=1') },
    { id: 'ai-apps', label: t('quickAction.openAiApps', { defaultValue: '開啟 AI Apps' }), icon: Sparkles, action: () => navigate('/ai-apps') },
  ]

  const runSearch = useCallback(async (q: string) => {
    const id = ++reqRef.current
    if (!q.trim()) { setResults([]); setAiAnswer(null); setLoading(false); return }
    setLoading(true)
    try {
      const data = await apiClient.get<{ results: SearchResult[] }>(`/api/v1/crm/search?q=${encodeURIComponent(q)}&limit=8`)
      if (id === reqRef.current) setResults((data?.results || []).filter(r => r.type !== 'deal'))
    } catch { if (id === reqRef.current) setResults([]) }
    finally { if (id === reqRef.current) setLoading(false) }
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runSearch(query), 180)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, runSearch])

  const isQuestionLike = (q: string) => /[?？]$/.test(q.trim()) || /^(点|點|how|what|when|why|邊|幾|誰|哪)/i.test(q.trim()) || q.startsWith('/ai ')

  const runAiQuery = async () => {
    const q = query.replace(/^\/ai\s*/, '')
    if (!q.trim()) return
    setAiLoading(true); setAiAnswer(null)
    try {
      // Wire to existing /ai/chat (portal channel) — returns { text, ... }
      const data = await apiClient.post<{ text: string }>('/api/v1/ai/chat', {
        messages: [{ role: 'user', content: q }],
        channel: 'portal',
        max_tokens: 512,
      })
      setAiAnswer(data?.text || t('search.noAiAnswer', { defaultValue: '未能生成回應' }))
    } catch { setAiAnswer(t('search.aiError', { defaultValue: 'AI 查詢失敗，請重試' })) }
    finally { setAiLoading(false) }
  }

  useEffect(() => {
    if (query.trim() && isQuestionLike(query)) {
      const timer = setTimeout(() => runAiQuery(), 500)
      return () => clearTimeout(timer)
    } else { setAiAnswer(null) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const saveRecent = (label: string) => {
    const next = [label, ...recent.filter(r => r !== label)].slice(0, 5)
    setRecent(next)
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  }

  const goToResult = (r: SearchResult) => { saveRecent(r.label); onClose(); navigate(r.url) }

  const flatItems: { kind: 'result' | 'action'; data: SearchResult | QuickAction }[] = query.trim()
    ? results.map(r => ({ kind: 'result' as const, data: r }))
    : quickActions.map(a => ({ kind: 'action' as const, data: a }))

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIndex(i => Math.min(i + 1, flatItems.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIndex(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      const item = flatItems[activeIndex]
      if (!item) return
      if (item.kind === 'result') goToResult(item.data as SearchResult)
      else { onClose(); (item.data as QuickAction).action() }
    } else if (e.key === 'Escape') onClose()
  }

  if (!open) return null

  return (
    <div className="cmdp-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="cmdp-panel" role="dialog" aria-modal="true">
        <div className="cmdp-input-row">
          <SvcIcon name="search" size={17} className="cmdp-search-icon" />
          <input
            ref={inputRef} className="cmdp-input" value={query}
            placeholder={t('search.placeholder', { defaultValue: '搜尋聯絡人、公司、商機… 或輸入問題問 AI（例如：邊個客戶最耐冇聯絡？）' })}
            onChange={(e) => { setQuery(e.target.value); setActiveIndex(0) }}
            onKeyDown={handleKeyDown}
          />
          {query && <button className="cmdp-clear" onClick={() => setQuery('')}><SvcIcon name="x" size={14} /></button>}
          <kbd className="cmdp-esc">ESC</kbd>
        </div>

        <div className="cmdp-body">
          {(aiLoading || aiAnswer) && (
            <div className="cmdp-ai-block">
              <div className="cmdp-ai-header"><SvcIcon name="sparkles" size={14} /> {t('search.aiAnswer', { defaultValue: 'AI 回應' })}</div>
              {aiLoading ? (
                <div className="cmdp-ai-thinking"><span className="cmdp-dot" /><span className="cmdp-dot" /><span className="cmdp-dot" /></div>
              ) : <div className="cmdp-ai-text">{aiAnswer}</div>}
            </div>
          )}

          {!query.trim() && recent.length > 0 && (
            <div className="cmdp-section">
              <div className="cmdp-section-label"><SvcIcon name="clock" size={12} /> {t('search.recent', { defaultValue: '最近搜尋' })}</div>
              {recent.map((r, i) => <div key={i} className="cmdp-recent-item" onClick={() => setQuery(r)}>{r}</div>)}
            </div>
          )}

          <div className="cmdp-section">
            {query.trim() && (
              <div className="cmdp-section-label">
                {loading ? t('search.searching', { defaultValue: '搜尋中…' }) : t('search.results', { defaultValue: '結果' })}
              </div>
            )}
            {!query.trim() && <div className="cmdp-section-label"><Zap size={12} /> {t('search.quickActions', { defaultValue: '快速操作' })}</div>}
            {query.trim() && results.length === 0 && !loading && (
              <div className="cmdp-empty">{t('search.noResults', { defaultValue: '找不到相關結果' })}</div>
            )}
            {flatItems.map((item, i) => {
              if (item.kind === 'result') {
                const r = item.data as SearchResult
                const Icon = TYPE_ICONS[r.type] || FileText
                return (
                  <div key={r.id} className={`cmdp-item ${i === activeIndex ? 'active' : ''}`}
                    onMouseEnter={() => setActiveIndex(i)} onClick={() => goToResult(r)}>
                    <div className="cmdp-item-icon"><Icon size={15} /></div>
                    <div className="cmdp-item-body">
                      <div className="cmdp-item-label">{r.label}</div>
                      <div className="cmdp-item-sub">{r.sub}</div>
                    </div>
                    <span className="cmdp-item-type">{t(`entityType.${r.type}`, { defaultValue: r.type })}</span>
                    <SvcIcon name="arrow-right" size={13} className="cmdp-item-arrow" />
                  </div>
                )
              }
              const a = item.data as QuickAction
              const Icon = a.icon
              return (
                <div key={a.id} className={`cmdp-item ${i === activeIndex ? 'active' : ''}`}
                  onMouseEnter={() => setActiveIndex(i)} onClick={() => { onClose(); a.action() }}>
                  <div className="cmdp-item-icon accent"><Icon size={15} /></div>
                  <div className="cmdp-item-body"><div className="cmdp-item-label">{a.label}</div></div>
                  {a.hint && <kbd className="cmdp-item-hint">{a.hint}</kbd>}
                  <SvcIcon name="arrow-right" size={13} className="cmdp-item-arrow" />
                </div>
              )
            })}
          </div>
        </div>

        <div className="cmdp-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('search.navigate', { defaultValue: '導航' })}</span>
          <span><kbd>↵</kbd> {t('search.select', { defaultValue: '選擇' })}</span>
          <span className="cmdp-footer-brand"><Command size={11} /> Penguin AI Search</span>
        </div>
      </div>
    </div>
  )
}

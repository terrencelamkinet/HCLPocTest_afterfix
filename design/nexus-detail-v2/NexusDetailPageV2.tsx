import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Sparkles, Pencil, RefreshCw, ChevronRight, AlertTriangle, TrendingUp, Target } from 'lucide-react'
import { apiClient } from '../lib/api'
import type { EntityRecord, ModuleConfig } from './module-types'

/* ═══════════════════════════════════════════════════════════
   NexusDetailPageV2 — AI-Native Record Detail Layout
   Replaces the flat tab-only layout with:
   1. Sticky header + breadcrumb + identity + highlight widgets
   2. AI Insight Card (summary, risk tags, opportunity tags)
   3. Two-column body: main tab content + grouped sidebar (Attio-style)
   4. Unified timeline merging tasks/touchpoints/notes/AI-detected events
   ═══════════════════════════════════════════════════════════ */

export interface HighlightWidget {
  label: string
  value: string | number
  trend?: 'up' | 'down' | 'neutral'
  icon?: string
}

export interface AIInsight {
  summary: string
  tags: { label: string; kind: 'opportunity' | 'risk' | 'info'; icon?: string }[]
  generatedAt: string
}

export interface SidebarSection {
  title: string
  fields: { label: string; value: string; aiEnriched?: boolean }[]
}

export interface DetailTab {
  key: string
  label: string
  count?: number
  render: () => React.ReactNode
}

interface NexusDetailPageV2Props {
  entity: EntityRecord
  moduleConfig: ModuleConfig
  avatarLabel: string
  subline: string[]
  highlights: HighlightWidget[]
  aiInsight?: AIInsight
  aiInsightLoading?: boolean
  onRefreshInsight?: () => void
  sidebarSections: SidebarSection[]
  relatedCards?: { title: string; meta: string; badge?: string; badgeColor?: string; onClick?: () => void }[]
  tabs: DetailTab[]
  onEdit?: () => void
  onAskAI?: () => void
  breadcrumbLabel: string
  breadcrumbHref: string
}

export function NexusDetailPageV2({
  entity, avatarLabel, subline, highlights, aiInsight, aiInsightLoading,
  onRefreshInsight, sidebarSections, relatedCards, tabs, onEdit, onAskAI,
  breadcrumbLabel, breadcrumbHref,
}: NexusDetailPageV2Props) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(tabs[0]?.key)
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({})

  const activeTabDef = useMemo(() => tabs.find(tb => tb.key === activeTab), [tabs, activeTab])

  const toggleSection = (title: string) =>
    setCollapsedSections(s => ({ ...s, [title]: !s[title] }))

  return (
    <div className="nx-detail-page">
      {/* ═══ Sticky Header ═══ */}
      <div className="nx-detail-header">
        <div className="nx-detail-breadcrumb">
          <Link to={breadcrumbHref}>{breadcrumbLabel}</Link>
          <ChevronRight size={12} />
          <span style={{ color: 'var(--color-text-primary)' }}>{entity.name}</span>
        </div>

        <div className="nx-detail-identity-row">
          <div className="nx-detail-identity">
            <div className="nx-detail-avatar">{avatarLabel}</div>
            <div className="nx-detail-titleblock">
              <h1>{entity.name}</h1>
              <div className="nx-detail-subline">
                {subline.map((s, i) => (
                  <span key={i}>{i > 0 && <span style={{ marginRight: 6 }}>·</span>}{s}</span>
                ))}
              </div>
            </div>
          </div>
          <div className="nx-detail-actions">
            {onEdit && (
              <button className="nx-btn nx-btn-secondary" onClick={onEdit}>
                <Pencil size={13} /> {t('common.edit')}
              </button>
            )}
            {onAskAI && (
              <button className="nx-btn nx-btn-ai" onClick={onAskAI}>
                <Sparkles size={13} /> {t('common.askAI', { defaultValue: 'Ask AI' })}
              </button>
            )}
          </div>
        </div>

        {highlights.length > 0 && (
          <div className="nx-highlight-row">
            {highlights.map((h, i) => (
              <div className="nx-highlight-widget" key={i}>
                <div className="nx-highlight-label">{h.label}</div>
                <div className={`nx-highlight-value ${h.trend === 'up' ? 'trend-up' : h.trend === 'down' ? 'trend-down' : ''}`}>
                  {h.value}
                  {h.trend === 'up' && <TrendingUp size={13} />}
                  {h.trend === 'down' && <AlertTriangle size={13} />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ═══ AI Insight Card ═══ */}
      {(aiInsight || aiInsightLoading) && (
        <div className="nx-ai-insight-card">
          <div className="nx-ai-insight-head">
            <div className="nx-ai-insight-icon"><Sparkles size={14} /></div>
            <div className="nx-ai-insight-title">{t('common.aiSummary', { defaultValue: 'AI 客戶摘要' })}</div>
            {onRefreshInsight && (
              <div className="nx-ai-insight-refresh" onClick={onRefreshInsight}>
                <RefreshCw size={11} />
                {aiInsight ? new Date(aiInsight.generatedAt).toLocaleTimeString() : t('common.loading')}
              </div>
            )}
          </div>
          {aiInsightLoading ? (
            <div className="nx-ai-thinking">
              <span className="nx-ai-dot" /><span className="nx-ai-dot" /><span className="nx-ai-dot" />
            </div>
          ) : (
            <>
              <div className="nx-ai-insight-body">{aiInsight!.summary}</div>
              {aiInsight!.tags.length > 0 && (
                <div className="nx-ai-insight-tags">
                  {aiInsight!.tags.map((tg, i) => (
                    <span className={`nx-ai-tag ${tg.kind}`} key={i}>
                      {tg.kind === 'opportunity' && <Target size={11} />}
                      {tg.kind === 'risk' && <AlertTriangle size={11} />}
                      {tg.label}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ═══ Body: Main Tabs + Sidebar ═══ */}
      <div className="nx-detail-body">
        <div className="nx-detail-main">
          <div className="nx-tabs">
            {tabs.map(tb => (
              <div
                key={tb.key}
                className={`nx-tab ${activeTab === tb.key ? 'active' : ''}`}
                onClick={() => setActiveTab(tb.key)}
              >
                {tb.label}
                {tb.count != null && <span className="nx-tab-count">{tb.count}</span>}
              </div>
            ))}
          </div>
          {activeTabDef?.render()}
        </div>

        <div className="nx-detail-sidebar">
          {sidebarSections.map(sec => (
            <div className="nx-sidebar-section" key={sec.title}>
              <div className="nx-sidebar-section-head" onClick={() => toggleSection(sec.title)}>
                {sec.title} <span>{collapsedSections[sec.title] ? '+' : '−'}</span>
              </div>
              {!collapsedSections[sec.title] && sec.fields.map((f, i) => (
                <div className="nx-sidebar-field" key={i}>
                  <span className="nx-sidebar-field-label">{f.label}</span>
                  <span className={`nx-sidebar-field-value ${f.aiEnriched ? 'ai-enriched' : ''}`}>
                    {f.aiEnriched && <span className="nx-enrich-dot" />}
                    {f.value}
                  </span>
                </div>
              ))}
            </div>
          ))}

          {relatedCards && relatedCards.length > 0 && (
            <div className="nx-sidebar-section">
              <div className="nx-sidebar-section-head">{t('common.related', { defaultValue: 'Related' })}</div>
              <div className="nx-related-grid" style={{ gridTemplateColumns: '1fr' }}>
                {relatedCards.map((c, i) => (
                  <div className="nx-related-card" key={i} onClick={c.onClick}>
                    <div className="nx-related-card-title">{c.title}</div>
                    <div className="nx-related-card-meta">{c.meta}</div>
                    {c.badge && (
                      <span
                        className="nx-related-card-badge"
                        style={{ background: c.badgeColor || 'rgba(37,99,235,.12)', color: '#60A5FA' }}
                      >
                        {c.badge}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════
   Unified Timeline component — merges tasks/touchpoints/notes/
   AI-detected events into one chronological feed
   ═══════════════════════════════════════════════════════════ */

export interface TimelineEvent {
  id: string
  icon: string
  title: string
  meta: string
  body?: string
  aiDetected?: boolean
  aiLabel?: string
  sortKey: string
}

export function UnifiedTimeline({ events }: { events: TimelineEvent[] }) {
  const { t } = useTranslation()
  if (events.length === 0) {
    return (
      <div className="nx-empty-state">
        <div className="nx-empty-state-title">{t('common.noActivity', { defaultValue: '暫無活動記錄' })}</div>
        <div className="nx-empty-state-desc">{t('common.noActivityDesc', { defaultValue: '新增 Task、Touchpoint 或 Note 後將顯示於此' })}</div>
      </div>
    )
  }
  return (
    <div className="nx-timeline">
      {events.map(ev => (
        <div className="nx-timeline-item" key={ev.id}>
          <div className={`nx-timeline-dot ${ev.aiDetected ? 'ai-detected' : ''}`}>{ev.icon}</div>
          <div className="nx-timeline-card">
            <div className="nx-timeline-title">{ev.title}</div>
            <div className="nx-timeline-meta">{ev.meta}</div>
            {ev.body && <div className="nx-timeline-body">{ev.body}</div>}
            {ev.aiDetected && <span className="nx-timeline-ai-tag"><Sparkles size={10} /> {ev.aiLabel || 'AI 自動偵測'}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════
   Hook: fetch/generate AI insight for an entity
   Calls backend endpoint that summarizes recent activity +
   detects opportunities/risks via LLM
   ═══════════════════════════════════════════════════════════ */

export function useAIInsight(entityType: string, entityId: string) {
  const [insight, setInsight] = useState<AIInsight | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchInsight = async () => {
    setLoading(true)
    try {
      const res = await apiClient.post<AIInsight>('/api/v1/ai/entity-insight', {
        entity_type: entityType,
        entity_id: entityId,
      })
      setInsight(res)
    } catch {
      setInsight(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchInsight() }, [entityType, entityId])

  return { insight, loading, refresh: fetchInsight }
}

import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import type { EntityRecord, ModuleConfig } from '../module-types'

/* 共用：相對時間（Last Update KPI 等） */
export function timeAgoShort(d?: string): string {
  if (!d) return '—'
  const diff = Date.now() - new Date(d).getTime()
  if (diff < 0) return 'Today'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'Yesterday'
  if (days < 30) return `${days}d ago`
  return new Date(d).toLocaleDateString()
}

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
  /* SPEC mobile-crm-svg-uiux §9: KPI 可點擊（切去對應 tab）+ mobile 隱藏次要 cell */
  tab?: string
  hideOnMobile?: boolean
}

export interface AIInsight {
  summary: string
  tags: { label: string; kind: 'opportunity' | 'risk' | 'info'; icon?: string }[]
  generatedAt: string
}

export interface SidebarField {
  label: string
  value: string
  aiEnriched?: boolean
  /* SPEC mobile-crm-svg-uiux §10.2: row 右側 icon 快捷（mailto/tel/company 導航） */
  action?: { type: 'mailto'; href: string } | { type: 'tel'; href: string } | { type: 'open'; onClick: () => void }
}

export interface SidebarSection {
  title: string
  fields: SidebarField[]
}

export interface DetailTab {
  key: string
  label: string
  count?: number
  render: () => React.ReactNode
}

export interface MobileMenuAction {
  key: string
  label: string
  icon?: 'external-link' | 'share' | 'copy' | 'trash' | 'archive' | 'mail'
  danger?: boolean
  onClick: () => void
}

interface NexusDetailPageV2Props {
  entity: EntityRecord
  moduleConfig: ModuleConfig
  avatarLabel: string
  subline: string[]
  highlights: HighlightWidget[]
  sidebarSections: SidebarSection[]
  relatedCards?: { title: string; meta: string; badge?: string; badgeColor?: string; avatarLabel?: string; onClick?: () => void }[]
  tabs: DetailTab[]
  onEdit?: () => void
  onAskAI?: () => void
  editMode?: boolean
  editSaving?: boolean
  onSaveEdit?: () => void
  onCancelEdit?: () => void
  /* SPEC mobile-crm-svg-uiux §12: mobile 專屬 edit 表單（單欄 full-screen — desktop 保留原 form） */
  editForm?: React.ReactNode
  editDirty?: boolean
  breadcrumbLabel: string
  breadcrumbHref: string
  /* SPEC mobile-crm-svg-uiux: mobile top bar 標題 + ⋯ more menu（淨 mobile 顯示） */
  mobileTitle?: string
  mobileMenuItems?: MobileMenuAction[]
}

export function ragForStatus(status: string): string {
  const s = status.toLowerCase()
  if (['lead', 'prospect', 'new'].includes(s)) return 'blue'
  if (['warm', 'in progress', 'review', 'pending', 'at risk', 'scheduled'].includes(s)) return 'amber'
  if (['blocked', 'overdue', 'lost', 'overdue-fail'].includes(s)) return 'red'
  if (['cold', 'inactive', 'archive', 'cancelled'].includes(s)) return 'gray'
  return 'green'
}

export function NexusDetailPageV2({
  entity, avatarLabel, subline, highlights,
  sidebarSections, relatedCards, tabs, onEdit, onAskAI,
  editMode, editSaving, onSaveEdit, onCancelEdit,
  breadcrumbLabel, breadcrumbHref, mobileTitle, mobileMenuItems,
  editForm, editDirty,
}: NexusDetailPageV2Props) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(tabs[0]?.key)
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({})
  const [moreOpen, setMoreOpen] = useState(false)
  /* mobile edit 表單淨 <900px 生效（desktop 保留原 edit panel） */
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const onChange = () => setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const menuIcon = (icon?: MobileMenuAction['icon']) => {
    // 2026-09-09: lucide → SvcIcon 統一（同主頁面 icon kit 一致）
    switch (icon) {
      case 'external-link': return <SvcIcon name="external-link" size={20} />
      case 'share': return <SvcIcon name="share" size={20} />
      case 'copy': return <SvcIcon name="copy" size={20} />
      case 'trash': return <SvcIcon name="trash-2" size={20} />
      case 'archive': return <SvcIcon name="archive" size={20} />
      case 'mail': return <SvcIcon name="mail" size={20} />
      default: return <SvcIcon name="more-horizontal" size={20} />
    }
  }

  const activeTabDef = useMemo(() => tabs.find(tb => tb.key === activeTab), [tabs, activeTab])

  const toggleSection = (title: string) =>
    setCollapsedSections(s => ({ ...s, [title]: !s[title] }))

  return (
    <>
    {/* ═══ Mobile Top App Bar（SPEC mobile-crm-svg-uiux — <900px 顯示，desktop 隱藏）═══ */}
    <div className={`mobile-topbar ${editMode && editForm && isMobile ? 'edit-mode' : ''}`}>
      {editMode && editForm && isMobile ? (
        /* Sticky Edit Header（SPEC §12.1）: 取消 | 編輯聯絡人 | 儲存 */
        <>
          <button type="button" className="edit-bar-btn" onClick={onCancelEdit} disabled={editSaving}>
            {t('common.cancel', { defaultValue: '取消' })}
          </button>
          <span className="mobile-topbar-title">{t('mobile.editContact', { defaultValue: '編輯聯絡人' })}</span>
          <button type="button" className="edit-bar-btn edit-bar-save" onClick={onSaveEdit} disabled={!editDirty || editSaving}>
            {editSaving ? t('common.saving', { defaultValue: '儲存中…' }) : t('common.save', { defaultValue: '儲存' })}
          </button>
        </>
      ) : (
        <>
          <Link to={breadcrumbHref} className="icon-btn" aria-label={t('mobile.backToList', { defaultValue: '返回列表' })}>
            <SvcIcon name="chevron-left" size={22} />
          </Link>
          <span className="mobile-topbar-title">{mobileTitle || breadcrumbLabel}</span>
          {mobileMenuItems && mobileMenuItems.length > 0 ? (
            <button className="icon-btn" type="button" aria-label={t('mobile.moreActions', { defaultValue: '更多操作' })} onClick={() => setMoreOpen(true)}>
              <SvcIcon name="more-horizontal" size={22} />
            </button>
          ) : <span className="icon-btn" aria-hidden="true" style={{ visibility: 'hidden' }}><SvcIcon name="more-horizontal" size={22} /></span>}
        </>
      )}
    </div>

    <div className={`detail-shell ${editMode && editForm && isMobile ? 'edit-mode' : ''}`}>
      {editMode && editForm && isMobile ? (
        <div className="edit-form-wrap">{editForm}</div>
      ) : (<>
      <div className="detail-header">
        <div className="crumb">
          <Link to={breadcrumbHref}>{breadcrumbLabel}</Link>
          <SvcIcon name="chevron-right" size={12} />
          <span style={{ color: 'var(--color-text-primary)' }}>{entity.name}</span>
        </div>

        <div className="identity-row">
          <div className="identity-left">
            <div className="avatar">{avatarLabel}</div>
            <div className="id-block">
              <div className="id-name-row">
                <h1 className="id-name">{entity.name}</h1>
                {entity.status && (
                  <span className={`status-pill rag-${ragForStatus(String(entity.status))}`}>{String(entity.status)}</span>
                )}
              </div>
              <div className="id-subline">
                {subline.map((s, i) => (
                  <span key={i}>{s}</span>
                ))}
              </div>
            </div>
          </div>
          <div className="actions-row">
            {editMode ? (
              <>
                {onCancelEdit && (
                  <button className="btn btn-ghost" onClick={onCancelEdit} disabled={editSaving}>
                    {t('common.cancel')}
                  </button>
                )}
                {onSaveEdit && (
                  <button className="btn btn-dark" onClick={onSaveEdit} disabled={editSaving}>
                    {editSaving ? t('common.saving') : t('common.save')}
                  </button>
                )}
              </>
            ) : (
              <>
                {onEdit && (
                  <button className="btn btn-ghost" onClick={onEdit}>
                    <SvcIcon name="pencil" size={13} /> {t('common.edit')}
                  </button>
                )}
                {onAskAI && (
                  <button className="btn btn-ai" onClick={onAskAI}>
                    <SvcIcon name="sparkles" size={13} /> {t('common.askAI', { defaultValue: 'Ask AI' })}
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {highlights.length > 0 && (
          <div className="kpi-strip" style={{ gridTemplateColumns: `repeat(${highlights.length}, 1fr)` }}>
            {highlights.map((h, i) => (
              <div
                className={`kpi-cell ${h.tab ? 'kpi-tappable' : ''} ${h.hideOnMobile ? 'kpi-hide-mobile' : ''}`}
                key={i}
                onClick={h.tab ? () => setActiveTab(h.tab as string) : undefined}
                role={h.tab ? 'button' : undefined}
                tabIndex={h.tab ? 0 : undefined}
                onKeyDown={h.tab ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab(h.tab as string) } } : undefined}
              >
                <div className="kpi-label">{h.label}</div>
                <div className={`kpi-value ${h.trend === 'up' ? 'trend-up' : h.trend === 'down' ? 'trend-down' : ''}`}>
                  {h.value}
                  {h.trend === 'up' && <SvcIcon name="trending-up" size={13} />}
                  {h.trend === 'down' && <SvcIcon name="alert-triangle" size={13} />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ═══ Body: Main Tabs + Sidebar ═══ */}
      <div className="detail-body">
        <div className="detail-main">
          <div className="tabs">
            {tabs.map(tb => (
              <div
                key={tb.key}
                className={`tab ${activeTab === tb.key ? 'active' : ''}`}
                onClick={() => setActiveTab(tb.key)}
              >
                {tb.label}
                {tb.count != null && <span className="count">{tb.count}</span>}
              </div>
            ))}
          </div>
          {activeTabDef?.render()}
        </div>

        <div className="detail-sidebar">
          {sidebarSections.map(sec => (
            <div className="sb-card" key={sec.title}>
              <div className="sb-head" onClick={() => toggleSection(sec.title)}>
                {sec.title} <span>{collapsedSections[sec.title] ? '+' : '−'}</span>
              </div>
              {!collapsedSections[sec.title] && sec.fields.map((f, i) => (
                <div className="sb-row" key={i}>
                  <span className="sb-row-label">{f.label}</span>
                  <span className="sb-row-value-wrap">
                    <span className={`sb-row-value ${f.aiEnriched ? 'ai-enriched' : ''}`}>
                      {f.aiEnriched && <span className="enrich-dot" />}
                      {f.value}
                    </span>
                    {f.action?.type === 'mailto' && (
                      <a className="row-action" href={`mailto:${f.action.href}`} aria-label={t('mobile.sendEmail', { defaultValue: '寄送電郵' })} onClick={e => e.stopPropagation()}>
                        <SvcIcon name="mail" size={15} />
                      </a>
                    )}
                    {f.action?.type === 'tel' && (
                      <a className="row-action" href={`tel:${f.action.href}`} aria-label={t('mobile.call', { defaultValue: '致電' })} onClick={e => e.stopPropagation()}>
                        <SvcIcon name="phone" size={15} />
                      </a>
                    )}
                    {f.action?.type === 'open' && (
                      <button type="button" className="row-action" aria-label={f.label} onClick={e => { e.stopPropagation(); (f.action as { type: 'open'; onClick: () => void }).onClick() }}>
                        <SvcIcon name="chevron-right" size={16} />
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ))}

          {relatedCards && relatedCards.length > 0 && (
            <div className="sb-card">
              <div className="sb-head">{t('common.related', { defaultValue: 'Related' })}</div>
              <div className="related-grid" style={{ gridTemplateColumns: '1fr' }}>
                {relatedCards.map((c, i) => (
                  <div className="related-card" key={i} onClick={c.onClick}>
                    <div className="related-avatar">{c.avatarLabel || String(c.title || '?').slice(0, 2).toUpperCase()}</div>
                    <div style={{ minWidth: 0 }}>
                      <div className="related-title">{c.title}</div>
                      <div className="related-meta">{c.meta}</div>
                      {c.badge && (
                        <span
                          className="related-badge"
                          style={{ background: c.badgeColor || 'rgba(15,110,106,.1)', color: 'var(--color-primary)' }}
                        >
                          {c.badge}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      </>)}
    </div>

    {/* ═══ ⋯ More Actions Bottom Sheet（SPEC mobile-crm-svg-uiux §5.2）═══ */}
    {moreOpen && mobileMenuItems && (
      <div className="more-sheet-overlay" onClick={e => { if (e.target === e.currentTarget) setMoreOpen(false) }}>
        <div className="more-sheet" role="dialog" aria-label={t('mobile.moreActions', { defaultValue: '更多操作' })}>
          <div className="more-sheet-grip" />
          {mobileMenuItems.map(item => (
            <button
              key={item.key}
              type="button"
              className={`more-sheet-item ${item.danger ? 'danger' : ''}`}
              onClick={() => { setMoreOpen(false); item.onClick() }}
            >
              <span className="more-sheet-icon">{menuIcon(item.icon)}</span>
              <span>{item.label}</span>
            </button>
          ))}
          <div className="more-sheet-spacer" />
          <button type="button" className="more-sheet-item more-sheet-cancel" onClick={() => setMoreOpen(false)}>
            {t('common.cancel', { defaultValue: '取消' })}
          </button>
        </div>
      </div>
    )}
    </>
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
      <div className="empty-state">
        <div className="empty-state-title">{t('common.noActivity', { defaultValue: '暫無活動記錄' })}</div>
        <div className="empty-state-desc">{t('common.noActivityDesc', { defaultValue: '新增 Task、Touchpoint 或 Note 後將顯示於此' })}</div>
      </div>
    )
  }
  return (
    <div className="timeline">
      {events.map(ev => (
        <div className="tl-item" key={ev.id}>
          <div className={`tl-icon ${ev.aiDetected ? 'ai' : ''}`}>{ev.icon}</div>
          <div className="tl-content">
            <div className="tl-title">{ev.title}</div>
            <div className="tl-meta">{ev.meta}</div>
            {ev.body && <div className="tl-meta">{ev.body}</div>}
            {ev.aiDetected && <span className="tl-tag ai"><SvcIcon name="sparkles" size={10} /> {ev.aiLabel || 'AI 自動偵測'}</span>}
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

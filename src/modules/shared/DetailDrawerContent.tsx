import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../../lib/api'
import { FieldsRenderer } from './FieldsRenderer'
import { buildPayload, apiErrorToString } from './field-utils'
import { localizeResourceLabel } from './labels'
import { ragForStatus } from './NexusDetailPageV2'
import type { HighlightWidget } from './NexusDetailPageV2'
import type { ModuleConfig, EntityRecord } from '../module-types'

interface Props {
  config: ModuleConfig
  id: string
  onClose: () => void
  tabRenderers?: Record<string, React.ComponentType<{
    entity: EntityRecord
    moduleConfig: ModuleConfig
    refresh: () => void
  }>>
  extraData?: Record<string, any>
}

function formatDateSafe(d?: string): string {
  if (!d) return '—'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '—'
  return dt.toLocaleDateString()
}

export default function DetailDrawerContent({ config, id, onClose, extraData }: Props) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [entity, setEntity] = useState<EntityRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const fetchEntity = async () => {
    setLoading(true)
    setError(null)
    try {
      const eRes = await apiClient.get<EntityRecord>(`${config.apiPath}/${id}`)
      setEntity(eRes)
      const f: Record<string, any> = {}
      for (const field of config.fields) {
        let val = (eRes as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    } catch (e: any) {
      setError(e.detail || e.message)
    } finally {
      setLoading(false)
    }
  }

  // Initialise edit form when entity loads (or re-fetch after save)
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of config.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
  }, [entity, config])

  useEffect(() => { fetchEntity() }, [config.apiPath, id])

  const handleChange = (key: string, value: any) => setForm(f => ({ ...f, [key]: value }))

  const cancelEdit = () => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of config.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
    setEditOpen(false)
  }

  const handleSave = async () => {
    if (!entity) return
    setSaving(true)
    try {
      await apiClient.patch(`${config.apiPath}/${entity.id}`, buildPayload(form, config.fields))
      setEditOpen(false)
      fetchEntity()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const handleDeleteConfirm = async () => {
    if (!entity) return
    setDeleteLoading(true)
    try {
      await apiClient.delete(`${config.apiPath}/${entity.id}`)
      onClose()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setDeleteLoading(false) }
  }

  if (loading) {
    return (
      <div className="drawer-loading">
        <div className="drawer-skeleton h-24" />
        <div className="drawer-skeleton" />
        <div className="drawer-skeleton" />
      </div>
    )
  }

  if (error || !entity) {
    return (
      <div className="drawer-error">
        <p>{error || t('common.notFound', { label: localizeResourceLabel(config.name, false, config.label, t) })}</p>
        <button onClick={fetchEntity} className="btn-secondary">{t('common.retry')}</button>
      </div>
    )
  }

  const nameField = config.fields.find(f => f.type === 'title')?.key || config.titleField || 'name'
  const entityName = String(entity[nameField] || entity.id || '')
  const avatarLabel = String(entityName || '?').slice(0, 2).toUpperCase()

  // Subline per module
  const sublineParts: string[] = (() => {
    const e: any = entity
    if (config.name === 'company') return [e.industry, e.category, e.city || e.address].filter(Boolean)
    if (config.name === 'contact') return [e.job_title, e.department, e.company?.name || ''].filter(Boolean)
    if (config.name === 'project') return [e.status, e.priority, e.company?.name || ''].filter(Boolean)
    if (config.name === 'task') return [e.priority, e.status, e.company_id ? String(e.company_id) : ''].filter(Boolean)
    if (config.name === 'touchpoint') return [e.type, formatDateSafe(e.date)].filter(Boolean)
    return []
  })() as string[]

  // Highlights (3-4 KPIs per module, '—' fallback)
  const highlights: HighlightWidget[] = (() => {
    const e: any = entity
    if (config.name === 'company') return [
      { label: t('common.openDeals', { defaultValue: 'Open Deals' }), value: e.open_deals_count ?? '—', trend: 'neutral' },
      { label: t('common.contacts', { defaultValue: 'Contacts' }), value: e.contacts_count ?? '—', trend: 'neutral' },
      { label: t('fields.status', { defaultValue: 'Status' }), value: e.status || '—', trend: 'neutral' },
    ]
    if (config.name === 'contact') return [
      { label: t('common.openTasks', { defaultValue: 'Open Tasks' }), value: e.open_tasks_count ?? '—', trend: 'neutral' },
      { label: t('common.touchpoints', { defaultValue: 'Touchpoints' }), value: e.touchpoints_count ?? '—', trend: 'neutral' },
      { label: t('fields.status', { defaultValue: 'Status' }), value: e.status || '—', trend: 'neutral' },
    ]
    if (config.name === 'project') return [
      { label: t('fields.status', { defaultValue: 'Status' }), value: e.status || '—', trend: 'neutral' },
      { label: t('fields.priority', { defaultValue: 'Priority' }), value: e.priority || '—', trend: 'neutral' },
      { label: t('fields.deadline', { defaultValue: 'Deadline' }), value: formatDateSafe(e.deadline), trend: 'neutral' },
    ]
    if (config.name === 'task') return [
      { label: t('fields.priority', { defaultValue: 'Priority' }), value: e.priority || '—', trend: 'neutral' },
      { label: t('fields.status', { defaultValue: 'Status' }), value: e.status || '—', trend: 'neutral' },
      { label: t('fields.dueDate', { defaultValue: 'Due Date' }), value: formatDateSafe(e.due_date), trend: 'neutral' },
    ]
    if (config.name === 'touchpoint') return [
      { label: t('fields.type', { defaultValue: 'Type' }), value: e.type || '—', trend: 'neutral' },
      { label: t('fields.date', { defaultValue: 'Date' }), value: formatDateSafe(e.date), trend: 'neutral' },
      { label: t('fields.duration', { defaultValue: 'Duration' }), value: e.duration_minutes != null ? `${e.duration_minutes}m` : '—', trend: 'neutral' },
    ]
    return []
  })()

  // General Info + Ownership sidebar sections per module
  const generalInfo = (() => {
    const e: any = entity
    if (config.name === 'company') return [
      [t('fields.industry', { defaultValue: 'Industry' }), e.industry || '—'],
      [t('fields.size', { defaultValue: 'Employees' }), e.size != null ? String(e.size) : '—'],
      [t('fields.website', { defaultValue: 'Website' }), e.website || '—'],
      [t('fields.phone', { defaultValue: 'Phone' }), e.phone || '—'],
    ]
    if (config.name === 'contact') return [
      [t('fields.jobTitle', { defaultValue: 'Title' }), e.job_title || '—'],
      [t('fields.email', { defaultValue: 'Email' }), e.email || '—'],
      [t('fields.phone', { defaultValue: 'Phone' }), e.phone || '—'],
      [t('fields.company', { defaultValue: 'Company' }), e.company?.name || '—'],
    ]
    if (config.name === 'project') return [
      [t('fields.status', { defaultValue: 'Status' }), e.status || '—'],
      [t('fields.priority', { defaultValue: 'Priority' }), e.priority || '—'],
      [t('fields.startDate', { defaultValue: 'Start Date' }), formatDateSafe(e.start_date)],
      [t('fields.deadline', { defaultValue: 'Deadline' }), formatDateSafe(e.deadline)],
      [t('fields.budget', { defaultValue: 'Budget' }), e.budget_amount != null ? String(e.budget_amount) : '—'],
      [t('fields.company', { defaultValue: 'Company' }), e.company?.name || '—'],
      [t('fields.description', { defaultValue: 'Description' }), e.description || '—'],
    ]
    if (config.name === 'task') return [
      [t('fields.description', { defaultValue: 'Description' }), e.description || '—'],
    ]
    if (config.name === 'touchpoint') return [
      [t('fields.location', { defaultValue: 'Location' }), e.location || '—'],
      [t('fields.description', { defaultValue: 'Description' }), e.description || '—'],
    ]
    return [] as [string, string][]
  })()

  const ownership = (() => {
    const e: any = entity
    const rows: [string, string][] = []
    if (config.name === 'company') rows.push([t('fields.owner', { defaultValue: 'Owner' }), e.owner_name || '—'])
    return rows
  })()

  const relatedCompanyId = (entity as any).company?.id as string | undefined
  const relatedCompanyName = (entity as any).company?.name as string | undefined

  return (
    <div className="drawer-detail nx-drawer-v2">
      {/* ═══ Header（v3 設計 — 同 details page）═══ */}
      <div className="identity-row" style={{ alignItems: 'flex-start', gap: 'var(--space-3)' }}>
        <div className="identity-left">
          <div className="avatar nx-drawer-avatar">{avatarLabel}</div>
          <div className="id-block">
            <div className="id-name-row">
              <h1 className="id-name nx-drawer-idname">{entityName}</h1>
              {(entity as any).status && (
                <span className={`status-pill rag-${ragForStatus(String((entity as any).status))}`}>{(entity as any).status}</span>
              )}
            </div>
            {sublineParts.length > 0 && (
              <div className="id-subline">
                {sublineParts.slice(0, 3).map((s, i) => (
                  <span key={i}>{s}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ Actions ═══ */}
      <div className="nx-drawer-actions">
        {editOpen ? (
          <>
            <button onClick={cancelEdit} disabled={saving} className="btn btn-ghost btn-sm">{t('common.cancel')}</button>
            <button onClick={handleSave} disabled={saving} className="btn btn-dark btn-sm">
              {saving ? t('common.saving') : t('common.save')}
            </button>
          </>
        ) : (
          <>
            <button onClick={() => setDeleteModalOpen(true)} className="btn btn-ghost btn-sm">
              <SvcIcon name="trash-2" size={13} /> {t('common.delete')}
            </button>
            <button onClick={() => {
              const route = config.routePrefix || config.labelPlural.toLowerCase()
              onClose()
              navigate(`/${route}/${entity.id}`)
            }} className="btn btn-ghost btn-sm">
              <SvcIcon name="external-link" size={13} /> {t('common.openFull')}
            </button>
            <button onClick={() => setEditOpen(true)} className="btn btn-dark btn-sm">
              <SvcIcon name="pencil" size={13} /> {t('common.edit')}
            </button>
            <button
              onClick={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: { id: entity.id, name: entityName, type: config.name } } }))}
              className="btn btn-ai btn-sm"
            >
              <SvcIcon name="sparkles" size={13} /> {t('common.askAI', { defaultValue: 'Ask AI' })}
            </button>
          </>
        )}
      </div>

      {/* ═══ KPI（v3 kpi-strip）═══ */}
      {highlights.length > 0 && (
        <div className="kpi-strip nx-drawer-kpis">
          {highlights.map((h, i) => (
            <div className="kpi-cell" key={i}>
              <div className="kpi-label">{h.label}</div>
              <div className={`kpi-value ${h.trend === 'up' ? 'trend-up' : h.trend === 'down' ? 'trend-down' : ''}`}>
                {h.value}
                {h.trend === 'down' && <SvcIcon name="alert-triangle" size={13} />}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* SPEC preview-v3: preview 唔放任何 AI summary（全部入 Ask AI portal — 同 details page 一致） */}

      {/* ═══ Inline edit form ═══ */}
      {editOpen && (
        <div className="nx-inline-edit-panel nx-drawer-edit">
          <div className="nx-inline-edit-title">{t('common.editing', { defaultValue: '編輯' })}</div>
          <div className="nx-inline-edit-grid">
            {config.fields.filter(fld => fld.editable !== false && !['created_time', 'last_edited_time', 'created_by', 'last_edited_by'].includes(fld.type)).map(f => (
              <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
                onChange={handleChange} editOpen={true}
                relationData={{ companies: extraData?.companies }} />
            ))}
          </div>
        </div>
      )}

      {/* ═══ Sidebar-style field groups ═══ */}
      <div className="nx-drawer-sections">
        {generalInfo.length > 0 && (
          <div className="sb-card">
            <div className="sb-head">{t('common.generalInfo', { defaultValue: 'General Info' })}</div>
            {generalInfo.map(([label, value], i) => {
              if (!value || value === '—') return null
              const isCompany = config.name === 'contact' && label === t('fields.company', { defaultValue: 'Company' })
              return (
                <div className="sb-row" key={i}>
                  <span className="sb-row-label">{label}</span>
                  {isCompany && relatedCompanyId ? (
                    <span
                      className="sb-row-value nx-drawer-related-tag"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (relatedCompanyId) { onClose(); navigate(`/companies/${relatedCompanyId}`) }
                      }}
                      title={relatedCompanyName || value}
                    >
                      <SvcIcon name="user" size={12} /><span className="nx-drawer-related-tag-text">{value}</span>
                    </span>
                  ) : (
                    <span className="sb-row-value">{value}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
        {ownership.length > 0 && (
          <div className="sb-card">
            <div className="sb-head">{t('common.ownership', { defaultValue: 'Ownership' })}</div>
            {ownership.map(([label, value], i) => {
              if (!value || value === '—') return null
              return (
                <div className="sb-row" key={i}>
                  <span className="sb-row-label">{label}</span>
                  <span className="sb-row-value">{value}</span>
                </div>
              )
            })}
          </div>
        )}

        {/* Related company navigation (preserve onNavigate behaviour) */}
        {relatedCompanyId && (
          <div className="sb-card">
            <div className="sb-head">{t('common.related', { defaultValue: 'Related' })}</div>
            <div
              className="nx-drawer-related"
              onClick={() => {
                if (relatedCompanyId) { onClose(); navigate(`/companies/${relatedCompanyId}`) }
              }}
            >
              <SvcIcon name="user" size={13} />
              <span>{relatedCompanyName || String(relatedCompanyId)}</span>
            </div>
          </div>
        )}
      </div>

      {/* Delete modal */}
      {deleteModalOpen && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setDeleteModalOpen(false) }}>
          <div className="modal modal-sm">
            <div className="delete-body">
              <div className="delete-icon-wrap"><SvcIcon name="trash-2" /></div>
              <h3 className="delete-heading">{t('common.deleteConfirm', { name: entityName })}</h3>
              <p className="delete-text">{t('common.cannotUndo')}</p>
            </div>
            <div className="modal-foot">
              <button onClick={() => setDeleteModalOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleDeleteConfirm} disabled={deleteLoading}
                className="btn-notification">{deleteLoading ? t('common.deleting') : t('common.delete')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

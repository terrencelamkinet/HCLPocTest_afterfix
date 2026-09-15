import { useState, useEffect, useCallback, Suspense } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../components/SvcIcon'
import { apiClient } from '../lib/api'
import { FieldsRenderer } from './shared/FieldsRenderer'
import { buildPayload, formatDate, apiErrorToString } from './shared/field-utils'
import { statusColors } from './module-types'
import { localizeResourceLabel, localizeTabLabel } from './shared/labels'
import MobileSection from './shared/MobileSection'
import { useMobile } from './shared/useMobile'
import type { ModuleConfig, EntityRecord } from './module-types'
import { isModuleEnabled } from './enabled-modules'

interface Props {
  config: ModuleConfig
  tabRenderers?: Record<string, React.ComponentType<{
    entity: EntityRecord
    moduleConfig: ModuleConfig
    refresh: () => void
  }>>
  extraData?: Record<string, any>
  /** Optional header action buttons (rendered in non-edit mode, before delete/edit) */
  actions?: React.ReactNode
}

export default function GenericDetailPage({ config, tabRenderers, extraData, actions }: Props) {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const pathParts = location.pathname.split('/').filter(Boolean)
  const { isMobile, showFullTab, setShowFullTab } = useMobile()

  const [entity, setEntity] = useState<EntityRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState(config.detailTabs?.[0]?.id || 'details')

  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const fetchEntity = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const eRes = await apiClient.get<EntityRecord>(`${config.apiPath}/${id}`)
      setEntity(eRes)
      const f: Record<string, any> = {}
      for (const field of config.fields) {
        let val = (eRes as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') {
          val = val ? [val] : []
        }
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    } catch (e: any) {
      setError(e.detail || e.message)
    } finally {
      setLoading(false)
    }
  }, [config.apiPath, id])

  useEffect(() => { fetchEntity() }, [fetchEntity])

  const handleChange = (key: string, value: any) => {
    setForm(f => ({ ...f, [key]: value }))
  }

  const openEdit = () => setEditOpen(true)

  const cancelEdit = () => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of config.fields) {
        let val = entity[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') {
          val = val ? [val] : []
        }
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

  const handleDeleteClick = () => setDeleteModalOpen(true)

  const handleDeleteConfirm = async () => {
    if (!entity) return
    setDeleteLoading(true)
    try {
      await apiClient.delete(`${config.apiPath}/${entity.id}`)
      navigate(`/${config.routePrefix || config.name + 's'}`)
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setDeleteLoading(false) }
  }

  if (loading) {
    return (
      <div className="contact-detail-page loading">
        <div className="h-8 bg-slate-200 rounded w-48" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 h-64 bg-slate-100 rounded-xl" />
          <div className="lg:col-span-2 h-96 bg-slate-100 rounded-xl" />
        </div>
      </div>
    )
  }

  if (error || !entity) {
    return (
      <div className="contact-detail-page">
        <button onClick={() => navigate(`/${config.routePrefix || config.name + 's'}`)}
          className="flex items-center gap-1 text-sm hover:underline mb-4 back-link">
          <SvcIcon name="arrow-left" className="w-4 h-4" /> {t('common.backToLabel', { label: localizeResourceLabel(config.name, true, config.labelPlural, t) })}
        </button>
        <div className="error-box">
          <span className="error-text">{error || t('common.notFound', { label: localizeResourceLabel(config.name, false, config.label, t) })}</span>
          <button onClick={fetchEntity} className="error-retry-btn">{t('common.retry')}</button>
        </div>
      </div>
    )
  }

  const initials = (entity['name'] || '').split(' ').map((n: string) => n[0]).join('').toUpperCase().slice(0, 2)
  const lastTouchDate = entity['updated_at'] ? formatDate(entity['updated_at']) : entity['created_at'] ? formatDate(entity['created_at']) : '—'
  const nameField = config.fields.find(f => f.type === 'title')?.key || config.titleField || 'name'
  const entityName = String(entity[nameField] || entity.id || '')

  const visibleTabs = config.detailTabs?.filter(c => !c.condition || c.condition(entity)) || []

  const detailsTab = config.detailTabs?.find(c => c.id === 'details')
  const detailFields = (detailsTab?.fields
    ? config.fields.filter(f => detailsTab.fields!.includes(f.key))
    : config.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  // Grouped field renderer (NovaCRM-style architecture: labelled sections, 2-col grid each)
  const renderDetailFields = () => {
    const renderOne = (f: typeof detailFields[number]) => (
      <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
        onChange={handleChange} editOpen={editOpen} relationData={{ companies: extraData?.companies }} />
    )
    if (!config.fieldGroups) return detailFields.map(renderOne)
    return config.fieldGroups.map(g => {
      const gFields = detailFields.filter(f => g.fields.includes(f.key))
      if (!gFields.length) return null
      return (
        <div className="field-group" key={g.id}>
          <div className="field-group-title">{t(`common.fieldGroup.${g.id}`, { defaultValue: g.label })}</div>
          <div className="detail-form-grid">{gFields.map(renderOne)}</div>
        </div>
      )
    })
  }

  return (
    <div className="contact-detail-page">
      <nav className="breadcrumb">
        {pathParts.map((part, i) => {
          const isLast = i === pathParts.length - 1
          const label = part === 'dashboard' ? t('common.home') : part.charAt(0).toUpperCase() + part.slice(1)
          const to = '/' + pathParts.slice(0, i + 1).join('/')
          return isLast ? (
            <span key={part} className="cur">{entityName || part}</span>
          ) : (
            <span key={part}><Link to={to}>{label}</Link><span className="bc-sep">/</span></span>
          )
        })}
      </nav>

      <div className="page-header">
        <div className="title-row">
          <button onClick={() => navigate(`/${config.routePrefix || config.name + 's'}`)} className="back-btn">
            <SvcIcon name="arrow-left" className="w-4 h-4" />
          </button>
          <h1>{entityName}</h1>
        </div>
        <div className="header-actions">
          {editOpen ? (
            <>
              <button onClick={cancelEdit} disabled={saving} className="btn-ghost">{t('common.cancel')}</button>
              <button onClick={handleSave} disabled={saving} className="btn-primary">
                {saving ? t('common.saving') : t('common.saveChanges')}
              </button>
            </>
          ) : (
            <>
              {actions}
              <button onClick={handleDeleteClick} className="btn-danger">
                <SvcIcon name="trash-2" className="icon-16" /> {t('common.delete')}
              </button>
              <button onClick={openEdit} className="btn-primary">
                <SvcIcon name="edit-3" className="icon-16" /> {t('common.edit')}
              </button>
            </>
          )}
        </div>
      </div>

      {editOpen && (
        <div className="edit-banner">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
          {t('common.editingMode')}
        </div>
      )}

      <div className="detail-grid">
        {!config.hideProfileCard && <div className="profile-card">
          <div className="profile-avatar">{initials}</div>
          <h3>{entityName}</h3>
          <div className="role">{[entity['job_title'], entity['company']?.name].filter(Boolean).join(' · ') || '—'}</div>

          {config.profileInfoList ? (
            <>
              {/* Quick actions: call / email / WhatsApp */}
              <div className="quick-actions">
                {entity['phone'] && (
                  <a href={`tel:${String(entity['phone']).replace(/[^\d+]/g, '')}`} className="btn-secondary">
                    <SvcIcon name="phone" className="w-3.5 h-3.5" /> {t('common.call')}
                  </a>
                )}
                {entity['email'] && (
                  <a href={`mailto:${entity['email']}`} className="btn-secondary">
                    <SvcIcon name="mail" className="w-3.5 h-3.5" /> {t('common.email')}
                  </a>
                )}
                {entity['phone'] && (
                  <a href={`https://wa.me/${String(entity['phone']).replace(/[^\d]/g, '')}`} target="_blank" rel="noopener noreferrer" className="btn-secondary">
                    <SvcIcon name="message-circle" className="w-3.5 h-3.5" /> {t('common.message')}
                  </a>
                )}
              </div>

              {/* Label:value info list */}
              <div className="info-list">
                {entity['phone'] && (
                  <div className="info-row">
                    <span className="info-label">{t('common.phone')}</span>
                    <span className="info-value">{entity['phone']}</span>
                  </div>
                )}
                {entity['email'] && (
                  <div className="info-row">
                    <span className="info-label">{t('common.email')}</span>
                    <span className="info-value">{entity['email']}</span>
                  </div>
                )}
                {entity['company'] && (
                  <div className="info-row">
                    <span className="info-label">{t('common.company')}</span>
                    <span className="info-value">{(entity['company'] as any).name}</span>
                  </div>
                )}
                <div className="info-row">
                  <span className="info-label">{t('common.owner')}</span>
                  <span className="info-value">{entity['contact_type'] || t('common.unassigned')}</span>
                </div>
                <div className="info-row">
                  <span className="info-label">{t('common.lastTouch')}</span>
                  <span className="info-value">{lastTouchDate}</span>
                </div>
                {entity['address'] && (
                  <div className="info-row">
                    <span className="info-label">{t('common.address')}</span>
                    <span className="info-value">{entity['address']}</span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="tal">
              {entity['email'] && (
                <div className="profile-field">
                  <SvcIcon name="mail" className="w-3.5 h-3.5" />
                  <span>{entity['email']}</span>
                </div>
              )}
              {entity['phone'] && (
                <div className="profile-field">
                  <SvcIcon name="phone" className="w-3.5 h-3.5" />
                  <span>{entity['phone']}</span>
                </div>
              )}
              <div className="profile-field">
                <SvcIcon name="user" className="w-3.5 h-3.5" /> {t('common.ownerLabel', { name: entity['contact_type'] || t('common.unassigned') })}
              </div>
              <div className="profile-field">
                <SvcIcon name="clock" className="w-3.5 h-3.5" /> {t('common.lastTouch', { date: lastTouchDate })}
              </div>
              {entity['company'] && (
                <div className="profile-field">
                  <SvcIcon name="building-2" className="w-3.5 h-3.5" />
                  <span>{(entity['company'] as any).name}</span>
                </div>
              )}
            </div>
          )}

          <div className="tag-row">
            <span className={`select-tag ${statusColors[entity['status']] || 'tag-default'}`}>{entity['status'] || t('status.active')}</span>
            {Array.isArray(entity['tags']) && entity['tags'].map((t: string) => <span key={t} className="tag">{t}</span>)}
            {entity['contact_type'] && entity['contact_type'] !== 'Unassigned' && <span className="tag">{entity['contact_type']}</span>}
          </div>
        </div>}

        <div className={isMobile ? 'mobile-stacked-sections' : ''}>
          {/* Mobile: single full tab view */}
          {isMobile && showFullTab ? (
            <>
              <button onClick={() => setShowFullTab(null)} className="btn-ghost" style={{ marginBottom: '10px', fontSize: '12px' }}>
                {t('common.backToAll')}
              </button>
              {visibleTabs.filter(c => c.id === showFullTab).map(c => {
                if (c.id === 'details') {
                  return (
                    <div className="panel" key="details">
                      <div className="panel-head"><h3>{t('common.infoSection', { label: localizeResourceLabel(config.name, false, config.label, t) })}</h3></div>
                      <div className="p-16">{renderDetailFields()}</div>
                    </div>
                  )
                }
                const CustomRenderer = c.render || tabRenderers?.[c.id]
                if (CustomRenderer) {
                  return (
                    <Suspense key={c.id} fallback={<div className="panel"><div className="panel-head"><h3>{localizeTabLabel(c.id, c.label, t)}</h3></div><div className="empty-state">Loading {t('common.loadingTab', { label: localizeTabLabel(c.id, c.label, t).toLowerCase() })}</div></div>}>
                      <CustomRenderer entity={entity} moduleConfig={config} refresh={fetchEntity} />
                    </Suspense>
                  )
                }
                return (
                  <div className="panel" key={c.id}>
                    <div className="panel-head"><h3>{localizeTabLabel(c.id, c.label, t)}</h3></div>
                    <div className="empty-state">{t('common.noDataTab', { label: localizeTabLabel(c.id, c.label, t).toLowerCase() })}</div>
                  </div>
                )
              })}
            </>
          /* Desktop: tabs + content */
          ) : !isMobile && (
            <>
              <div className="tabs">
                {visibleTabs.map(c => (
                  <div key={c.id} className={`tab ${tab === c.id ? 'active' : ''}`}
                    onClick={() => setTab(c.id)}>
                    {localizeTabLabel(c.id, c.label, t)}
                  </div>
                ))}
              </div>

              {tab === 'details' && (
                <div className="panel">
                  <div className="panel-head">
                    <h3>{t('common.infoSection', { label: localizeResourceLabel(config.name, false, config.label, t) })}</h3>
                  </div>
                  <div className="p-16">{renderDetailFields()}</div>
                </div>
              )}

              {visibleTabs.filter(cfg => cfg.id !== 'details').map(cfg => {
                if (tab === cfg.id) {
                  const CustomRenderer = cfg.render || tabRenderers?.[cfg.id]
                  if (CustomRenderer) {
                    return (
                      <Suspense key={cfg.id} fallback={<div className="panel"><div className="panel-head"><h3>{localizeTabLabel(cfg.id, cfg.label, t)}</h3></div><div className="empty-state">Loading {t('common.loadingTab', { label: localizeTabLabel(cfg.id, cfg.label, t).toLowerCase() })}</div></div>}>
                        <CustomRenderer entity={entity} moduleConfig={config} refresh={fetchEntity} />
                      </Suspense>
                    )
                  }
                  return (
                    <div className="panel" key={cfg.id}>
                      <div className="panel-head">
                        <h3>{localizeTabLabel(cfg.id, cfg.label, t)}</h3>
                      </div>
                      <div className="empty-state">{localizeTabLabel(cfg.id, cfg.label, t)} {t('common.noDataTab', { label: localizeTabLabel(cfg.id, cfg.label, t).toLowerCase() })}</div>
                    </div>
                  )
                }
                return null
              })}
            </>
          )}

          {/* Mobile stacked sections */}
          {isMobile && !showFullTab && visibleTabs.map(c => {
            if (c.id === 'details') {
              const fieldCount = detailFields.length
              return (
                <MobileSection key="details" label="fields" total={fieldCount}
                  onViewAll={() => setShowFullTab('details')}>
                  <div className="panel">
                    <div className="panel-head"><h3>{t('common.infoSection', { label: localizeResourceLabel(config.name, false, config.label, t) })}</h3></div>
                    <div className="p-16">{renderDetailFields()}</div>
                  </div>
                </MobileSection>
              )
            }
            const CustomRenderer = tabRenderers?.[c.id]
            if (CustomRenderer) {
              return (
                <MobileSection key={c.id} label={localizeTabLabel(c.id, c.label, t).toLowerCase()} total={0}
                  onViewAll={() => setShowFullTab(c.id)}>
                  <Suspense fallback={<div className="empty-state">{t('common.loadingTab', { label: localizeTabLabel(c.id, c.label, t).toLowerCase() })}</div>}>
                    <CustomRenderer entity={entity} moduleConfig={config} refresh={fetchEntity} />
                  </Suspense>
                </MobileSection>
              )
            }
            return (
              <div className="panel" key={c.id}>
                <div className="panel-head"><h3>{localizeTabLabel(c.id, c.label, t)}</h3></div>
                <div className="empty-state">{t('common.noDataTab', { label: localizeTabLabel(c.id, c.label, t).toLowerCase() })}</div>
              </div>
            )
          })}
        </div>
      </div>

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

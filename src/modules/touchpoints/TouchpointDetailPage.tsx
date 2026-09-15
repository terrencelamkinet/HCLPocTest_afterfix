import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NexusDetailPageV2, type DetailTab, type HighlightWidget } from '../shared/NexusDetailPageV2'
import touchpointConfig from './config'
import { useEntity } from '../hooks/useEntity'
import { FieldsRenderer } from '../shared/FieldsRenderer'
import { buildPayload, apiErrorToString } from '../shared/field-utils'
import { isModuleEnabled } from '../enabled-modules'
import { apiClient } from '../../lib/api'

function formatDate(d?: string): string {
  if (!d) return '—'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '—'
  return dt.toLocaleDateString()
}

export default function TouchpointDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const { entity, loading, refresh } = useEntity('touchpoint', id!)

  // 保留原有 contacts/companies fetch
  const [contacts, setContacts] = useState<{ id: string; name: string }[]>([])
  const [companies, setCompanies] = useState<{ id: string; name: string }[]>([])
  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  /* SPEC mobile-crm-svg-uiux §12.3: Save disabled until something changes */
  const [editDirty, setEditDirty] = useState(false)

  useEffect(() => {
    Promise.all([
      // 2026-09-11: the CRM list endpoints take limit/offset, NOT page_size. The old
      // page_size=500 was silently ignored, so only the default 50 contacts loaded and
      // ~170 of 220 could never be found in the contact picker ("用戶還是不能搜尋").
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/contacts?limit=500').then(r => setContacts(r.items || [])).catch(() => {}),
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/companies?limit=500').then(r => setCompanies(r.items || [])).catch(() => {}),
    ])
  }, [])

  // Edit state — initialised once entity is loaded
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of touchpointConfig.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
  }, [entity])

  if (loading || !entity) {
    return <div className="nx-loading-shell">{t('common.loading', { defaultValue: 'Loading…' })}</div>
  }

  const openEdit = () => { setEditDirty(false); setEditOpen(true) }

  const cancelEdit = () => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of touchpointConfig.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
    setEditOpen(false)
    setEditDirty(false)
  }

  const handleChange = (key: string, value: any) => {
    setForm(f => ({ ...f, [key]: value }))
    setEditDirty(true)
  }

  const handleSave = async () => {
    if (!entity) return
    setSaving(true)
    try {
      await apiClient.patch(`/api/v1/crm/touchpoints/${entity.id}`, buildPayload(form, touchpointConfig.fields))
      setEditOpen(false)
      setEditDirty(false)
      refresh()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const detailFields = (touchpointConfig.detailTabs?.find(tb => tb.id === 'details')?.fields
    ? touchpointConfig.fields.filter(f => touchpointConfig.detailTabs!.find(tb => tb.id === 'details')!.fields!.includes(f.key))
    : touchpointConfig.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  const participantNames = (Array.isArray(entity.participants) ? entity.participants : [])
    .map((p: any) => (typeof p === 'object' && p ? (p.name || p.title || p.id) : p)).join(', ')
  const companyNames = (Array.isArray((entity as any).companies) ? (entity as any).companies : [])
    .map((c: any) => (typeof c === 'object' && c ? (c.name || c.id) : c)).join(', ')

  const subline = [
    entity.type,
    formatDate(entity.date),
    participantNames,
  ].filter(Boolean) as string[]

  const highlights: HighlightWidget[] = [
    { label: t('fields.type', { defaultValue: 'Type' }), value: entity.type || '—', trend: 'neutral' },
    { label: t('fields.date', { defaultValue: 'Date' }), value: formatDate(entity.date), trend: 'neutral' },
    { label: t('fields.duration', { defaultValue: 'Duration' }), value: entity.duration_minutes != null ? `${entity.duration_minutes}m` : '—', trend: 'neutral' },
    { label: t('fields.location', { defaultValue: 'Location' }), value: entity.location || '—', trend: 'neutral' },
  ]

  /* SPEC detail-polish T2: 之前 config 動態 tabs 全部 render「No data」空殼 —
     精簡做單一 Overview（touchpoint 主體 = description 全文） */
  const tabs: DetailTab[] = [
    {
      key: 'overview',
      label: t('common.overview', { defaultValue: 'Overview' }),
      render: () => (
        <div className="panel">
          <div className="panel-head"><h3>{t('fields.description', { defaultValue: 'Description' })}</h3></div>
          {entity.description ? (
            <div style={{ padding: '12px 16px', fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: 'var(--color-text-primary)' }}>{entity.description}</div>
          ) : (
            <div className="empty-state">{t('common.noData', { defaultValue: 'No data' })}</div>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <NexusDetailPageV2
        entity={entity}
        moduleConfig={touchpointConfig}
        avatarLabel={String(entity.title || '?').slice(0, 2).toUpperCase()}
        subline={subline.slice(0, 3)}
        highlights={highlights}
        breadcrumbLabel={t('pages.touchpoints.title', { defaultValue: 'Touchpoints' })}
        breadcrumbHref="/touchpoints"
        onEdit={openEdit}
        editMode={editOpen}
        editSaving={saving}
        editDirty={editDirty}
        /* 2026-09-11: mobile (<=900px) renders the form ONLY from this prop, and the
           sticky mobile bar's 儲存 button requires editMode && editForm && isMobile.
           Without it the whole add/edit form was blank on mobile and the save button
           was absent — while Contacts/Companies/Projects all pass it (the reference). */
        editForm={
          <div className="edit-form-mobile">
            <div className="nx-inline-edit-grid">
              {detailFields.map(f => (
                <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
                  onChange={handleChange} editOpen={true}
                  relationData={{ contacts, companies }} />
              ))}
            </div>
          </div>
        }
        onSaveEdit={handleSave}
        onCancelEdit={cancelEdit}
        onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: { ...entity, type: 'touchpoint' } } }))}
        sidebarSections={[
          {
            title: t('common.generalInfo', { defaultValue: 'General Info' }),
            fields: [
              { label: t('fields.type', { defaultValue: 'Type' }), value: entity.type || '—' },
              { label: t('fields.description', { defaultValue: 'Description' }), value: entity.description || '—' },
              { label: t('fields.date', { defaultValue: 'Date' }), value: formatDate(entity.date) },
              { label: t('fields.duration', { defaultValue: 'Duration' }), value: entity.duration_minutes != null ? `${entity.duration_minutes}m` : '—' },
              { label: t('fields.location', { defaultValue: 'Location' }), value: entity.location || '—' },
              { label: t('fields.contact', { defaultValue: 'Contact' }), value: participantNames || '—' },
              { label: t('fields.company', { defaultValue: 'Company' }), value: companyNames || '—' },
            ],
          },
          {
            title: t('common.ownership', { defaultValue: 'Ownership' }),
            fields: [
              { label: t('fields.created', { defaultValue: 'Created' }), value: formatDate(entity.created_at) },
            ],
          },
        ]}
        tabs={tabs}
      />
      {editOpen && (
        <div className="nx-inline-edit-panel">
          <div className="nx-inline-edit-title">{t('common.editing', { defaultValue: '編輯' })}</div>
          <div className="nx-inline-edit-grid">
            {detailFields.map(f => (
              <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
                onChange={handleChange} editOpen={true}
                relationData={{ contacts, companies }} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NexusDetailPageV2, type DetailTab, type HighlightWidget, timeAgoShort } from '../shared/NexusDetailPageV2'
import companyConfig from './config'
import {
  ContactsTab, ProjectsTab, ProductsTab,
  PartnersTab, TouchpointsTab, NotesTab, TasksTab,
} from './CompanyDetailTabs'
import { useEntity } from '../hooks/useEntity'
import { V2ActivityTimeline } from '../shared/V2ActivityTimeline'
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

export default function CompaniesDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const { entity, loading, refresh } = useEntity('company', id!)

  // Order of hooks is fixed — all useEntity/useState hooks before early return
  const [taskCount, setTaskCount] = useState<number | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!id) return
    let alive = true
    apiClient.get<{ items: unknown[]; total?: number }>(`/api/v1/crm/tasks?company_id=${id}&limit=1`)
      .then(r => { if (alive) setTaskCount(r.total ?? null) })
      .catch(() => { if (alive) setTaskCount(null) })
    return () => { alive = false }
  }, [id])

  // Edit state — initialised once entity is loaded
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of companyConfig.fields) {
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

  const openEdit = () => setEditOpen(true)

  const cancelEdit = () => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of companyConfig.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
    setEditOpen(false)
  }

  const handleChange = (key: string, value: any) => setForm(f => ({ ...f, [key]: value }))

  const handleSave = async () => {
    if (!entity) return
    setSaving(true)
    try {
      await apiClient.patch(`/api/v1/crm/companies/${entity.id}`, buildPayload(form, companyConfig.fields))
      setEditOpen(false)
      refresh()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const subline = [entity.industry, entity.category, entity.city || entity.address].filter(Boolean) as string[]

  const highlights: HighlightWidget[] = [
    /* SPEC detail-v3: company KPI 對齊 mockup — Active Projects/Contacts/Overdue/Health/Last Update */
    { label: t('common.activeProjects', { defaultValue: 'Active Projects' }), value: String(entity.active_projects_count ?? '—'), trend: 'neutral' },
    { label: t('common.contacts', { defaultValue: 'Contacts' }), value: String(entity.contacts_count ?? '—'), trend: 'neutral' },
    { label: t('common.overdueTasks', { defaultValue: 'Overdue Tasks' }), value: String(taskCount ?? entity.overdue_tasks_count ?? '—'), trend: ((taskCount ?? 0) > 0 ? 'down' : 'neutral') },
    { label: t('common.healthScore', { defaultValue: 'Health Score' }), value: entity.health_score ?? '—', trend: 'neutral' },
    { label: t('common.lastUpdate', { defaultValue: 'Last Update' }), value: timeAgoShort(entity.updated_at), trend: 'neutral' },
  ]

  const detailFields = (companyConfig.detailTabs?.find(tb => tb.id === 'details')?.fields
    ? companyConfig.fields.filter(f => companyConfig.detailTabs!.find(tb => tb.id === 'details')!.fields!.includes(f.key))
    : companyConfig.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  const tabs: DetailTab[] = [
    /* SPEC detail-polish T2: 移除重複 Overview（同 timeline 一樣 render activity）；
       Deal module 未開發 → 唔 mount 空 Deals tab */
    { key: 'timeline', label: t('common.timeline', { defaultValue: 'Timeline' }), render: () => <V2ActivityTimeline entityId={id!} filterType="company" /> },
    { key: 'contacts', label: t('common.contacts', { defaultValue: 'Contacts' }), render: () => <ContactsTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'projects', label: t('common.projects', { defaultValue: 'Projects' }), render: () => <ProjectsTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'products', label: t('common.products', { defaultValue: 'Products' }), render: () => <ProductsTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'partners', label: t('common.partners', { defaultValue: 'Partners' }), render: () => <PartnersTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'tasks', label: t('common.tasks', { defaultValue: 'Tasks' }), render: () => <TasksTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'touchpoints', label: t('common.touchpoints', { defaultValue: 'Touchpoints' }), render: () => <TouchpointsTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
    { key: 'notes', label: t('common.notes', { defaultValue: 'Notes' }), render: () => <NotesTab entity={entity} moduleConfig={companyConfig} refresh={refresh} /> },
  ]

  return (
    <>
      <NexusDetailPageV2
        entity={entity}
        moduleConfig={companyConfig}
        avatarLabel={String(entity.name || '?').slice(0, 2).toUpperCase()}
        subline={subline.slice(0, 3)}
        highlights={highlights}
        breadcrumbLabel={t('pages.companies.title', { defaultValue: 'Companies' })}
        breadcrumbHref="/companies"
        onEdit={openEdit}
        editMode={editOpen}
        editSaving={saving}
        onSaveEdit={handleSave}
        onCancelEdit={cancelEdit}
        onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: { ...entity, type: 'company' } } }))}
        sidebarSections={[
          {
            title: t('common.generalInfo', { defaultValue: 'General Info' }),
            fields: [
              { label: t('fields.industry', { defaultValue: 'Industry' }), value: entity.industry || '—' },
              { label: t('fields.category', { defaultValue: 'Category' }), value: entity.category || '—' },
              { label: t('fields.ceo', { defaultValue: 'CEO' }), value: entity.ceo_name || '—' },
              { label: t('fields.website', { defaultValue: 'Website' }), value: entity.website || '—', aiEnriched: !!entity.website_ai_filled },
              { label: t('fields.phone', { defaultValue: 'Phone' }), value: entity.phone || '—' },
              { label: t('fields.address', { defaultValue: 'Address' }), value: entity.address || '—' },
              { label: t('fields.domain', { defaultValue: 'Domain' }), value: entity.domain || '—' },
            ],
          },
          {
            title: t('common.ownership', { defaultValue: 'Ownership' }),
            fields: [
              { label: t('fields.owner', { defaultValue: 'Owner' }), value: entity.owner_name || String(entity.owner_id || '') || '—' },
              { label: t('fields.created', { defaultValue: 'Created' }), value: formatDate(entity.created_at) },
              { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—' },
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
                onChange={handleChange} editOpen={true} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

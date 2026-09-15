import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NexusDetailPageV2, type DetailTab, type HighlightWidget } from '../shared/NexusDetailPageV2'
import projectConfig from './config'
import { useEntity } from '../hooks/useEntity'
import { FieldsRenderer } from '../shared/FieldsRenderer'
import { buildPayload, apiErrorToString } from '../shared/field-utils'
import { isModuleEnabled } from '../enabled-modules'
import { apiClient } from '../../lib/api'
import EntityNotesPanel from '../shared/EntityNotesPanel'

function formatDate(d?: string): string {
  if (!d) return '—'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '—'
  return dt.toLocaleDateString()
}

export default function ProjectsDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const { entity, loading, refresh } = useEntity('project', id!)

  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)

  // Edit state — initialised once entity is loaded
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of projectConfig.fields) {
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
      for (const field of projectConfig.fields) {
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
      await apiClient.patch(`/api/v1/crm/projects/${entity.id}`, buildPayload(form, projectConfig.fields))
      setEditOpen(false)
      refresh()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const detailFields = (projectConfig.detailTabs?.find(tb => tb.id === 'details')?.fields
    ? projectConfig.fields.filter(f => projectConfig.detailTabs!.find(tb => tb.id === 'details')!.fields!.includes(f.key))
    : projectConfig.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  const overdue = entity.deadline ? (new Date(entity.deadline) < new Date() && entity.status !== 'completed') : false
  const subline = [
    entity.status,
    entity.priority,
    (entity.company as any)?.name || '—',
  ].filter(Boolean).filter(v => v !== '—') as string[]

  const highlights: HighlightWidget[] = [
    { label: t('common.tasks', { defaultValue: 'Tasks' }), value: entity.tasks_count ?? '—', trend: 'neutral' },
    { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—', trend: 'neutral' },
    { label: t('fields.priority', { defaultValue: 'Priority' }), value: entity.priority || '—', trend: 'neutral' },
    { label: t('common.deadline', { defaultValue: 'Deadline' }), value: formatDate(entity.deadline), trend: (overdue ? 'down' : 'neutral') },
  ]

  // 沿用 config detailTabs 嘅 renderers（e.g. timeline → ProjectDetailCalendar）
  const tabs: DetailTab[] = (projectConfig.detailTabs || [])
    .filter(tb => tb.id !== 'details') // details 欄位已由 sidebar 展示
    .map(tb => ({
      key: tb.id,
      label: t(`common.${tb.id}`, { defaultValue: tb.label }),
      render: () => {
        if (tb.id === 'notes') {
          return <EntityNotesPanel entityType="project" entityId={String(entity.id)} filterKey="project_id" />
        }
        const R = tb.render
        if (R) return <R entity={entity} moduleConfig={projectConfig} refresh={refresh} />
        /* 2026-09-13 修（用戶報：Details page 見到「No {{label}} yet」）：
           common.noDataTab 個 key 本身含 {{label}}，但呢度冇傳 label；i18next 因為
           key 存在就唔會用 defaultValue → 直接將 placeholder 原碼寫出嚟。
           傳返 tab 標題做 label（同上面 label: 用同一個 expression）。 */
        return <div className="nx-empty-state">{t('common.noDataTab', { label: t(`common.${tb.id}`, { defaultValue: tb.label }), defaultValue: 'No data' })}</div>
      },
    }))

  return (
    <>
      <NexusDetailPageV2
        entity={entity}
        moduleConfig={projectConfig}
        avatarLabel={String(entity.name || '?').slice(0, 2).toUpperCase()}
        subline={subline.slice(0, 3)}
        highlights={highlights}
        breadcrumbLabel={t('pages.projects.title', { defaultValue: 'Projects' })}
        breadcrumbHref="/projects"
        onEdit={openEdit}
        editMode={editOpen}
        editSaving={saving}
        onSaveEdit={handleSave}
        onCancelEdit={cancelEdit}
        onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: entity } }))}
        sidebarSections={[
          {
            title: t('common.generalInfo', { defaultValue: 'General Info' }),
            fields: [
              { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—' },
              { label: t('fields.priority', { defaultValue: 'Priority' }), value: entity.priority || '—' },
              { label: t('fields.startDate', { defaultValue: 'Start Date' }), value: formatDate(entity.start_date) },
              { label: t('fields.deadline', { defaultValue: 'Deadline' }), value: formatDate(entity.deadline) },
              { label: t('fields.budget', { defaultValue: 'Budget' }), value: entity.budget_amount != null ? String(entity.budget_amount) : '—' },
              { label: t('fields.company', { defaultValue: 'Company' }), value: (entity.company as any)?.name || '—' },
              { label: t('fields.description', { defaultValue: 'Description' }), value: entity.description || '—' },
            ],
          },
          {
            title: t('common.ownership', { defaultValue: 'Ownership' }),
            fields: [
              { label: t('fields.salesOwner', { defaultValue: 'Sales Owner' }), value: String(entity.sales_owner_id || '') || '—' },
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
                onChange={handleChange} editOpen={true} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

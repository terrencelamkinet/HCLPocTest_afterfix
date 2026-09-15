import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import SlideDrawer from '../../components/SlideDrawer'
import { NexusDetailPageV2, type DetailTab, type HighlightWidget } from '../shared/NexusDetailPageV2'
import taskConfig from './config'
import { useEntity } from '../hooks/useEntity'
import { FieldsRenderer } from '../shared/FieldsRenderer'
import { buildPayload, apiErrorToString } from '../shared/field-utils'
import { isModuleEnabled } from '../enabled-modules'
import { apiClient } from '../../lib/api'
import EntityNotesPanel from '../shared/EntityNotesPanel'

function tomorrowISO(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDate(d?: string): string {
  if (!d) return '—'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '—'
  return dt.toLocaleDateString()
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { entity, loading, refresh } = useEntity('task', id!)

  // 保留原有 contacts/companies fetch（relation fields）
  const [contacts, setContacts] = useState<{ id: string; name: string }[]>([])
  const [companies, setCompanies] = useState<{ id: string; name: string }[]>([])
  const [busy, setBusy] = useState<'done' | 'snooze' | null>(null)
  const [flash, setFlash] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/contacts?limit=1000').then(r => setContacts(r.items || [])).catch(() => {}),
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/companies?limit=1000').then(r => setCompanies(r.items || [])).catch(() => {}),
    ])
  }, [])

  // Edit state — initialised once entity is loaded
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of taskConfig.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
  }, [entity])

  const act = async (kind: 'done' | 'snooze') => {
    if (!id) return
    setBusy(kind)
    setFlash(null)
    try {
      const body = kind === 'done' ? { status: 'completed' } : { due_date: tomorrowISO() }
      await apiClient.patch(`/api/v1/crm/tasks/${id}`, body)
      setFlash({ kind: 'ok', text: kind === 'done' ? '✅ Task 已標記完成' : '⏰ 已推遲至聽日' })
      refresh() // refetch entity
    } catch (e: any) {
      setFlash({ kind: 'err', text: e.detail || e.message || '操作失敗' })
    } finally {
      setBusy(null)
    }
  }

  const openEdit = () => setEditOpen(true)

  const cancelEdit = () => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of taskConfig.fields) {
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
      await apiClient.patch(`/api/v1/crm/tasks/${entity.id}`, buildPayload(form, taskConfig.fields))
      setEditOpen(false)
      refresh()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const detailFields = (taskConfig.detailTabs?.find(tb => tb.id === 'details')?.fields
    ? taskConfig.fields.filter(f => taskConfig.detailTabs!.find(tb => tb.id === 'details')!.fields!.includes(f.key))
    : taskConfig.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  // Hooks 已經全部喺 early return 之前 — safe
  if (loading || !entity) {
    return <div className="nx-loading-shell">{t('common.loading', { defaultValue: 'Loading…' })}</div>
  }

  const overdue = entity.due_date ? (new Date(entity.due_date) < new Date() && entity.status !== 'done') : false
  /* SPEC contact-assoc-fix: backend resolve 咗 entity.contact/company（{id,name}）— subline 顯示關連 */
  const contactName = (entity.contact as any)?.name
  const companyName = (entity.company as any)?.name
  const subline = [entity.priority, entity.status, contactName, companyName].filter(Boolean) as string[]

  const highlights: HighlightWidget[] = [
    { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—', trend: 'neutral' },
    { label: t('fields.priority', { defaultValue: 'Priority' }), value: entity.priority || '—', trend: 'neutral' },
    { label: t('fields.dueDate', { defaultValue: 'Due Date' }), value: formatDate(entity.due_date), trend: (overdue ? 'down' : 'neutral') },
  ]

  const QuickActions = () => (
    <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
      <button className="btn-primary" disabled={busy !== null} onClick={() => act('done')}>
        {busy === 'done' ? '⋯' : '✅ 完成'}
      </button>
      <button className="btn-ghost" disabled={busy !== null} onClick={() => act('snooze')}>
        {busy === 'snooze' ? '⋯' : '⏰ 推遲至聽日'}
      </button>
    </div>
  )

  const tabs: DetailTab[] = [
    {
      key: 'overview',
      label: t('common.overview', { defaultValue: 'Overview' }),
      render: () => (
        <>
          <QuickActions />
          {flash && (
            <div className={`rounded-lg px-4 py-2 text-sm ${flash.kind === 'ok' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600'}`} style={{ marginBottom: 12 }}>
              {flash.text}
            </div>
          )}
          <div className="nx-empty-state">{t('common.noActivity', { defaultValue: '暫無活動記錄' })}</div>
        </>
      ),
    },
    {
      key: 'notes',
      label: t('common.notes', { defaultValue: 'Notes' }),
      render: () => (
        <EntityNotesPanel entityType="task" entityId={String(id)} filterKey="task_id" />
      ),
    },
  ]

  return (
    <>
      <SlideDrawer
        open={!!entity}
        onClose={() => navigate('/tasks')}
        title={t('pages.tasks.title', { defaultValue: 'Tasks' })}
        width="96vw"
        closeOnLeft
      >
      <NexusDetailPageV2
        entity={entity}
        moduleConfig={taskConfig}
        avatarLabel={String(entity.title || '?').slice(0, 2).toUpperCase()}
        subline={subline.slice(0, 3)}
        highlights={highlights}
        breadcrumbLabel={t('pages.tasks.title', { defaultValue: 'Tasks' })}
        breadcrumbHref="/tasks"
        onEdit={openEdit}
        editMode={editOpen}
        editSaving={saving}
        onSaveEdit={handleSave}
        onCancelEdit={cancelEdit}
        onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: { ...entity, type: 'task' } } }))}
        sidebarSections={[
          {
            title: t('common.generalInfo', { defaultValue: 'General Info' }),
            fields: [
              { label: t('fields.description', { defaultValue: 'Description' }), value: entity.description || '—' },
              { label: t('fields.priority', { defaultValue: 'Priority' }), value: entity.priority || '—' },
              { label: t('fields.dueDate', { defaultValue: 'Due Date' }), value: formatDate(entity.due_date) },
              { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—' },
              /* SPEC contact-assoc-fix: 關連放 General Info — click 跳轉（互相連繫） */
              ...(contactName ? [{ label: t('fields.contact', { defaultValue: 'Contact' }), value: contactName, action: { type: 'open' as const, onClick: () => navigate(`/contacts/${(entity.contact as any).id}`) } }] : []),
              ...(companyName ? [{ label: t('fields.company', { defaultValue: 'Company' }), value: companyName, action: { type: 'open' as const, onClick: () => navigate(`/companies/${(entity.company as any).id}`) } }] : []),
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
      </SlideDrawer>
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

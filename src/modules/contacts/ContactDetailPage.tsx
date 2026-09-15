import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { NexusDetailPageV2, type DetailTab, type HighlightWidget, timeAgoShort } from '../shared/NexusDetailPageV2'
import contactConfig from './config'
import { TouchpointsTab, NotesTab, ProjectsTab, TasksTab } from './ContactDetailTabs'
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

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()

  const { entity, loading, refresh } = useEntity('contact', id!)

  // 保留原有 companies fetch（用喺 relation fields / related cards）
  const [companies, setCompanies] = useState<{ id: string; name: string }[]>([])
  const [editOpen, setEditOpen] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  /* SPEC mobile-crm-svg-uiux §12.3: Save disabled 直至有改動 */
  const [editDirty, setEditDirty] = useState(false)

  useEffect(() => {
    apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/companies?limit=1000')
      .then(r => setCompanies(r.items || []))
      .catch(() => {})
  }, [])

  // Edit state — initialised once entity is loaded
  useEffect(() => {
    if (entity) {
      const f: Record<string, any> = {}
      for (const field of contactConfig.fields) {
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
      for (const field of contactConfig.fields) {
        let val = (entity as any)[field.key]
        if (field.type === 'multi_select' && typeof val === 'string') val = val ? [val] : []
        f[field.key] = val ?? (field.type === 'multi_select' ? [] : field.type === 'checkbox' ? false : '')
      }
      setForm(f)
    }
    setEditDirty(false)
    setEditOpen(false)
  }

  const handleChange = (key: string, value: any) => { setForm(f => ({ ...f, [key]: value })); setEditDirty(true) }

  /* SPEC mobile-crm-svg-uiux §5.2: ⋯ menu — 分享 / 複製電郵 / 刪除 */
  const handleShare = async () => {
    const e: any = entity
    const text = [e.name, e.job_title, e.company?.name].filter(Boolean).join(' — ')
    if (navigator.share) { try { await navigator.share({ title: e.name, text, url: window.location.href }) } catch { /* user cancelled */ } }
    else { navigator.clipboard?.writeText(window.location.href) }
  }
  const handleCopyEmail = () => {
    if (entity?.email) navigator.clipboard?.writeText(String(entity.email))
  }
  const handleDelete = async () => {
    if (!entity) return
    if (!window.confirm(t('common.deleteConfirm', { defaultValue: '確定要刪除？此操作無法復原。' }))) return
    try {
      await apiClient.delete(`/api/v1/crm/contacts/${entity.id}`)
      navigate('/contacts')
    } catch (e: any) { alert(apiErrorToString(e)) }
  }

  const handleSave = async () => {
    if (!entity) return
    setSaving(true)
    try {
      await apiClient.patch(`/api/v1/crm/contacts/${entity.id}`, buildPayload(form, contactConfig.fields))
      setEditOpen(false)
      refresh()
    } catch (e: any) { alert(apiErrorToString(e)) }
    finally { setSaving(false) }
  }

  const detailFields = (contactConfig.detailTabs?.find(tb => tb.id === 'details')?.fields
    ? contactConfig.fields.filter(f => contactConfig.detailTabs!.find(tb => tb.id === 'details')!.fields!.includes(f.key))
    : contactConfig.fields
  ).filter(f => !f.dependsOnModule || isModuleEnabled(f.dependsOnModule))

  const subline = [
    entity.job_title,
    entity.department,
    (entity.company as any)?.name || (entity.company_id ? String(entity.company_id) : ''),
  ].filter(Boolean) as string[]

  const highlights: HighlightWidget[] = [
    { label: t('common.openTasks', { defaultValue: 'Open Tasks' }), value: String(entity.open_tasks_count ?? '—'), trend: 'neutral', tab: 'tasks' },
    { label: t('common.touchpoints', { defaultValue: 'Touchpoints' }), value: String(entity.touchpoints_count ?? '—'), trend: 'neutral', tab: 'touchpoints' },
    { label: t('common.projects', { defaultValue: 'Projects' }), value: String(entity.projects_count ?? '—'), trend: 'neutral', tab: 'projects', hideOnMobile: true },
    { label: t('common.lastUpdate', { defaultValue: 'Last Update' }), value: timeAgoShort(entity.updated_at), trend: 'neutral', hideOnMobile: true },
    { label: t('common.nextFollowUp', { defaultValue: 'Next Follow-up' }), value: entity.next_follow_up ? formatDate(entity.next_follow_up) : '—', trend: 'neutral', tab: 'tasks' },
  ]

  const tabs: DetailTab[] = [
    /* SPEC detail-polish T2: 移除重複 — Overview 同 Timeline 之前 render 一模一樣嘅 activity；
       Deal module 未開發 → 唔 mount 空 Deals tab（sales 開返先加返） */
    { key: 'timeline', label: t('common.timeline', { defaultValue: 'Timeline' }), render: () => <V2ActivityTimeline entityId={id!} filterType="contact" /> },
    { key: 'tasks', label: t('common.tasks', { defaultValue: 'Tasks' }), render: () => <TasksTab entity={entity} moduleConfig={contactConfig} refresh={refresh} /> },
    { key: 'touchpoints', label: t('common.touchpoints', { defaultValue: 'Touchpoints' }), render: () => <TouchpointsTab entity={entity} moduleConfig={contactConfig} refresh={refresh} /> },
    { key: 'notes', label: t('common.notes', { defaultValue: 'Notes' }), render: () => <NotesTab entity={entity} moduleConfig={contactConfig} refresh={refresh} /> },
    { key: 'projects', label: t('common.projects', { defaultValue: 'Projects' }), render: () => <ProjectsTab entity={entity} moduleConfig={contactConfig} refresh={refresh} /> },
  ]

  return (
    <>
      <NexusDetailPageV2
        entity={entity}
        moduleConfig={contactConfig}
        avatarLabel={String(entity.name || '?').slice(0, 2).toUpperCase()}
        subline={subline.slice(0, 3)}
        highlights={highlights}
        breadcrumbLabel={t('pages.contacts.title', { defaultValue: 'Contacts' })}
        breadcrumbHref="/contacts"
        onEdit={openEdit}
        editMode={editOpen}
        editSaving={saving}
        editDirty={editDirty}
        onSaveEdit={handleSave}
        onCancelEdit={cancelEdit}
        editForm={
          <div className="edit-form-mobile">
            {detailFields.map(f => (
              <div className="efm-row" key={f.key}>
                <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
                  onChange={handleChange} editOpen={true}
                  relationData={{ companies }} />
              </div>
            ))}
          </div>
        }
        onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: { ...entity, type: 'contact' } } }))}
        mobileTitle={t('mobile.contactDetails', { defaultValue: '聯絡人詳情' })}
        mobileMenuItems={[
          { key: 'share', label: t('mobile.share', { defaultValue: '分享' }), icon: 'share', onClick: () => handleShare() },
          { key: 'copy-email', label: t('mobile.copyEmail', { defaultValue: '複製電郵地址' }), icon: 'copy', onClick: () => handleCopyEmail() },
          { key: 'delete', label: t('common.delete', { defaultValue: '刪除' }), icon: 'trash', danger: true, onClick: () => handleDelete() },
        ]}
        sidebarSections={[
          {
            title: t('common.generalInfo', { defaultValue: 'General Info' }),
            fields: [
              { label: t('fields.jobTitle', { defaultValue: 'Title' }), value: entity.job_title || '—' },
              { label: t('fields.department', { defaultValue: 'Department' }), value: entity.department || '—' },
              { label: t('fields.email', { defaultValue: 'Email' }), value: entity.email || '—', ...(entity.email ? { action: { type: 'mailto' as const, href: String(entity.email) } } : {}) },
              { label: t('fields.phone', { defaultValue: 'Phone' }), value: entity.phone || '—', ...(entity.phone ? { action: { type: 'tel' as const, href: String(entity.phone) } } : {}) },
              { label: t('fields.linkedin', { defaultValue: 'LinkedIn' }), value: entity.linkedin_url || '—', aiEnriched: !!entity.linkedin_ai_filled },
              { label: t('fields.address', { defaultValue: 'Address' }), value: entity.address || '—' },
              { label: t('fields.company', { defaultValue: 'Company' }), value: (entity.company as any)?.name || '—', ...((entity.company as any)?.id ? { action: { type: 'open' as const, onClick: () => navigate(`/companies/${(entity.company as any).id}`) } } : {}) },
            ],
          },
          {
            title: t('common.ownership', { defaultValue: 'Ownership' }),
            fields: [
              { label: t('fields.contactType', { defaultValue: 'Contact Type' }), value: entity.contact_type || '—' },
              { label: t('fields.grade', { defaultValue: 'Grade' }), value: entity.grade || '—' },
              { label: t('fields.status', { defaultValue: 'Status' }), value: entity.status || '—' },
              { label: t('fields.created', { defaultValue: 'Created' }), value: formatDate(entity.created_at) },
            ],
          },
        ]}
        relatedCards={companies.length > 0 ? [{
          title: (entity.company as any)?.name || 'Company',
          meta: (entity.company as any)?.industry || '—',
          badge: 'Company',
        }] : []}
        tabs={tabs}
      />
      {editOpen && (
        <div className="nx-inline-edit-panel">
          <div className="nx-inline-edit-title">{t('common.editing', { defaultValue: '編輯' })}</div>
          <div className="nx-inline-edit-grid">
            {detailFields.map(f => (
              <FieldsRenderer key={f.key} field={f} entity={entity} form={form}
                onChange={handleChange} editOpen={true}
                relationData={{ companies }} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

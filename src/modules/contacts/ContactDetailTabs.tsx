import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import { sanitizeHtml } from '../../lib/sanitizeHtml'
import i18n from '../../i18n/config'
import type { EntityRecord, ModuleConfig } from '../module-types'

interface TaskItem {
  id: string; title: string; status: string; priority: string; due_date: string | null
}

export function TasksTab({ entity }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient.get<{ items: TaskItem[] }>(`/api/v1/crm/tasks?contact_id=${entity.id}&limit=100`)
      .then(r => setTasks(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [entity.id])

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.contacts.detail.tasks')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{t('pages.contacts.detail.tasks')} ({tasks.length})</h3>
      </div>
      {tasks.length === 0 ? (
        <div className="empty-state">{t('pages.contacts.detail.noTasks')}</div>
      ) : (
        <div className="flex-col">
          {tasks.map(t => (
            <div key={t.id} className="list-row">
              <div className="list-main">
                <div className="list-title">{t.title}</div>
                <div className="list-sub flex items-center gap-2">
                  <span className={`badge ${t.status === 'done' ? 'badge-active' : t.status === 'in_progress' ? 'badge-warm' : 'badge-p3'}`}>{t.status}</span>
                  {t.priority && <span className={`badge ${t.priority === 'P0' ? 'badge-p0' : t.priority === 'P1' ? 'badge-p1' : 'badge-p3'}`}>{t.priority}</span>}
                </div>
              </div>
              {t.due_date && <div className="text-right text-xs">{new Date(t.due_date).toLocaleDateString()}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

interface Touchpoint {
  id: string; type: string; title: string; description: string | null
  company?: { name: string } | null; created_at: string
}
interface Deal {
  id: string; name: string; amount: number | null
  stage?: { id: string; name: string } | null
  probability: number; status: string
}
interface Note {
  id: string; title: string; content: string | null; pinned: boolean; created_at: string; contact_id: string
  /** 由 note_links 關係帶出：呢篇筆記提及此 record（但未掛住） */
  mentioned?: boolean
}
interface ActivityItem {
  id: string; action: string; entity_type: string; entity_id: string; created_at: string
}
interface ProjectLink {
  id: string; project_id: string; project_name: string
  project_amount: number | null; stage_name: string | null
  probability: number | null; role: string | null
}

function timeAgo(d: string): string {
  if (!d) return ''
  const diff = Date.now() - new Date(d).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return i18n.t('common.timeAgo.justNow')
  if (mins < 60) return i18n.t('common.timeAgo.minutes', { count: mins })
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return i18n.t('common.timeAgo.hours', { count: hrs })
  return i18n.t('common.timeAgo.days', { count: Math.floor(hrs / 24) })
}
function formatAmount(v: number | null): string {
  if (v == null) return '$0'
  return `$${v.toLocaleString()}`
}

export function TimelineTab({ entity, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ action: '', description: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([
      apiClient.get<{ items: ActivityItem[] }>('/api/v1/crm/activities?page_size=100').catch(() => ({ items: [] })),
      apiClient.get<{ items: Touchpoint[] }>(`/api/v1/crm/touchpoints?contact_id=${entity.id}&limit=100`).catch(() => ({ items: [] })),
    ]).then(([aRes, tpRes]) => {
      setActivities((aRes.items || []).filter((a: ActivityItem) => a.entity_id === entity.id))
      setTouchpoints(tpRes.items || [])
    })
  }, [entity.id])

  const timelineItems = [
    ...activities.map(a => ({ id: a.id, emoji: '📝', title: a.action, date: timeAgo(a.created_at), meta: i18n.t(`pages.contacts.detail.entityTypes.${a.entity_type}`, { defaultValue: a.entity_type?.replace(/_/g, ' ') }), sortKey: a.created_at })),
    ...touchpoints.map(tp => ({ id: tp.id, emoji: tp.type === 'call' ? '📞' : tp.type === 'email' ? '✉️' : tp.type === 'meeting' ? '🤝' : '📌', title: tp.title, date: timeAgo(tp.created_at), meta: tp.description || i18n.t(`pages.contacts.detail.touchpointTypes.${tp.type}`, { defaultValue: tp.type }), sortKey: tp.created_at })),
  ].sort((a, b) => new Date(b.sortKey).getTime() - new Date(a.sortKey).getTime())

  const handleLog = async () => {
    if (!form.action.trim()) return
    setSaving(true)
    try {
      await apiClient.post('/api/v1/crm/activities', {
        action: form.action, description: form.description,
        entity_type: 'contact', entity_id: entity.id,
      })
      setForm({ action: '', description: '' })
      setOpen(false)
      refresh()
    } catch (e: any) { alert(e.detail || e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h3>{t('pages.contacts.detail.activity')}</h3>
          <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.contacts.detail.logActivity')}</button>
        </div>
        {timelineItems.length === 0 ? (
          <div className="empty-state">{t('pages.contacts.detail.noActivity')}</div>
        ) : (
          <div className="timeline p-16">
            {timelineItems.map(item => (
              <div key={item.id} className="tl-item">
                <div className="tl-dot">{item.emoji}</div>
                <div className="tl-card">
                  <div className="tl-head">
                    <span className="t">{item.title}</span>
                    <span className="d">{item.date}</span>
                  </div>
                  <div className="tl-meta">{item.meta}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {open && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.contacts.detail.modalLogActivity')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <div>
                  <label className="field-label">{t('pages.contacts.detail.actionRequired')}</label>
                  <input type="text" value={form.action} onChange={e => setForm(f => ({ ...f, action: e.target.value }))}
                    placeholder={t('pages.contacts.detail.actionPlaceholder')} className="input-field" />
                </div>
              </div>
              <div className="form-row-1">
                <div>
                  <label className="field-label">{t('pages.contacts.detail.description')}</label>
                  <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    rows={3} placeholder={t('pages.contacts.detail.activityDescriptionPlaceholder')} className="input-field" />
                </div>
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleLog} disabled={saving || !form.action.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.contacts.detail.log')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export function DealsTab({ entity }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [deals, setDeals] = useState<Deal[]>([])
  useEffect(() => {
    apiClient.get<{ items: Deal[] }>(`/api/v1/crm/deals?contact_id=${entity.id}&limit=200`)
      .then(r => setDeals(r.items || []))
      .catch(() => {})
  }, [entity.id])

  return (
    <div className="panel">
      <div className="panel-head"><h3>{t('pages.contacts.detail.deals')}</h3></div>
      {deals.length === 0 ? (
        <div className="empty-state">{t('pages.contacts.detail.noDeals')}</div>
      ) : (
        <div className="flex-col">
          {deals.map(d => (
            <div key={d.id} className="list-row">
              <div className="list-main">
                <div className="list-title">{d.name}</div>
                <div className="list-sub">{d.stage?.name || '—'}</div>
              </div>
              <div className="text-right">
                <div className="list-title">{formatAmount(d.amount)}</div>
                <div className="list-sub">{d.probability ?? 0}%</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function TouchpointsTab({ entity, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', type: 'meeting', description: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient.get<{ items: Touchpoint[] }>(`/api/v1/crm/touchpoints?contact_id=${entity.id}&limit=100`)
      .then(r => setTouchpoints(r.items || []))
      .catch(() => {})
  }, [entity.id])

  const handleAdd = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await apiClient.post(`/api/v1/crm/touchpoints`, {
        title: form.title, type: form.type, description: form.description || null, contact_id: entity.id,
      })
      setForm({ title: '', type: 'meeting', description: '' })
      setOpen(false)
      refresh()
    } catch (e: any) { alert(e.detail || e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h3>{t('pages.contacts.detail.touchpoints')}</h3>
          <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.contacts.detail.addTouchpoint')}</button>
        </div>
        {touchpoints.length === 0 ? (
          <div className="empty-state">{t('pages.contacts.detail.noTouchpoints')}</div>
        ) : (
          <div className="flex-col">
            {touchpoints.map(tp => (
              <div key={tp.id} className="list-row">
                <div className="list-icon"><SvcIcon name="activity" /></div>
                <div className="list-main">
                  <div className="list-title">{tp.title}</div>
                  <div className="list-sub">{tp.description || '—'}</div>
                  <div className="list-sub mt-1 flex items-center gap-2">
                  <span className="badge badge-p3">{t(`pages.contacts.detail.touchpointTypes.${tp.type}`, { defaultValue: tp.type })}</span>
                    {tp.company && <span>· {tp.company.name}</span>}
                    <span className="ml-auto text-faint text-xs">{timeAgo(tp.created_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {open && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.contacts.detail.modalAddTouchpoint')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.titleRequired')}</label>
                <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder={t('pages.contacts.detail.titlePlaceholder')} className="input-field" />
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.type')}</label>
                <select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))} className="input-field">
                  <option value="meeting">{t('pages.contacts.detail.touchpointTypes.meeting')}</option>
                  <option value="call">{t('pages.contacts.detail.touchpointTypes.call')}</option>
                  <option value="email">{t('pages.contacts.detail.touchpointTypes.email')}</option>
                  <option value="namecard">{t('pages.contacts.detail.touchpointTypes.namecard')}</option>
                </select>
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.description')}</label>
                <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={2} placeholder={t('pages.contacts.detail.descriptionPlaceholder')} className="input-field" />
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleAdd} disabled={saving || !form.title.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.contacts.detail.add')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export function NotesTab({ entity, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [notes, setNotes] = useState<Note[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', content: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    /* spec §8.3 反向查詢：原本係「撈 100 條再 client-side 按 contact_id 過濾」——
       ① 會漏：新筆記掛 record 係寫 note_links（legacy FK 已經唔再寫）；
       ② 攞唔到 100 條以外嘅。改成 server-side：FK 掛住嘅 ＋ note_links 提及嘅，
       合併去重（提及但未掛住嘅標 mentioned，UI 用 chip 分辨）。 */
    Promise.all([
      apiClient.get<{ items: Note[] }>(`/api/v1/crm/notes?limit=100&contact_id=${entity.id}`),
      apiClient
        .get<{ items: Note[] }>(
          `/api/v1/crm/notes?limit=100&mention_of_type=contact&mention_of_id=${entity.id}`
        )
        .catch(() => ({ items: [] as Note[] })),
    ])
      .then(([res, mentioned]) => {
        const attached = res.items || []
        const seen = new Set(attached.map(n => n.id))
        setNotes([
          ...attached,
          ...(mentioned.items || []).filter(n => !seen.has(n.id)).map(n => ({ ...n, mentioned: true })),
        ])
      })
      .catch(() => {})
  }, [entity.id])

  const handleAdd = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await apiClient.post('/api/v1/crm/notes', {
        title: form.title, content: form.content || null, contact_id: entity.id,
      })
      setForm({ title: '', content: '' })
      setOpen(false)
      refresh()
    } catch (e: any) { alert(e.detail || e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h3>{t('pages.contacts.detail.notes')}</h3>
          <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.contacts.detail.addNote')}</button>
        </div>
        {notes.length === 0 ? (
          <div className="empty-state">{t('pages.contacts.detail.noNotes')}</div>
        ) : (
          <div className="flex-col">
            {notes.map(n => (
              <div key={n.id} className="list-row flex-col items-stretch px-5 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="list-title">
                    {n.title}
                    {n.mentioned && (
                      <span className="badge" style={{ marginLeft: 6 }}>
                        {t('notes.mentionedBadge', { defaultValue: 'Mentioned' })}
                      </span>
                    )}
                  </div>
                  {n.pinned && <span className="badge badge-p1">{t('pages.contacts.detail.pinned')}</span>}
                </div>
                {/* 筆記內容係 rich-editor HTML（同 EntityNotesPanel 一致）→ 唔可以直接 print string，
                    否則用戶會見到 <p>/<span> 原碼。用返 nxe-rendered-content 統一 render。 */}
                {n.content && (
                  <div className="nxe-rendered-content list-sub mt-1" dangerouslySetInnerHTML={{ __html: sanitizeHtml(n.content) }} />
                )}
                <p className="list-sub mt-1 text-xs">{timeAgo(n.created_at)}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {open && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.contacts.detail.modalAddNote')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.titleRequired')}</label>
                <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder={t('pages.contacts.detail.noteTitlePlaceholder')} className="input-field" />
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.description')}</label>
                <textarea value={form.content} onChange={e => setForm(f => ({ ...f, content: e.target.value }))}
                  rows={4} placeholder={t('pages.contacts.detail.noteContentPlaceholder')} className="input-field" />
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleAdd} disabled={saving || !form.title.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.contacts.detail.add')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export function ProjectsTab({ entity, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [projects, setProjects] = useState<ProjectLink[]>([])
  const [dealOptions, setDealOptions] = useState<{ id: string; name: string; amount: number | null }[]>([])
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient.get<{ items: ProjectLink[] }>(`/api/v1/crm/contacts/${entity.id}/projects?page_size=100`)
      .then(r => setProjects(r.items || []))
      .catch(() => {})
  }, [entity.id])

  const handleLink = async () => {
    if (!selected) return
    setSaving(true)
    try {
      await apiClient.post(`/api/v1/crm/contacts/${entity.id}/projects`, { project_id: selected })
      setOpen(false)
      setSelected('')
      refresh()
    } catch (e: any) { alert(e.detail || e.message) }
    finally { setSaving(false) }
  }

  const handleRemove = async (linkId: string) => {
    if (!confirm(t('common.removeProject'))) return
    try {
      await apiClient.delete(`/api/v1/crm/contacts/${entity.id}/projects/${linkId}`)
      refresh()
    } catch (e: any) { alert(e.detail || e.message) }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h3>{t('pages.contacts.detail.projects')}</h3>
          <button onClick={async () => {
            try {
              const res = await apiClient.get<{ items: { id: string; name: string; amount: number | null }[] }>('/api/v1/crm/deals?limit=200')
              setDealOptions(res.items || [])
              setOpen(true)
            } catch (e: any) { alert(e.detail || e.message) }
          }} className="btn-ghost">{t('pages.contacts.detail.linkProject')}</button>
        </div>
        {projects.length === 0 ? (
          <div className="empty-state">{t('pages.contacts.detail.noProjects')}</div>
        ) : (
          <div className="flex-col">
            {projects.map(p => (
              <div key={p.id} className="list-row">
                <div className="list-main">
                  <div className="list-title">{p.project_name}</div>
                  <div className="list-sub">{p.stage_name || '—'}</div>
                </div>
                <div className="text-right flex items-center gap-3">
                  <div>
                    <div className="list-title">{p.project_amount ? formatAmount(p.project_amount) : '$0'}</div>
                    <div className="list-sub">{p.probability ?? 0}%</div>
                  </div>
                  <button onClick={() => handleRemove(p.id)} className="icon-btn text-notification" title={t('common.delete')}>
                    <SvcIcon name="trash-2" className="icon-16" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {open && (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.contacts.detail.modalLinkProject')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.contacts.detail.selectProject')}</label>
                <select value={selected} onChange={e => setSelected(e.target.value)} className="input-field">
                  <option value="">{t('pages.contacts.detail.chooseProject')}</option>
                  {dealOptions.map(d => (
                    <option key={d.id} value={d.id}>{d.name} {d.amount ? `($${d.amount})` : ''}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleLink} disabled={saving || !selected}
                className="btn-primary">{saving ? t('common.saving') : t('pages.contacts.detail.link')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

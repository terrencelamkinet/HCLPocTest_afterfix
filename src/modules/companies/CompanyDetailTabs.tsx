import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import AutofillButton from '../../components/ai/chat/core/AutofillButton'
import { sanitizeHtml } from '../../lib/sanitizeHtml'
import i18n from '../../i18n/config'
import type { EntityRecord, ModuleConfig } from '../module-types'

// ---------- Types ----------

interface Touchpoint {
  id: string; type: string; title: string; description: string | null
  contact_id?: string; company_id?: string; created_at: string
}
interface Note {
  id: string; title: string; content: string | null; pinned: boolean
  created_at: string; company_id?: string
  /** 由 note_links 關係帶出：呢篇筆記提及此 record（但未掛住） */
  mentioned?: boolean
}
interface ActivityItem {
  id: string; action: string; entity_type: string; entity_id: string; created_at: string
}
interface LinkRow { id: string; name: string; [k: string]: any }

// ---------- Helpers ----------

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

const typeEmoji: Record<string, string> = {
  call: '📞', email: '✉️', meeting: '🤝', namecard: '📇', default: '📌',
}

// ═══════════════════════════════════════════
//  Tabs
// ═══════════════════════════════════════════

/** Contacts tab — list all contacts belonging to this company */
export function ContactsTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [contacts, setContacts] = useState<LinkRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient.get<{ items: LinkRow[] }>(`/api/v1/crm/contacts?company_id=${company.id}&limit=500`)
      .then(r => setContacts(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [company.id])

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.contacts')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{t('pages.companies.detail.contacts')} ({contacts.length})</h3>
      </div>
      {contacts.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noContacts')}</div>
      ) : (
        <div className="flex-col">
          {contacts.map(c => (
            <Link key={c.id} to={`/contacts/${c.id}`} className="list-row hover:bg-slate-50 no-underline">
              <div className="list-avatar">{c.name?.charAt(0)?.toUpperCase() || '?'}</div>
              <div className="list-main">
                <div className="list-title">{c.name}</div>
                <div className="list-sub">{c.job_title || c.email || '—'}</div>
              </div>
              <SvcIcon name="chevron-right" className="w-4 h-4 text-slate-300" />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

/** Deals tab — list deals under this company */
export function DealsTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [deals, setDeals] = useState<LinkRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient.get<{ items: LinkRow[] }>(`/api/v1/crm/deals?company_id=${company.id}&limit=200`)
      .then(r => setDeals(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [company.id])

  const fmt = (n: number | null) => n ? `$${n.toLocaleString()}` : '$0'

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.deals')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{t('pages.companies.detail.deals')} ({deals.length})</h3>
      </div>
      {deals.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noDeals')}</div>
      ) : (
        <div className="flex-col">
          {deals.map(d => (
            <div key={d.id} className="list-row">
              <div className="list-main">
                <div className="list-title">{d.name}</div>
                <div className="list-sub">
                  <span className={`badge badge-p3`}>{i18n.t(`pages.deals.${d.status}`, { defaultValue: d.status })}</span>
                  {d.probability != null && <span className="ml-2">{d.probability}%</span>}
                </div>
              </div>
              <div className="text-right">
                <div className="list-title">{fmt(d.amount)}</div>
                <div className="list-sub">{d.currency || 'HKD'}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Projects tab — projects belonging to this company */
export function ProjectsTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [projects, setProjects] = useState<LinkRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient.get<{ items: LinkRow[] }>(`/api/v1/crm/projects?company_id=${company.id}&limit=200`)
      .then(r => setProjects(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [company.id])

  const fmt = (n: number | null) => n ? `$${n.toLocaleString()}` : '$0'

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.projects')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{t('pages.companies.detail.projects')} ({projects.length})</h3>
      </div>
      {projects.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noProjects')}</div>
      ) : (
        <div className="flex-col">
          {projects.map(p => (
            <Link key={p.id} to={`/projects/${p.id}`} className="list-row hover:bg-slate-50 no-underline">
              <div className="list-main">
                <div className="list-title">{p.name}</div>
                <div className="list-sub">
                  <span className={`badge badge-p3`}>{i18n.t(`pages.deals.${p.status}`, { defaultValue: p.status })}</span>
                  {p.priority && <span className="ml-2">· {p.priority}</span>}
                </div>
              </div>
              <div className="text-right">
                <div className="list-title">{fmt(p.budget_amount)}</div>
                <div className="list-sub">{p.deadline ? new Date(p.deadline).toLocaleDateString() : '—'}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

/** Products tab — products in use & proposed products */
export function ProductsTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [inUse, setInUse] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [products, setProducts] = useState<Record<string, string>>({})

  useEffect(() => {
    setLoading(true)
    Promise.all([
      apiClient.get<any[]>(`/api/v1/crm/companies/${company.id}/products-in-use`).catch(() => []),
      apiClient.get<any[]>('/api/v1/crm/products?limit=200').catch(() => ({ items: [] })),
    ]).then(([inUseRes, prodRes]) => {
      setInUse(inUseRes || [])
      const pmap: Record<string, string> = {}
      ;((prodRes as any).items || []).forEach((p: any) => { pmap[p.id] = p.name })
      setProducts(pmap)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [company.id])

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.productsInUse')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head"><h3>{t('pages.companies.detail.productsInUse')} ({inUse.length})</h3></div>
      {inUse.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noProducts')}</div>
      ) : (
        <div className="flex-col">
          {inUse.map((p: any, i: number) => (
            <div key={p.product_id || i} className="list-row">
              <div className="list-main">
                <div className="list-title">{products[p.product_id] || p.product_id.slice(0, 8)}</div>
                {p.since_date && <div className="list-sub">{t('pages.companies.detail.since')}{new Date(p.since_date).toLocaleDateString()}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Partners tab — distributor partners */
export function PartnersTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [partners, setPartners] = useState<any[]>([])
  const [companyNames, setCompanyNames] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      apiClient.get<any[]>(`/api/v1/crm/companies/${company.id}/partners`).catch(() => []),
      apiClient.get<{ items: LinkRow[] }>('/api/v1/crm/companies?limit=500').catch(() => ({ items: [] })),
    ]).then(([pRes, cRes]) => {
      setPartners(pRes || [])
      const nmap: Record<string, string> = {}
      ;(cRes.items || []).forEach((c: any) => { nmap[c.id] = c.name })
      setCompanyNames(nmap)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [company.id])

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.partners')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head"><h3>{t('pages.companies.detail.partners')} ({partners.length})</h3></div>
      {partners.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noPartners')}</div>
      ) : (
        <div className="flex-col">
          {partners.map((p: any, i: number) => (
            <div key={`${p.partner_company_id}-${i}`} className="list-row">
              <div className="list-main">
                <div className="list-title">{companyNames[p.partner_company_id] || p.partner_company_id.slice(0, 8)}</div>
                <div className="list-sub">{t('pages.companies.detail.relationPartner')}{p.relation_type && p.relation_type !== 'Partner' ? p.relation_type : ''}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Touchpoints tab */
export function TouchpointsTab({ entity: company, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', type: 'meeting', description: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient.get<{ items: Touchpoint[] }>(`/api/v1/crm/touchpoints?company_id=${company.id}&limit=200`)
      .then(r => setTouchpoints(r.items || []))
      .catch(() => {})
  }, [company.id])

  const handleAdd = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await apiClient.post('/api/v1/crm/touchpoints', {
        title: form.title, type: form.type, description: form.description || null,
        company_id: company.id,
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
          <h3>{t('pages.companies.detail.touchpoints')} ({touchpoints.length})</h3>
          <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.companies.detail.addTouchpoint')}</button>
        </div>
        {touchpoints.length === 0 ? (
          <div className="empty-state">{t('pages.companies.detail.noTouchpoints')}</div>
        ) : (
          <div className="flex-col">
            {touchpoints.map(tp => (
              <div key={tp.id} className="list-row">
                <div className="list-icon"><SvcIcon name="activity" /></div>
                <div className="list-main">
                  <div className="list-title">{tp.title}</div>
                  <div className="list-sub">{tp.description || '—'}</div>
                  <div className="list-sub mt-1 flex items-center gap-2">
                    <span className="badge badge-p3">{i18n.t(`pages.contacts.detail.touchpointTypes.${tp.type}`, { defaultValue: tp.type })}</span>
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
              <h2>{t('pages.companies.detail.modalAddTouchpoint')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.titleRequired')}</label>
                <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder={t('pages.companies.detail.titlePlaceholder')} className="input-field" />
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.type')}</label>
                <select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))} className="input-field">
                  <option value="meeting">{i18n.t('pages.contacts.detail.touchpointTypes.meeting')}</option>
                  <option value="call">{i18n.t('pages.contacts.detail.touchpointTypes.call')}</option>
                  <option value="email">{i18n.t('pages.contacts.detail.touchpointTypes.email')}</option>
                  <option value="namecard">{i18n.t('pages.contacts.detail.touchpointTypes.namecard')}</option>
                </select>
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.description')}</label>
                <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={2} placeholder={t('pages.companies.detail.descriptionPlaceholder')} className="input-field" />
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleAdd} disabled={saving || !form.title.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.companies.detail.add')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/** Notes tab */
export function NotesTab({ entity: company, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [notes, setNotes] = useState<Note[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ title: '', content: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    /* spec §8.3：除咗 FK 掛住嘅，仲要列出 note_links 提及呢間公司嘅（合併去重）。 */
    Promise.all([
      apiClient.get<{ items: Note[] }>(`/api/v1/crm/notes?company_id=${company.id}&limit=200`),
      apiClient
        .get<{ items: Note[] }>(
          `/api/v1/crm/notes?limit=100&mention_of_type=company&mention_of_id=${company.id}`
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
  }, [company.id])

  const handleAdd = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await apiClient.post('/api/v1/crm/notes', {
        title: form.title, content: form.content || null, company_id: company.id,
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
          <h3>{t('pages.companies.detail.notes')} ({notes.length})</h3>
          <div className="flex items-center gap-2">
            <AutofillButton mode="summary" onRun={async () => {
              try {
                const res = await apiClient.post<{ value: string }>('/api/v1/crm/ai/autofill', {
                  record_type: 'company', record_id: company.id, field: 'summary', mode: 'summary',
                })
                setForm({ title: 'AI 摘要', content: res.value || '' })
                setOpen(true)
              } catch (e: any) { alert(e.detail || e.message) }
            }} />
            <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.companies.detail.addNote')}</button>
          </div>
        </div>
        {notes.length === 0 ? (
          <div className="empty-state">{t('pages.companies.detail.noNotes')}</div>
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
                  {n.pinned && <span className="badge badge-p1">{t('pages.companies.detail.pinned')}</span>}
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
              <h2>{t('pages.companies.detail.modalAddNote')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.titleRequired')}</label>
                <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  placeholder={t('pages.companies.detail.noteTitlePlaceholder')} className="input-field" />
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.description')}</label>
                <textarea value={form.content} onChange={e => setForm(f => ({ ...f, content: e.target.value }))}
                  rows={4} placeholder={t('pages.companies.detail.noteContentPlaceholder')} className="input-field" />
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleAdd} disabled={saving || !form.title.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.companies.detail.add')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/** Timeline tab — activity + touchpoints for this company */
export function TimelineTab({ entity: company, refresh }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ action: '', description: '' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([
      apiClient.get<{ items: ActivityItem[] }>('/api/v1/crm/activities?page_size=100').catch(() => ({ items: [] })),
      apiClient.get<{ items: Touchpoint[] }>('/api/v1/crm/touchpoints?limit=100').catch(() => ({ items: [] })),
    ]).then(([aRes, tpRes]) => {
      setActivities((aRes.items || []).filter(a => a.entity_id === company.id))
      setTouchpoints((tpRes.items || []).filter(tp => tp.company_id === company.id))
    })
  }, [company.id])

  const timelineItems = [
    ...activities.map(a => ({ id: a.id, emoji: '📝', title: a.action, date: timeAgo(a.created_at), meta: i18n.t(`pages.contacts.detail.entityTypes.${a.entity_type}`, { defaultValue: a.entity_type?.replace(/_/g, ' ') }), sortKey: a.created_at })),
    ...touchpoints.map(tp => ({ id: tp.id, emoji: typeEmoji[tp.type] || typeEmoji.default, title: tp.title, date: timeAgo(tp.created_at), meta: tp.description || i18n.t(`pages.contacts.detail.touchpointTypes.${tp.type}`, { defaultValue: tp.type }), sortKey: tp.created_at })),
  ].sort((a, b) => new Date(b.sortKey).getTime() - new Date(a.sortKey).getTime())

  const handleLog = async () => {
    if (!form.action.trim()) return
    setSaving(true)
    try {
      await apiClient.post('/api/v1/crm/activities', {
        action: form.action, description: form.description,
        entity_type: 'company', entity_id: company.id,
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
          <h3>{t('pages.companies.detail.activity')}</h3>
          <button onClick={() => setOpen(true)} className="btn-ghost">{t('pages.companies.detail.logActivity')}</button>
        </div>
        {timelineItems.length === 0 ? (
          <div className="empty-state">{t('pages.companies.detail.noActivity')}</div>
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
              <h2>{t('pages.companies.detail.modalLogActivity')}</h2>
              <button onClick={() => setOpen(false)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body">
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.actionRequired')}</label>
                <input type="text" value={form.action} onChange={e => setForm(f => ({ ...f, action: e.target.value }))}
                  placeholder={t('pages.companies.detail.actionPlaceholder')} className="input-field" />
              </div>
              <div className="form-row-1">
                <label className="field-label">{t('pages.companies.detail.description')}</label>
                <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={3} placeholder={t('pages.companies.detail.activityDescriptionPlaceholder')} className="input-field" />
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={() => setOpen(false)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleLog} disabled={saving || !form.action.trim()}
                className="btn-primary">{saving ? t('common.saving') : t('pages.companies.detail.log')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Tasks tab ──────────────────────────────────────────

interface TaskItem {
  id: string; title: string; status: string; priority: string; due_date: string | null
}

export function TasksTab({ entity: company }: { entity: EntityRecord; moduleConfig: ModuleConfig; refresh: () => void }) {
  const { t } = useTranslation()
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiClient.get<{ items: TaskItem[] }>(`/api/v1/crm/tasks?company_id=${company.id}&limit=100`)
      .then(r => setTasks(r.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [company.id])

  if (loading) return <div className="panel"><div className="panel-head"><h3>{t('pages.companies.detail.tasks')}</h3></div><div className="empty-state">{t('common.loading')}</div></div>

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>{t('pages.companies.detail.tasks')} ({tasks.length})</h3>
      </div>
      {tasks.length === 0 ? (
        <div className="empty-state">{t('pages.companies.detail.noTasks')}</div>
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

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { apiClient } from '../lib/api';
import { DollarSign, Layout } from 'lucide-react'
import SvcIcon from '../components/SvcIcon'
import SlideDrawer from '../components/SlideDrawer'

interface Task { id: string; title: string; priority: string; status: string; due_date: string | null }
interface Touchpoint { id: string; type: string; title: string; description: string | null; company?: { name: string } | null; contact?: { name: string } | null; created_at: string }
interface Deal { id: string; name: string; amount: number | null; stage_id: string; probability: number; company?: { name: string } | null }
interface Contact { id: string; name: string; email: string | null; phone: string | null; position: string | null; company?: { name: string } | null }

const stages: Record<string, { label: string; color: string }> = {
  qualification: { label: 'Qualification', color: 'var(--color-blue)' },
  proposal: { label: 'Proposal', color: 'var(--color-warning)' },
  negotiation: { label: 'Negotiation', color: 'var(--color-purple)' },
  closed_won: { label: 'Closed Won', color: 'var(--color-success)' },
  closed_lost: { label: 'Closed Lost', color: 'var(--color-text-faint)' },
}
const stageKeys = ['qualification', 'proposal', 'negotiation', 'closed_won']

const todayStr = () => {
  const d = new Date()
  const days = ['日', '一', '二', '三', '四', '五', '六']
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 · 星期${days[d.getDay()]}`
}

// Widget definitions — span-based CSS grid (design01)
type WidgetKey = string
interface WidgetDef { label: string; span: number }
const allWidgets: Record<string, WidgetDef> = {
  kpi_contacts: { label: 'Contacts', span: 6 },
  kpi_companies: { label: 'Companies', span: 6 },
  kpi_deals: { label: 'Deal Count', span: 6 },
  kpi_tasks: { label: 'Tasks', span: 6 },
  pipeline: { label: 'Deal Pipeline', span: 8 },
  tasks: { label: "Today's Tasks", span: 4 },
  touchpoints: { label: 'Recent Touchpoints', span: 4 },
  dealvalue: { label: 'Total Deal Value', span: 4 },
  aiinsight: { label: 'AI Insight', span: 4 },
  activity_feed: { label: 'Activity Feed', span: 12 },
}
const defaultOrder: WidgetKey[] = [
  'kpi_contacts', 'kpi_companies', 'kpi_deals', 'kpi_tasks',
  'pipeline', 'tasks',
  'touchpoints', 'dealvalue', 'aiinsight',
  'activity_feed',
]
const ORDER_KEY = 'dash-preview-order'

// ── Demo data fallbacks ──
const demoContacts: Contact[] = [
  { id: 'demo-cont-1', name: 'David Chen', email: 'david@example.com', phone: '+852 9876 5432', position: 'CEO', company: { name: 'TechCorp' } },
  { id: 'demo-cont-2', name: 'Sarah Wong', email: 'sarah@example.com', phone: '+852 9123 4567', position: 'CTO', company: { name: 'Innovate Ltd' } },
  { id: 'demo-cont-3', name: 'Michael Lau', email: 'michael@example.com', phone: '+852 9000 1111', position: 'VP Sales', company: { name: 'Growth Inc' } },
]
const demoTasks: Task[] = [
  { id: 'demo-t-1', title: 'Follow up with TechCorp proposal', priority: 'P0', status: 'pending', due_date: new Date().toISOString() },
  { id: 'demo-t-2', title: 'Review Q3 pipeline report', priority: 'P1', status: 'in_progress', due_date: new Date().toISOString() },
  { id: 'demo-t-3', title: 'Prepare client presentation', priority: 'P1', status: 'pending', due_date: new Date(Date.now() + 86400000).toISOString() },
  { id: 'demo-t-4', title: 'Update CRM contact records', priority: 'P2', status: 'pending', due_date: null },
  { id: 'demo-t-5', title: 'Schedule team sync meeting', priority: 'P2', status: 'done', due_date: new Date().toISOString() },
]
const demoDeals: Deal[] = [
  { id: 'demo-d-1', name: 'TechCorp Enterprise Plan', amount: 120000, stage_id: 'negotiation', probability: 70, company: { name: 'TechCorp' } },
  { id: 'demo-d-2', name: 'Innovate Ltd Platform', amount: 85000, stage_id: 'proposal', probability: 50, company: { name: 'Innovate Ltd' } },
  { id: 'demo-d-3', name: 'Growth Inc SaaS', amount: 45000, stage_id: 'qualification', probability: 30, company: { name: 'Growth Inc' } },
  { id: 'demo-d-4', name: 'DataSync Solutions', amount: 200000, stage_id: 'negotiation', probability: 60, company: { name: 'DataSync' } },
  { id: 'demo-d-5', name: 'CloudBase Migration', amount: 95000, stage_id: 'closed_won', probability: 100, company: { name: 'CloudBase' } },
]
const demonTouchpoints: Touchpoint[] = [
  { id: 'demo-tp-1', type: 'meeting', title: 'Q3 Review with TechCorp', description: 'Discussed quarterly performance', company: { name: 'TechCorp' }, contact: { name: 'David Chen' }, created_at: new Date().toISOString() },
  { id: 'demo-tp-2', type: 'call', title: 'Discovery Call - Innovate Ltd', description: 'Initial product demo', company: { name: 'Innovate Ltd' }, contact: { name: 'Sarah Wong' }, created_at: new Date(Date.now() - 86400000).toISOString() },
  { id: 'demo-tp-3', type: 'email', title: 'Proposal sent to Growth Inc', description: 'Sent enterprise proposal', company: { name: 'Growth Inc' }, contact: { name: 'Michael Lau' }, created_at: new Date(Date.now() - 172800000).toISOString() },
]

export default function DashboardPreview() {
  const { t } = useTranslation()
  const [stats, setStats] = useState({ contacts: 0, deals: 0, dealValue: '', tasks: 0, companies: 0 })
  const [tasks, setTasks] = useState<Task[]>([])
  const [touchpoints, setTouchpoints] = useState<Touchpoint[]>([])
  const [deals, setDeals] = useState<Deal[]>([])
  const [contacts, setContacts] = useState<Contact[]>([])
  const [editing, setEditing] = useState(false)
  const [aiOn, setAiOn] = useState(false)
  const [showPicker, setShowPicker] = useState(false)

  // ── Drawer state ──
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerTitle, setDrawerTitle] = useState('')
  const [drawerContent, setDrawerContent] = useState<React.ReactNode>(null)

  const openDrawer = (title: string, content: React.ReactNode) => {
    setDrawerTitle(title)
    setDrawerContent(content)
    setDrawerOpen(true)
  }

  // Widget order with span — persists to localStorage
  type WidgetItem = { key: string; span: number }
  const [widgetItems, setWidgetItems] = useState<WidgetItem[]>(() => {
    try { return JSON.parse(localStorage.getItem(ORDER_KEY) || 'null') || defaultOrder.map(k => ({key: k, span: allWidgets[k].span})) }
    catch { return defaultOrder.map(k => ({key: k, span: allWidgets[k].span})) }
  })
  const saveItems = (items: WidgetItem[]) => {
    setWidgetItems(items)
    try { localStorage.setItem(ORDER_KEY, JSON.stringify(items)) } catch {}
  }

  // Drag state — dragKey used in handleDragStart/Over/End
  
  // Data fetching
  const fetchData = useCallback(async () => {
    try {
      const [cRes, coRes, dRes, tRes, tpRes, contRes] = await Promise.all([
        apiClient.get<{ total: number }>('/api/v1/crm/contacts?limit=1'),
        apiClient.get<{ total: number }>('/api/v1/crm/companies?limit=1'),
        apiClient.get<{ items: Deal[]; total: number }>('/api/v1/crm/deals?limit=100'),
        apiClient.get<{ items: Task[]; total: number }>('/api/v1/crm/tasks?limit=10'),
        apiClient.get<{ items: Touchpoint[]; total: number }>('/api/v1/crm/touchpoints?limit=10'),
        apiClient.get<{ items: Contact[]; total: number }>('/api/v1/crm/contacts?limit=10'),
      ])
      const dealsList = dRes.items || demoDeals
      const totalVal = dealsList.reduce((s: number, d: Deal) => s + (d.amount || 0), 0)
      const fmt = (n: number) => n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${(n / 1e3).toFixed(0)}K` : `$${n}`
      setStats({
        contacts: cRes.total || 10, deals: dealsList.length,
        dealValue: totalVal ? fmt(totalVal) : '$545K', tasks: tRes.total || 8, companies: coRes.total || 6,
      })
      setTasks(tRes.items?.length ? tRes.items : demoTasks)
      setTouchpoints((tpRes.items?.length ? tpRes.items : demonTouchpoints).slice(0, 5))
      setDeals(dealsList)
      setContacts(contRes.items?.length ? contRes.items : demoContacts)
    } catch {
      // Fallback to demo data
      setStats({ contacts: 10, deals: 5, dealValue: '$545K', tasks: 8, companies: 6 })
      setTasks(demoTasks)
      setTouchpoints(demonTouchpoints.slice(0, 5))
      setDeals(demoDeals)
      setContacts(demoContacts)
    }
  }, [])
  useEffect(() => { fetchData() }, [fetchData])

  const pipeline = stageKeys.map(k => {
    const items = deals.filter(d => d.stage_id === k)
    return {
      key: k, label: stages[k]?.label || k, count: items.length,
      total: items.reduce((s, d) => s + (d.amount || 0), 0),
      color: stages[k]?.color || 'var(--color-primary)',
    }
  })
  const maxPipelineTotal = Math.max(1, ...pipeline.map(p => p.total))

  // Ref for the grid container (DOM manipulation during drag, like design01)
  const gridRef = useRef<HTMLDivElement>(null)

  // Widget actions
  const addWidget = (k: string) => {
    if (widgetItems.some(w => w.key === k)) return
    saveItems([...widgetItems, {key: k, span: allWidgets[k].span}])
    setShowPicker(false)
  }
  const removeW = (k: string) => saveItems(widgetItems.filter(w => w.key !== k))
  // Resize widget
  const resizeW = (k: string, newSpan: number) => {
    const clamped = Math.max(1, Math.min(12, newSpan))
    saveItems(widgetItems.map(w => w.key === k ? {...w, span: clamped} : w))
  }

  // ── Drag: match design01 — DOM manipulation during drag, state sync only on dragEnd ──
  const dragKey = useRef<string | null>(null)
  const dragPending = useRef(false)
  const handleDragStart = (k: string) => {
    dragKey.current = k
    dragPending.current = false
  }
  const handleDragOver = (e: React.DragEvent, k: string) => {
    if (!editing || !dragKey.current || dragKey.current === k) return
    e.preventDefault()
    if (dragPending.current) return
    dragPending.current = true
    requestAnimationFrame(() => {
      dragPending.current = false
      const grid = gridRef.current
      if (!grid) return
      const dragged = grid.querySelector(`[data-key="${dragKey.current}"]`) as HTMLElement
      const target = e.currentTarget as HTMLElement
      if (!dragged || dragged === target) return
      const rect = target.getBoundingClientRect()
      const before = (e.clientX - rect.left) < rect.width / 2
      grid.insertBefore(dragged, before ? target : target.nextSibling)
    })
  }
  const handleDragEnd = () => {
    dragKey.current = null
    // Sync order from DOM once (like design01's syncLayoutFromDOM)
    const grid = gridRef.current
    if (!grid) return
    const domKeys: string[] = []
    grid.querySelectorAll('[data-key]').forEach(el => {
      const key = el.getAttribute('data-key')
      if (key) domKeys.push(key)
    })
    if (domKeys.length > 0) {
      // Preserve existing spans, just reorder
      const spanMap = new Map(widgetItems.map(w => [w.key, w.span]))
      const newItems: WidgetItem[] = domKeys.map(k => ({key: k, span: spanMap.get(k) ?? allWidgets[k]?.span ?? 4}))
      saveItems(newItems)
    }
  }

  // ── Drawer detail content builders ──
  const buildTaskDetail = (task: Task) => (
    <div style={{display:'flex',flexDirection:'column',gap:14,padding:'12px 0'}}>
      <div className="flex-col">
        <div className="list-row">
          <div className="list-main">
            <div className="list-title">{task.title}</div>
            <div className="list-sub">ID: {task.id}</div>
          </div>
          <span className="dash-badge" style={{
            background: task.priority==='P0'?'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))':task.priority==='P1'?'color-mix(in oklch,var(--color-warning)18%,var(--color-surface))':'color-mix(in oklch,var(--color-success)18%,var(--color-surface))',
            color: task.priority==='P0'?'var(--color-notification)':task.priority==='P1'?'var(--color-warning)':'var(--color-success)'
          }}>{task.priority||'P3'}</span>
        </div>
        <div className="list-row">
          <div className="list-main">
            <div className="list-title"><SvcIcon name="file-text" size={14} /> {t('tasks.status')}</div>
            <div className="list-sub">{task.status || 'pending'}</div>
          </div>
        </div>
        {task.due_date && (
          <div className="list-row">
            <SvcIcon name="calendar" size={14} />
            <div className="list-main">
              <div className="list-title">{t('tasks.dueDate')}</div>
              <div className="list-sub">{new Date(task.due_date).toLocaleDateString()}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )

  const buildDealDetail = (deal: Deal) => (
    <div style={{display:'flex',flexDirection:'column',gap:14,padding:'12px 0'}}>
      <div className="flex-col">
        <div className="list-row">
          <SvcIcon name="trending-up" size={16} style={{color:'var(--color-primary)'}} />
          <div className="list-main">
            <div className="list-title">{deal.name}</div>
            <div className="list-sub">{deal.company?.name || '—'}</div>
          </div>
          <span className="dash-badge" style={{
            background: 'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',
            color: 'var(--color-primary)'
          }}>${deal.amount?.toLocaleString() || '—'}</span>
        </div>
        <div className="list-row">
          <SvcIcon name="tags" size={14} />
          <div className="list-main">
            <div className="list-title">{t('deals.stage')}</div>
            <div className="list-sub">{stages[deal.stage_id]?.label || deal.stage_id}</div>
          </div>
        </div>
        <div className="list-row">
          <div className="list-main">
            <div className="list-title">{t('pages.deals.probability')}</div>
            <div className="list-sub">{deal.probability}%</div>
          </div>
        </div>
      </div>
    </div>
  )

  const buildContactDetail = (contact: Contact) => (
    <div style={{display:'flex',flexDirection:'column',gap:14,padding:'12px 0'}}>
      <div className="flex-col">
        <div className="list-row">
          <div className="avatar" style={{width:40,height:40,borderRadius:'50%',background:'var(--color-primary)',display:'flex',alignItems:'center',justifyContent:'center',color:'#fff',fontWeight:700,fontSize:16}}>
            {contact.name.split(' ').map(s=>s[0]).join('').toUpperCase().slice(0,2)}
          </div>
          <div className="list-main">
            <div className="list-title">{contact.name}</div>
            <div className="list-sub">{contact.position || '—'} {contact.company?.name ? `at ${contact.company.name}` : ''}</div>
          </div>
        </div>
        {contact.email && (
          <div className="list-row">
            <SvcIcon name="mail" size={14} />
            <div className="list-main">
              <div className="list-title">{t('contacts.email')}</div>
              <div className="list-sub">{contact.email}</div>
            </div>
          </div>
        )}
        {contact.phone && (
          <div className="list-row">
            <SvcIcon name="phone" size={14} />
            <div className="list-main">
              <div className="list-title">{t('contacts.phone')}</div>
              <div className="list-sub">{contact.phone}</div>
            </div>
          </div>
        )}
        {contact.company?.name && (
          <div className="list-row">
            <SvcIcon name="building-2" size={14} />
            <div className="list-main">
              <div className="list-title">{t('contacts.company')}</div>
              <div className="list-sub">{contact.company.name}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )

  const buildTouchpointDetail = (tp: Touchpoint) => (
    <div style={{display:'flex',flexDirection:'column',gap:14,padding:'12px 0'}}>
      <div className="flex-col">
        <div className="list-row">
          <SvcIcon name="activity" size={16} style={{color:'var(--color-primary)'}} />
          <div className="list-main">
            <div className="list-title">{tp.title}</div>
            <div className="list-sub">{tp.contact?.name || ''} {tp.company?.name ? `· ${tp.company.name}` : ''}</div>
          </div>
          <span className="dash-badge" style={{
            background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',
            color:'var(--color-primary)'
          }}>{tp.type}</span>
        </div>
        {tp.description && (
          <div className="list-row">
            <SvcIcon name="file-text" size={14} />
            <div className="list-main">
              <div className="list-title">{t('touchpoint.notes')}</div>
              <div className="list-sub">{tp.description}</div>
            </div>
          </div>
        )}
        <div className="list-row">
          <SvcIcon name="clock" size={14} />
          <div className="list-main">
            <div className="list-title">{t('touchpoint.type')}</div>
            <div className="list-sub">{new Date(tp.created_at).toLocaleString()}</div>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className="dash-content">
      {/* Toolbar — design01 .dash-toolbar pattern */}
      <div className="dash-toolbar">
        <div>
          <h1>{t('greeting.morning', { name: 'Terrence' })}</h1>
          <p>{todayStr()}</p>
        </div>
        <div style={{display:'flex', gap:10, alignItems:'center'}}>
          {/* AI toggle inline */}
          <div className="ai-toggle-inline">
            <SvcIcon name="sparkles" size={15} />
            <span>AI</span>
            <button className={`switcher${aiOn ? ' on' : ''}`} onClick={() => setAiOn(!aiOn)} />
          </div>
          <button className={`dash-btn${editing ? ' primary' : ''}`} onClick={() => setEditing(!editing)}>
            <Layout size={15} />
            {editing ? t('common.done') : t('dashboard.editMode')}
          </button>
        </div>
      </div>

      {/* AI Brief */}
      {aiOn && (
        <section className="ai-brief-card">
          <div className="brief-head">
            <SvcIcon name="sparkles" size={20} />
            <h2>{t('greeting.aiBriefing')}</h2>
            <span>{t('pages.briefing.title')}</span>
          </div>
          <div className="brief-grid">
            <div>
              <h4>{t('greeting.todayHighlights')}</h4>
              <ul>
                <li>{stats.deals} {t('pages.tasks.inProgress')} {t('deals.title').toLowerCase()}, {t('deals.amount').toLowerCase()} {stats.dealValue}</li>
                <li>{t('dashboard.widgets.tasksDue')}: {stats.tasks}</li>
              </ul>
            </div>
            <div>
              <h4>{t('greeting.meetingPrep')}</h4>
              <ul>
                {touchpoints.slice(0,2).map(tp => <li key={tp.id}>{tp.title}</li>)}
                {touchpoints.length === 0 && <li className="muted">{t('calendar.noEvents')}</li>}
              </ul>
            </div>
            <div>
              <h4>{t('greeting.riskAlerts')}</h4>
              <ul>
                <li>{tasks.filter(t=>t.priority==='P0').length} {t('priority.urgent')} {t('pages.tasks.taskTitle').toLowerCase()}</li>
                <li>{stats.companies} {t('companies.title').toLowerCase()} {t('status.active')}</li>
              </ul>
            </div>
          </div>
        </section>
      )}

      {/* Widget Grid — 12-column CSS grid */}
      <div className="dash-grid" ref={gridRef}>
        {widgetItems.map(item => {
          const k = item.key
          const def = allWidgets[k]
          if (!def) return null
          return (
            <div key={k} className={`dash-widget span-${item.span}${editing && dragKey.current === k ? ' dragging' : ''}`}
              data-key={k}
              draggable={editing}
              onDragStart={() => handleDragStart(k)}
              onDragOver={e => handleDragOver(e, k)}
              onDragEnd={handleDragEnd}>
              <div className="w-head">
                <h3>
                  {k.startsWith('kpi_') ? def.label :
                   k === 'tasks' ? <><SvcIcon name="check-square" size={14} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.tasksDue')} <span className="dash-badge" style={{background:'color-mix(in oklch,var(--color-primary)18%,var(--color-surface))',color:'var(--color-primary)'}}>{stats.tasks}</span></> :
                   k === 'touchpoints' ? <><SvcIcon name="activity" size={14} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.recentActivity')}</> :
                   k === 'pipeline' ? <><SvcIcon name="trending-up" size={14} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.pipeline')}</> :
                   k === 'dealvalue' ? <><DollarSign size={15} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.dealTotal')}</> :
                   k === 'aiinsight' ? <><SvcIcon name="sparkles" size={15} style={{color:'var(--color-purple)'}} /> AI Insight</> :
                   k === 'activity_feed' ? <><SvcIcon name="activity" size={15} style={{color:'var(--color-text-muted)'}} /> {t('dashboard.widgets.recentActivity')}</> :
                   def.label}
                </h3>
                {editing && (
                  <div className="w-actions">
                    <button className="w-action" title={t('greeting.drag')}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="9" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="18" r="1"/></svg></button>
                    <button className="w-action" title={t('greeting.remove')} onClick={e => { e.stopPropagation(); removeW(k) }}><SvcIcon name="x" size={14} /></button>
                  </div>
                )}
              </div>
              <div className="w-body">
                {k.startsWith('kpi_') && (
                  <div className="kpi-center">
                    <span className="kpi-val" style={{cursor:'pointer',color:k==='kpi_contacts'?'var(--color-blue)':k==='kpi_companies'?'var(--color-purple)':k==='kpi_deals'?'var(--color-primary)':'var(--color-warning)'}}
                      onClick={() => {
                        if (k === 'kpi_contacts' && contacts.length > 0) openDrawer(t('contacts.title'),
                          <div style={{display:'flex',flexDirection:'column',gap:8,padding:'8px 0'}}>
                            {contacts.slice(0,10).map(c => (
                              <div key={c.id} className="dash-row" onClick={() => openDrawer(c.name, buildContactDetail(c))}>
                                <div className="avatar-xs">{c.name.split(' ').map(s=>s[0]).join('').toUpperCase().slice(0,2)}</div>
                                <span className="row-name">{c.name}</span>
                                <span className="row-meta">{c.company?.name||''}</span>
                              </div>
                            ))}
                          </div>
                        )
                        if (k === 'kpi_deals' && deals.length > 0) openDrawer(t('deals.title'),
                          <div style={{display:'flex',flexDirection:'column',gap:8,padding:'8px 0'}}>
                            {deals.slice(0,10).map(d => (
                              <div key={d.id} className="dash-row" onClick={() => openDrawer(d.name, buildDealDetail(d))}>
                                <SvcIcon name="trending-up" size={14} className="row-icon" />
                                <span className="row-name">{d.name}</span>
                                <span className="dash-badge" style={{background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',color:'var(--color-primary)'}}>${d.amount?.toLocaleString()||'—'}</span>
                              </div>
                            ))}
                          </div>
                        )
                        if (k === 'kpi_tasks' && tasks.length > 0) openDrawer(t('tasks.title'),
                          <div style={{display:'flex',flexDirection:'column',gap:8,padding:'8px 0'}}>
                            {tasks.slice(0,10).map(t => (
                              <div key={t.id} className="dash-row" onClick={() => openDrawer(t.title, buildTaskDetail(t))}>
                                <SvcIcon name="check-square" size={14} className="row-icon" />
                                <span className="row-name">{t.title}</span>
                                <span className="dash-badge" style={{background:t.priority==='P0'?'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))':'color-mix(in oklch,var(--color-warning)18%,var(--color-surface))',color:t.priority==='P0'?'var(--color-notification)':'var(--color-warning)'}}>{t.priority||'P3'}</span>
                              </div>
                            ))}
                          </div>
                        )
                      }}>
                      {k==='kpi_contacts'?stats.contacts:k==='kpi_companies'?stats.companies:k==='kpi_deals'?stats.deals:stats.tasks}
                    </span>
                    <span className="kpi-lbl">{t('dashboard.widgets.' + ({
                      kpi_contacts: 'totalCustomers',
                      kpi_companies: 'totalCustomers',
                      kpi_deals: 'activeDeals',
                      kpi_tasks: 'tasksDue',
                    })[k])}</span>
                  </div>
                )}
                {k === 'tasks' && (tasks.length === 0
                  ? <div className="empty">{t('pages.tasks.empty')}</div>
                  : tasks.slice(0,5).map(t => (
                    <div key={t.id} className="dash-row" onClick={() => openDrawer(t.title, buildTaskDetail(t))}>
                      <SvcIcon name="check-square" size={14} className="row-icon" />
                      <span className="row-name">{t.title}</span>
                      <span className="dash-badge" style={{
                        background: t.priority==='P0'?'color-mix(in oklch,var(--color-notification)18%,var(--color-surface))':t.priority==='P1'?'color-mix(in oklch,var(--color-warning)18%,var(--color-surface))':'color-mix(in oklch,var(--color-success)18%,var(--color-surface))',
                        color: t.priority==='P0'?'var(--color-notification)':t.priority==='P1'?'var(--color-warning)':'var(--color-success)'
                      }}>{t.priority||'P3'}</span>
                    </div>
                  ))
                )}
                {k === 'touchpoints' && (touchpoints.length === 0
                  ? <div className="empty">{t('common.noResults')}</div>
                  : touchpoints.map(tp => (
                    <div key={tp.id} className="dash-row" onClick={() => openDrawer(tp.title, buildTouchpointDetail(tp))}>
                      <SvcIcon name="activity" size={14} className="row-icon" />
                      <span className="row-name">{tp.title}</span>
                      <span className="row-meta">{tp.company?.name||''}</span>
                    </div>
                  ))
                )}
                {k === 'pipeline' && pipeline.map(p => (
                  <div key={p.key} className="stage-row" style={{cursor:'pointer'}} onClick={() => {
                    const stageDeals = deals.filter(d => d.stage_id === p.key)
                    if (stageDeals.length > 0) openDrawer(`${p.label} ${t('deals.title')} (${stageDeals.length})`, 
                      <div style={{display:'flex',flexDirection:'column',gap:8,padding:'8px 0'}}>
                        {stageDeals.map(d => (
                          <div key={d.id} className="list-row" onClick={() => openDrawer(d.name, buildDealDetail(d))}>
                            <SvcIcon name="trending-up" size={14} style={{color:'var(--color-primary)'}} />
                            <div className="list-main">
                              <div className="list-title">{d.name}</div>
                              <div className="list-sub">{d.company?.name||''}</div>
                            </div>
                            <span className="dash-badge" style={{background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',color:'var(--color-primary)'}}>${d.amount?.toLocaleString()||'—'}</span>
                          </div>
                        ))}
                      </div>
                    )
                  }}>
                    <div className="stage-labels">
                      <span>{p.label}</span>
                      <span>{p.count} {t('deals.title').toLowerCase()} · ${p.total.toLocaleString()}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{width:`${(p.total/maxPipelineTotal)*100}%`,background:p.color}} />
                    </div>
                  </div>
                ))}
                {k === 'dealvalue' && (
                  <><div className="kpi-val" style={{color:'var(--color-primary)',cursor:'pointer'}} onClick={() => {
                    const won = deals.filter(d => d.stage_id === 'closed_won')
                    if (won.length > 0) openDrawer(t('pages.deals.won') + ' ' + t('deals.title'),
                      <div style={{display:'flex',flexDirection:'column',gap:8,padding:'8px 0'}}>
                        {won.map(d => (
                          <div key={d.id} className="list-row" onClick={() => openDrawer(d.name, buildDealDetail(d))}>
                            <DollarSign size={14} style={{color:'var(--color-success)'}} />
                            <div className="list-main"><div className="list-title">{d.name}</div><div className="list-sub">{d.company?.name||''}</div></div>
                            <span className="dash-badge" style={{background:'color-mix(in oklch,var(--color-success)18%,var(--color-surface))',color:'var(--color-success)'}}>${d.amount?.toLocaleString()||'—'}</span>
                          </div>
                        ))}
                      </div>
                    )
                  }}>{stats.dealValue||'—'}</div>
                  <div className="kpi-delta up">↑ {deals.filter(d=>d.stage_id==='closed_won').length} {t('status.won')}</div></>
                )}
                {k === 'aiinsight' && (
                  <div style={{fontSize:13,lineHeight:1.5,color:'var(--color-text-muted)'}}>
                    <p>• {stats.contacts} {t('contacts.title').toLowerCase()} {t('status.active')}</p>
                    <p>• {stats.tasks} {t('tasks.title').toLowerCase()} {t('status.pending')}</p>
                    <p>• {t('dashboard.widgets.pipeline')} velocity: {deals.length>0?Math.round(deals.filter(d=>d.stage_id==='closed_won').length/Math.max(1,deals.length)*100):0}%</p>
                  </div>
                )}
                {k === 'activity_feed' && (
                  <div style={{fontSize:13}}>
                    {touchpoints.length === 0
                      ? <div className="empty">{t('common.noResults')}</div>
                      : <table className="feed-table">
                          <thead>
                            <tr><th>{t('touchpoint.type')}</th><th>{t('touchpoint.title')}</th><th>{t('contacts.company')}</th><th>{t('touchpoint.type')}</th></tr>
                          </thead>
                          <tbody>
                            {touchpoints.map(tp => (
                              <tr key={tp.id} onClick={() => openDrawer(tp.title, buildTouchpointDetail(tp))}>
                                <td><span className="dash-badge" style={{background:'color-mix(in oklch,var(--color-primary)14%,var(--color-surface))',color:'var(--color-primary)'}}>{tp.type}</span></td>
                                <td className="td-name">{tp.title}</td>
                                <td className="td-muted">{tp.company?.name||'—'}</td>
                                <td className="td-date">{new Date(tp.created_at).toLocaleDateString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                    }
                  </div>
                )}
              </div>
              {/* Resize handle — bottom-right (DOM manipulation during drag, state sync only on mouseup) */}
              {editing && (
                <div className="resize-grip" draggable={false} onMouseDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  const startX = e.clientX
                  const startSpan = item.span
                  const grid = gridRef.current
                  const widgetEl = (e.currentTarget as HTMLElement).closest('.dash-widget') as HTMLElement
                  if (!grid || !widgetEl) return
                  // Cache column metrics so we don't recalc every frame
                  const gridRect = grid.getBoundingClientRect()
                  const gap = 14
                  const colW = (gridRect.width - (11 * gap)) / 12
                  const clsRe = /span-\d+/
                  const onMove = (ev: MouseEvent) => {
                    const dx = ev.clientX - startX
                    const newSpan = Math.max(1, Math.min(12, Math.round(startSpan + dx / (colW + gap))))
                    if (newSpan === (parseInt(widgetEl.className.match(/span-(\d+)/)?.[1] || '0'))) return
                    // Direct DOM — no React re-render
                    widgetEl.className = widgetEl.className.replace(clsRe, `span-${newSpan}`)
                    widgetEl.style.gridColumn = `span ${newSpan}`
                  }
                  const onUp = () => {
                    document.removeEventListener('mousemove', onMove)
                    document.removeEventListener('mouseup', onUp)
                    if (!widgetEl) return
                    const finalSpan = parseInt(widgetEl.className.match(/span-(\d+)/)?.[1] || String(startSpan))
                    widgetEl.style.gridColumn = ''
                    if (finalSpan !== startSpan) resizeW(k, finalSpan)
                  }
                  document.addEventListener('mousemove', onMove)
                  document.addEventListener('mouseup', onUp)
                }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12L12 22M22 2L2 22"/></svg>
                </div>
              )}
            </div>
          )
        })}
        {/* Add widget tile */}
        {editing && (
          <div className="dash-add-tile" onClick={() => setShowPicker(!showPicker)}>
            <SvcIcon name="plus" size={24} />
            <span>{t('dashboard.addWidget')}</span>
          </div>
        )}
      </div>

      {/* Widget picker */}
      {showPicker && (
        <div className="picker-bar">
          {Object.entries(allWidgets).filter(([k]) => !widgetItems.some(w => w.key === k)).map(([k, v]) => (
            <button key={k} className="picker-btn" onClick={() => addWidget(k)}>+ {v.label}</button>
          ))}
          {Object.keys(allWidgets).length === widgetItems.length && <span className="picker-done">{t('greeting.allWidgetsAdded')}</span>}
        </div>
      )}

      {/* ── SlideDrawer ── */}
      <SlideDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title={drawerTitle} width="30vw">
        {drawerContent}
      </SlideDrawer>
    </div>
  )
}

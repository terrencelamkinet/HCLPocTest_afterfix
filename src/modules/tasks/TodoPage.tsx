import '../../styles/todo.css'
import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { apiClient } from '../../lib/api'
import { useTranslation } from 'react-i18next'
import NexusEditor from '../../components/editor/NexusEditor'
import { Repeat, Paperclip, Share2, MoreVertical, ArrowDown, Palette, Bookmark } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'

/* ── Types ── */
interface TaskList {
  id: string; name: string; color: string; icon?: string; sort_order: number; is_smart: boolean
}
interface Task {
  id: string; title: string; status: string; priority: string
  due_date?: string | null; is_important: boolean; my_day_date?: string | null
  reminder_at?: string | null; recurrence_rule?: string | null; notes_html?: string | null
  list_id?: string | null; contact_id?: string | null; company_id?: string | null
  deal_id?: string | null; assignee_id?: string | null; completed_at?: string | null
  steps?: TaskStep[]; categories?: TaskCategory[]; attachments?: TaskAttachment[]
  step_count?: number; step_done?: number
}
interface TaskStep { id: string; title: string; is_completed: boolean; sort_order: number }
interface TaskCategory { id: string; name: string; color: string }
interface TaskAttachment { id: string; filename: string; file_size?: number; content_type?: string }

// ── List icon options (PenguinCRM SVG kit — v7.24) ──
const LIST_ICON_OPTIONS: { value: string; icon: React.ReactNode; label: string }[] = [
  { value: 'inbox', icon: <SvcIcon name="task-list" size={16} />, label: 'Inbox' },
  { value: 'star', icon: <SvcIcon name="task-important" size={16} />, label: 'Star' },
  { value: 'calendar', icon: <SvcIcon name="calendar" size={16} />, label: 'Calendar' },
  { value: 'sun', icon: <SvcIcon name="task-my-day" size={16} />, label: 'Sun' },
  { value: 'check', icon: <SvcIcon name="task-complete" size={16} />, label: 'Check' },
  { value: 'user', icon: <SvcIcon name="task-assigned" size={16} />, label: 'User' },
  { value: 'bell', icon: <SvcIcon name="task-due" size={16} />, label: 'Bell' },
  { value: 'flag', icon: <SvcIcon name="task-priority" size={16} />, label: 'Flag' },
  { value: 'briefcase', icon: <SvcIcon name="project-active" size={16} />, label: 'Briefcase' },
  { value: 'home', icon: <SvcIcon name="company-branch" size={16} />, label: 'Home' },
  { value: 'heart', icon: <SvcIcon name="vip-contact" size={16} />, label: 'Heart' },
  { value: 'bookmark', icon: <Bookmark size={16} />, label: 'Bookmark' },
]

// ── List color palette (design tokens 8 色) ──
const LIST_COLORS = ['#0f6f6f', '#c23b4a', '#2870b8', '#6f6d68', '#387a3a', '#7350ad', '#b9760f', '#0b7285']

export default function TodoPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation()
  const [lists, setLists] = useState<TaskList[]>([])
  const [activeListId, setActiveListId] = useState<string | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [loading, setLoading] = useState(true)
  const [newTitle, setNewTitle] = useState('')
  const [showShare, setShowShare] = useState(false)
  const [newListName, setNewListName] = useState('')
  const [showNewList, setShowNewList] = useState(false)
  const [showLeft, setShowLeft] = useState(false)
  const [showCatPicker, setShowCatPicker] = useState(false)
  const [categories, setCategories] = useState<TaskCategory[]>([])
  // List ⋯ menu state (2026-08-18 My List dropdown: rename/priority/type/delete)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [typeFor, setTypeFor] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<TaskList | null>(null)
  // Persisted toggle: hide completed tasks (default ON). Stored in localStorage so the choice survives reloads.
  const [hideCompleted, setHideCompleted] = useState<boolean>(() => {
    const stored = localStorage.getItem('nexus.todo.hideCompleted')
    return stored === null ? true : stored === '1'
  })
  const inputRef = useRef<HTMLInputElement>(null)
  const detailRef = useRef<HTMLDivElement>(null)

  // Pre-select list from URL param
  const contactFilter = searchParams.get('contact_id')
  const companyFilter = searchParams.get('company_id')

  // Per-user toggle: hide completed tasks. Persisted to localStorage.
  const toggleHideCompleted = () => {
    setHideCompleted(prev => {
      const next = !prev
      localStorage.setItem('nexus.todo.hideCompleted', next ? '1' : '0')
      return next
    })
  }

  // ── Fetch lists ──
  const fetchLists = useCallback(async () => {
    try {
      const data = await apiClient.get<any>('/api/v1/crm/todo/lists')
      const items = data?.items || data || []
      setLists(items)
      return items
    } catch { return [] }
  }, [])

  // ── Fetch tasks ──
  const fetchTasks = useCallback(async (listId?: string | null, smart?: string) => {
    setLoading(true)
    try {
      let url = '/api/v1/crm/todo/tasks?limit=100'
      if (contactFilter) url += `&contact_id=${contactFilter}`
      else if (companyFilter) url += `&company_id=${companyFilter}`
      else if (smart) url += `&smart=${smart}`
      else if (listId) url += `&list_id=${listId}`
      const data = await apiClient.get<any>(url)
      const items = data?.items || data || []
      setTasks(items)
    } catch { setTasks([]) }
    finally { setLoading(false) }
  }, [contactFilter, companyFilter])

  // ── Init ──
  useEffect(() => {
    fetchLists().then(allLists => {
      const smart = searchParams.get('smart') || 'all'
      const smartList = allLists?.find((l: TaskList) => l.is_smart && l.name.toLowerCase().includes(smart))
      if (smartList) setActiveListId(smartList.id)
      else if (allLists?.length) setActiveListId(allLists[0].id)
      fetchTasks(smartList?.id, smart)
    })
  }, [])

  // ── Select list ──
  const selectList = (list: TaskList) => {
    setActiveListId(list.id)
    setSelectedTask(null)
    setShowLeft(false)
    if (list.is_smart) {
      const t = list.name.toLowerCase().includes('my day') ? 'myday'
        : list.name.toLowerCase().includes('important') ? 'important'
        : list.name.toLowerCase().includes('planned') ? 'planned'
        : list.name.toLowerCase().includes('completed') ? 'completed'
        : list.name.toLowerCase().includes('assigned') ? 'assigned'
        : list.name.toLowerCase().includes('due today') ? 'due_today'
        : 'all'
      fetchTasks(null, t)
    } else {
      fetchTasks(list.id)
    }
  }

  // ── List ⋯ menu actions (2026-08-18: rename / priority / type / delete) ──
  const startRename = (list: TaskList) => {
    setRenamingId(list.id); setRenameValue(list.name); setMenuFor(null); setTypeFor(null)
  }
  const saveRename = async (list: TaskList) => {
    const name = renameValue.trim()
    setRenamingId(null)
    if (!name || name === list.name) return
    try {
      const updated = await apiClient.patch<TaskList>(`/api/v1/crm/todo/lists/${list.id}`, { name })
      setLists(prev => prev.map(l => l.id === list.id ? { ...l, ...updated } : l))
      if (activeListId === list.id) setActiveListId(list.id)
    } catch {}
  }
  const moveList = async (list: TaskList, dir: -1 | 1) => {
    const customs = lists.filter(l => !l.is_smart).sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
    const idx = customs.findIndex(l => l.id === list.id)
    const swap = customs[idx + dir]
    if (!swap) return
    setMenuFor(null)
    try {
      // 移動後成組重新分配連續 sort_order (0,1,2...) — 解決同值撞車
      const newOrder = [...customs]
      ;[newOrder[idx], newOrder[idx + dir]] = [newOrder[idx + dir], newOrder[idx]]
      await Promise.all(newOrder.map((l, i) =>
        l.sort_order === i ? Promise.resolve() : apiClient.patch(`/api/v1/crm/todo/lists/${l.id}`, { sort_order: i })
      ))
      fetchLists()
    } catch {}
  }
  const setListIcon = async (list: TaskList, icon: string) => {
    setTypeFor(null)
    try {
      const updated = await apiClient.patch<TaskList>(`/api/v1/crm/todo/lists/${list.id}`, { icon })
      setLists(prev => prev.map(l => l.id === list.id ? { ...l, ...updated } : l))
    } catch {}
  }
  const setListColor = async (list: TaskList, color: string) => {
    setTypeFor(null)
    try {
      const updated = await apiClient.patch<TaskList>(`/api/v1/crm/todo/lists/${list.id}`, { color })
      setLists(prev => prev.map(l => l.id === list.id ? { ...l, ...updated } : l))
    } catch {}
  }
  const confirmDeleteList = async () => {
    if (!deleteTarget) return
    const target = deleteTarget
    setDeleteTarget(null)
    try {
      await apiClient.delete(`/api/v1/crm/todo/lists/${target.id}`)
      setLists(prev => prev.filter(l => l.id !== target.id))
      if (activeListId === target.id) {
        const all = lists.find(l => l.is_smart && l.name.toLowerCase().includes('all'))
        if (all) { setActiveListId(all.id); fetchTasks(null, 'all') }
        else fetchLists().then(allLists => { if (allLists?.length) { setActiveListId(allLists[0].id); fetchTasks(allLists[0].id) } })
      }
    } catch {}
  }

  const renderListIcon = (list: TaskList) => {
    if (!list.icon) return <span className="l-color" style={{ background: list.color || '#999' }} />
    const opt = LIST_ICON_OPTIONS.find(o => o.value === list.icon)
    return <span className="l-icon" style={{ color: list.color || 'var(--color-text-muted)' }}>{opt?.icon || <SvcIcon name="task-list" size={16} />}</span>
  }

  // ── Create task ──
  const createTask = async () => {
    if (!newTitle.trim()) return
    try {
      const task = await apiClient.post('/api/v1/crm/todo/tasks', {
        title: newTitle.trim(),
        list_id: activeListId,
        contact_id: contactFilter || undefined,
        company_id: companyFilter || undefined,
      })
      setTasks(prev => [task, ...prev])
      setNewTitle('')
      inputRef.current?.focus()
    } catch {}
  }

  // ── Toggle complete ──
  const toggleComplete = async (task: Task) => {
    const done = task.status === 'done' ? 'pending' : 'done'
    try {
      await apiClient.patch(`/api/v1/crm/todo/tasks/${task.id}`, { status: done })
      setTasks(prev => prev.map(t => t.id === task.id ? { ...t, status: done, completed_at: done === 'done' ? new Date().toISOString() : null } : t))
      if (selectedTask?.id === task.id) setSelectedTask(prev => prev ? { ...prev, status: done } : null)
    } catch {}
  }

  // ── Toggle important ──
  const toggleImportant = async (task: Task) => {
    const v = !task.is_important
    try {
      await apiClient.patch(`/api/v1/crm/todo/tasks/${task.id}`, { is_important: v })
      setTasks(prev => prev.map(t => t.id === task.id ? { ...t, is_important: v } : t))
      if (selectedTask?.id === task.id) setSelectedTask(prev => prev ? { ...prev, is_important: v } : null)
    } catch {}
  }

  // ── Delete task ──
  const deleteTask = async (id: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/todo/tasks/${id}`)
      setTasks(prev => prev.filter(t => t.id !== id))
      if (selectedTask?.id === id) setSelectedTask(null)
    } catch {}
  }

  // ── Attachments ──
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const uploadAttachment = async (taskId: string, file: File) => {
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const att = await apiClient.post<TaskAttachment>(`/api/v1/crm/todo/tasks/${taskId}/attachments`, fd)
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, attachments: [...(t.attachments || []), att] } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, attachments: [...(prev.attachments || []), att] } : prev)
    } catch {}
    finally { setUploading(false) }
  }
  const deleteAttachment = async (taskId: string, attId: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/todo/tasks/${taskId}/attachments/${attId}`)
      const filt = (a: TaskAttachment) => a.id !== attId
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, attachments: t.attachments?.filter(filt) } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, attachments: prev.attachments?.filter(filt) } : prev)
    } catch {}
  }

  // ── Update task field ──
  const updateTask = async (id: string, updates: Partial<Task>) => {
    try {
      await apiClient.patch(`/api/v1/crm/todo/tasks/${id}`, updates)
      setTasks(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
      setSelectedTask(prev => prev?.id === id ? { ...prev, ...updates } : prev)
    } catch {}
  }

  // ── Steps ──
  const addStep = async (taskId: string, title: string) => {
    try {
      const step = await apiClient.post(`/api/v1/crm/todo/tasks/${taskId}/steps`, { title })
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, steps: [...(t.steps || []), step], step_count: (t.step_count || 0) + 1 } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, steps: [...(prev.steps || []), step] } : prev)
    } catch {}
  }
  const toggleStep = async (taskId: string, step: TaskStep) => {
    try {
      await apiClient.patch(`/api/v1/crm/todo/tasks/${taskId}/steps/${step.id}`, { is_completed: !step.is_completed })
      const upd = (s: TaskStep) => s.id === step.id ? { ...s, is_completed: !s.is_completed } : s
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, steps: t.steps?.map(upd) } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, steps: prev.steps?.map(upd) } : prev)
    } catch {}
  }
  const deleteStep = async (taskId: string, stepId: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/todo/tasks/${taskId}/steps/${stepId}`)
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, steps: t.steps?.filter(s => s.id !== stepId), step_count: Math.max(0, (t.step_count || 0) - 1) } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, steps: prev.steps?.filter(s => s.id !== stepId) } : prev)
    } catch {}
  }

  // ── Categories ──
  const fetchCategories = async () => {
    try {
      const data = await apiClient.get<any>('/api/v1/crm/todo/categories')
      setCategories(data?.items || data || [])
    } catch {}
  }
  useEffect(() => { fetchCategories() }, [])
  const addCategory = async (taskId: string, catId: string) => {
    try {
      await apiClient.post(`/api/v1/crm/todo/tasks/${taskId}/categories`, { category_id: catId })
      const cat = categories.find(c => c.id === catId)
      if (cat) {
        setTasks(prev => prev.map(t => t.id === taskId ? { ...t, categories: [...(t.categories || []), cat] } : t))
        setSelectedTask(prev => prev?.id === taskId ? { ...prev, categories: [...(prev.categories || []), cat] } : prev)
      }
    } catch {}
  }
  const removeCategory = async (taskId: string, catId: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/todo/tasks/${taskId}/categories/${catId}`)
      const filt = (c: TaskCategory) => c.id !== catId
      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, categories: t.categories?.filter(filt) } : t))
      setSelectedTask(prev => prev?.id === taskId ? { ...prev, categories: prev.categories?.filter(filt) } : prev)
    } catch {}
  }

  // ── Toggle My Day ──
  const toggleMyDay = async (task: Task) => {
    try {
      await apiClient.get(`/api/v1/crm/todo/my-day/toggle/${task.id}`)
      const hasMyDay = !task.my_day_date
      const today = hasMyDay ? new Date().toISOString().split('T')[0] : null
      setTasks(prev => prev.map(t => t.id === task.id ? { ...t, my_day_date: today } : t))
      setSelectedTask(prev => prev?.id === task.id ? { ...prev, my_day_date: today } : prev)
    } catch {}
  }

  // ── Smart list icon ──
  const smartIcon = (name: string) => {
    if (name.includes('My Day')) return '☀️'
    if (name.includes('Important')) return '⭐'
    if (name.includes('Planned')) return '📅'
    if (name.includes('All')) return '📋'
    if (name.includes('Completed')) return '✅'
    if (name.includes('Assigned')) return '👤'
    if (name.includes('Due Today')) return '🔔'
    return '📋'
  }

  // ── Due date display ──
  const dueLabel = (d?: string | null) => {
    if (!d) return null
    const dt = new Date(d)
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const tom = new Date(today); tom.setDate(tom.getDate() + 1)
    const diff = Math.ceil((dt.getTime() - today.getTime()) / 86400000)
    const cls = diff < 0 ? 'overdue' : diff === 0 ? 'today' : 'future'
    const label = diff === 0 ? t('pages.tasks.today') : diff === 1 ? t('pages.tasks.tomorrow') : diff < 0 ? t('pages.tasks.daysOverdue', { count: Math.abs(diff) }) : dt.toLocaleDateString('zh-HK', { month: 'short', day: 'numeric' })
    return <span className={`t-due ${cls}`}>{label}</span>
  }

  // ── Build detail ──
  const activeList = lists.find(l => l.id === activeListId) || null

  return (
    <>
      {/* Mobile scrim for left panel */}
      {showLeft && <div className="share-overlay" onClick={() => setShowLeft(false)} style={{zIndex:55}} />}

      <div className={`todo-page${selectedTask ? ' detail-open' : ''}`}
        onClick={e => {
          // Click-outside: click 喺 .todo-right 外面（主體空白/header）→ 收起 drawer
          if (selectedTask && !(e.target as Element).closest('.todo-right')) {
            setSelectedTask(null)
          }
        }}>
        {/* ── LEFT PANEL ── */}
        <aside className={`todo-left${showLeft ? ' show' : ''}`}>
          <div className="todo-left-head">{t('pages.tasks.lists')}</div>
          <div className="todo-list-group">
            {lists.filter(l => l.is_smart).map(l => (
              <div key={l.id} className={`todo-list-item${activeListId === l.id ? ' active' : ''}`} onClick={() => selectList(l)}>
                <span className="l-icon">{smartIcon(l.name)}</span>
                <span className="l-name">{l.name.replace(/^[^\s]+\s/, '')}</span>
                <span className="l-count">{l.name === '📋 All' ? tasks.length : ''}</span>
              </div>
            ))}
          </div>
          <div className="todo-list-sep" />
          <div className="todo-left-head">{t('pages.tasks.myLists')}</div>
          <div className="todo-list-group">
            {lists.filter(l => !l.is_smart).map(l => {
              const customs = lists.filter(x => !x.is_smart).sort((a, b) => a.sort_order - b.sort_order)
              const idx = customs.findIndex(x => x.id === l.id)
              return (
                <div key={l.id} className={`todo-list-item${activeListId === l.id ? ' active' : ''}${menuFor === l.id || typeFor === l.id ? ' menu-open' : ''}`} onClick={() => selectList(l)}>
                  {renderListIcon(l)}
                  {renamingId === l.id ? (
                    <input
                      className="l-rename-input"
                      value={renameValue}
                      autoFocus
                      onChange={e => setRenameValue(e.target.value)}
                      onBlur={() => saveRename(l)}
                      onKeyDown={e => { if (e.key === 'Enter') saveRename(l); if (e.key === 'Escape') setRenamingId(null) }}
                      onClick={e => e.stopPropagation()}
                    />
                  ) : (
                    <span className="l-name">{l.name}</span>
                  )}
                  <span className="l-count">{tasks.length}</span>
                  <button
                    className="l-menu-btn"
                    aria-label={t('common.moreOptions', { defaultValue: 'More options' })}
                    onClick={e => { e.stopPropagation(); setMenuFor(menuFor === l.id ? null : l.id); setTypeFor(null) }}
                  ><MoreVertical size={14} /></button>
                  {menuFor === l.id && (
                    <div className="tl-menu" onClick={e => e.stopPropagation()}>
                      <button onClick={() => startRename(l)}><SvcIcon name="pencil" size={14} /> {t('pages.tasks.renameList', { defaultValue: '重新命名' })}</button>
                      <button onClick={() => moveList(l, -1)} disabled={idx <= 0}><SvcIcon name="arrow-up" size={14} /> {t('pages.tasks.moveUp', { defaultValue: '上移' })}</button>
                      <button onClick={() => moveList(l, 1)} disabled={idx >= customs.length - 1}><ArrowDown size={14} /> {t('pages.tasks.moveDown', { defaultValue: '下移' })}</button>
                      <div className="tl-menu-sep" />
                      <button onClick={() => { setTypeFor(typeFor === l.id ? null : l.id); setMenuFor(null) }}><Palette size={14} /> {t('pages.tasks.listType', { defaultValue: '類型' })}</button>
                      <button className="danger" onClick={() => setDeleteTarget(l)}><SvcIcon name="trash-2" size={14} /> {t('pages.tasks.deleteList', { defaultValue: '刪除' })}</button>
                    </div>
                  )}
                  {typeFor === l.id && (
                    <div className="tl-type-pop" onClick={e => e.stopPropagation()}>
                      <div className="tl-type-label">{t('pages.tasks.listIcon', { defaultValue: '圖示' })}</div>
                      <div className="tl-type-icons">
                        {LIST_ICON_OPTIONS.map(o => (
                          <button key={o.value} className={l.icon === o.value ? 'active' : ''} onClick={() => setListIcon(l, o.value)} title={o.label}>{o.icon}</button>
                        ))}
                      </div>
                      <div className="tl-type-label">{t('pages.tasks.listColor', { defaultValue: '顏色' })}</div>
                      <div className="tl-type-colors">
                        {LIST_COLORS.map(c => (
                          <button key={c} className={l.color === c ? 'active' : ''} style={{ background: c }} onClick={() => setListColor(l, c)} aria-label={c} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          <button className="todo-add-list" onClick={() => setShowNewList(!showNewList)}>
            <SvcIcon name="plus" size={14} /> {t('pages.tasks.newList')}
          </button>
          {showNewList && (
            <div style={{display:'flex',gap:6,padding:'4px 10px'}}>
              <input type="text" placeholder={t('pages.tasks.listNamePlaceholder')} value={newListName}
                onChange={e => setNewListName(e.target.value)}
                style={{flex:1,border:'1px solid var(--color-border)',borderRadius:'var(--radius-sm)',padding:'4px 8px',fontSize:12,outline:'none',background:'var(--color-surface)'}}
                onKeyDown={async e => {
                  if (e.key === 'Enter' && newListName.trim()) {
                    try {
                      await apiClient.post('/api/v1/crm/todo/lists', { name: newListName.trim() })
                      setNewListName(''); setShowNewList(false)
                      fetchLists()
                    } catch {}
                  }
                }} />
            </div>
          )}
        </aside>

        {/* ── CENTER PANEL ── */}
        <div className="todo-center">
          <div className="todo-list-header">
            <button className="icon-btn-small mobile-hamburger" onClick={() => setShowLeft(true)}><SvcIcon name="list" size={18} /></button>
            <h2>
              {activeList?.is_smart && <span>{smartIcon(activeList?.name || '')}</span>}
              {!activeList?.is_smart && <span className="lh-color" style={{background:activeList?.color}} />}
              {activeList?.name?.replace(/^[^\s]+\s/, '') || t('pages.tasks.title')}
            </h2>
            <button type="button" className={`lh-hide-switch${hideCompleted ? ' on' : ''}`}
              onClick={toggleHideCompleted} role="switch" aria-checked={hideCompleted}
              title={hideCompleted ? t('pages.tasks.showCompleted') : t('pages.tasks.hideCompleted')}>
              <span className="lh-hide-track"><span className="lh-hide-thumb" /></span>
              <span className="lh-hide-label">{hideCompleted ? t('pages.tasks.hideCompleted') : t('pages.tasks.showCompleted')}</span>
            </button>
            <div className="lh-actions">
              {!activeList?.is_smart && activeList && (
                <button className="icon-btn-small" onClick={() => setShowShare(true)} title={t('pages.tasks.shareList')}><Share2 size={15} /></button>
              )}
            </div>
            <span className="lh-count">{t('pages.tasks.remaining', { count: tasks.filter(t => t.status !== 'done').length })}</span>
          </div>

          <div className="todo-tasks">
            {loading ? (
              <div style={{padding:40,textAlign:'center',color:'var(--color-text-faint)',fontSize:13}}>{t('common.loading')}</div>
            ) : tasks.length === 0 ? (
              <div style={{padding:40,textAlign:'center',color:'var(--color-text-faint)',fontSize:13}}>
                {contactFilter ? t('pages.tasks.emptyForContact') : t('pages.tasks.addToGetStarted')}
              </div>
            ) : ((() => {
              const visibleTasks = hideCompleted ? tasks.filter(t => t.status !== 'done') : tasks
              return visibleTasks.length === 0 ? (
                <div style={{padding:40,textAlign:'center',color:'var(--color-text-faint)',fontSize:13}}>
                  {hideCompleted && tasks.some(t => t.status === 'done')
                    ? t('pages.tasks.allDoneHidden')
                    : (contactFilter ? t('pages.tasks.emptyForContact') : t('pages.tasks.addToGetStarted'))}
                </div>
              ) : visibleTasks.map(task => (
                <div key={task.id}
                  className={`todo-task-row${task.status === 'done' ? ' done' : ''}${selectedTask?.id === task.id ? ' selected' : ''}`}
                  onClick={e => { e.stopPropagation(); setSelectedTask(task) }}>
                  <button className={`t-check${task.status === 'done' ? ' checked' : ''}`} onClick={e => { e.stopPropagation(); toggleComplete(task) }}>
                    {task.status === 'done' && <SvcIcon name="check" size={11} strokeWidth={3} />}
                  </button>
                  <span className="t-title">{task.title}</span>
                  {task.my_day_date && <span className="t-myday">{t('pages.tasks.myDay')}</span>}
                  {task.step_count ? <span className="t-step-count">{task.step_done || 0}/{task.step_count}</span> : null}
                  {dueLabel(task.due_date)}
                  <button className={`t-imp${task.is_important ? ' important' : ''}`} onClick={e => { e.stopPropagation(); toggleImportant(task) }}>
                    {task.is_important ? '★' : '☆'}
                  </button>
                </div>
              ))
            })())}
          </div>

          <div className="todo-add-task at-float at-top">
            <div className="at-input-wrap">
              <textarea ref={inputRef as any} className="at-input" placeholder=" " rows={1}
                value={newTitle}
                onChange={e => setNewTitle(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); createTask() }
                }}
                aria-label={t('pages.tasks.taskPlaceholder')} />
              <label className="at-label">{t('pages.tasks.taskPlaceholder')}</label>
            </div>
            <button className="at-btn" onClick={createTask}><SvcIcon name="plus" size={16} /></button>
          </div>
        </div>

        {/* ── RIGHT DETAIL PANEL ── */}
        <aside className={`todo-right${selectedTask ? ' open' : ''}`}>
          {selectedTask && (
            <div className="todo-detail" ref={detailRef}>
              {/* Drawer close button (smooth slide-out drawer) */}
              <div className="dt-close-wrap">
                <button className="icon-btn-small dt-close" onClick={() => setSelectedTask(null)} title={t('common.close')} aria-label={t('common.close')}>
                  <SvcIcon name="chevron-right" size={18} style={{transform:'rotate(180deg)'}} />
                </button>
              </div>
              {/* Title */}
              <textarea className={`dt-title${selectedTask.status === 'done' ? ' dt-done' : ''}`}
                value={selectedTask.title}
                onChange={e => setSelectedTask({ ...selectedTask, title: e.target.value })}
                onBlur={e => updateTask(selectedTask.id, { title: e.target.value })}
                rows={1} />

              {/* Steps */}
              <div className="dt-section">
                <h4>{t('pages.tasks.steps')}</h4>
                {selectedTask.steps?.map(s => (
                  <div key={s.id} className={`dt-step${s.is_completed ? ' done' : ''}`}>
                    <button className={`s-check${s.is_completed ? ' checked' : ''}`} onClick={() => toggleStep(selectedTask.id, s)}>
                      {s.is_completed && <SvcIcon name="check" size={10} strokeWidth={3} />}
                    </button>
                    <input className="s-text" value={s.title}
                      onChange={e => setSelectedTask(prev => prev ? { ...prev, steps: prev.steps?.map(st => st.id === s.id ? { ...st, title: e.target.value } : st) } : prev)}
                      onBlur={e => apiClient.patch(`/api/v1/crm/todo/tasks/${selectedTask.id}/steps/${s.id}`, { title: e.target.value }).catch(() => {})} />
                    <button className="s-del" onClick={() => deleteStep(selectedTask.id, s.id)}><SvcIcon name="x" size={12} /></button>
                  </div>
                ))}
                <button className="dt-add-step" onClick={() => {
                  const title = prompt(t('pages.tasks.stepNamePrompt'))
                  if (title?.trim()) addStep(selectedTask.id, title.trim())
                }}><SvcIcon name="plus" size={13} /> {t('pages.tasks.addStep')}</button>
              </div>

              {/* Fields */}
              <div className="dt-section">
                <h4>{t('pages.tasks.details')}</h4>

                {/* My Day */}
                <div className="dt-field">
                  <SvcIcon name="sun" size={15} className="f-label-icon" style={{color:'var(--color-text-muted)',flexShrink:0}} />
                  <span className="f-label">{t('pages.tasks.myDay')}</span>
                  <div className={`f-toggle${selectedTask.my_day_date ? ' on' : ''}`} onClick={() => toggleMyDay(selectedTask)}>
                    <div className="f-knob" />
                  </div>
                </div>

                {/* Due Date */}
                <div className="dt-field">
                  <SvcIcon name="calendar" size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                  <span className="f-label">{t('pages.tasks.due')}</span>
                  <div className="f-value">
                    <input type="date" value={selectedTask.due_date?.split('T')[0] || ''}
                      onChange={e => updateTask(selectedTask.id, { due_date: e.target.value || null })} />
                  </div>
                </div>

                {/* Reminder */}
                <div className="dt-field">
                  <SvcIcon name="bell" size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                  <span className="f-label">{t('pages.tasks.remind')}</span>
                  <div className="f-value">
                    <input type="datetime-local" value={selectedTask.reminder_at?.slice(0, 16) || ''}
                      onChange={e => updateTask(selectedTask.id, { reminder_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
                  </div>
                </div>

                {/* Repeat */}
                <div className="dt-field">
                  <Repeat size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                  <span className="f-label">{t('pages.tasks.repeat')}</span>
                  <div className="f-value">
                    <select value={selectedTask.recurrence_rule || ''}
                      onChange={e => updateTask(selectedTask.id, { recurrence_rule: e.target.value || null })}>
                      <option value="">{t('pages.tasks.recurrence.doesNotRepeat')}</option>
                      <option value="daily">{t('pages.tasks.recurrence.daily')}</option>
                      <option value="weekdays">{t('pages.tasks.recurrence.weekdays')}</option>
                      <option value="weekly">{t('pages.tasks.recurrence.weekly')}</option>
                      <option value="biweekly">{t('pages.tasks.recurrence.biweekly')}</option>
                      <option value="monthly">{t('pages.tasks.recurrence.monthly')}</option>
                      <option value="yearly">{t('pages.tasks.recurrence.yearly')}</option>
                    </select>
                  </div>
                </div>

                {/* Categories */}
                <div className="dt-field">
                  <SvcIcon name="file-text" size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                  <span className="f-label">{t('pages.tasks.category')}</span>
                  <div className="f-value cat-pos-rel">
                    <div className="f-tag-row">
                      {selectedTask.categories?.map(c => (
                        <span key={c.id} className="f-tag" style={{background:c.color+'22',color:c.color}}
                          onClick={() => removeCategory(selectedTask.id, c.id)}>
                          {c.name} <SvcIcon name="x" size={10} />
                        </span>
                      ))}
                      <button className="f-add-tag" onClick={() => setShowCatPicker(!showCatPicker)}>+</button>
                    </div>
                    {showCatPicker && (
                      <div className="cat-picker">
                        {categories.map(c => (
                          <div key={c.id} className={`cp-item${selectedTask.categories?.some(c2 => c2.id === c.id) ? ' active' : ''}`}
                            style={{background:c.color}}
                            onClick={() => {
                              if (selectedTask.categories?.some(c2 => c2.id === c.id)) {
                                removeCategory(selectedTask.id, c.id)
                              } else {
                                addCategory(selectedTask.id, c.id)
                              }
                              setShowCatPicker(false)
                            }} />
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Attachments — upload + list, backend /tasks/:id/attachments */}
                <div className="dt-field" style={{flexDirection:'column',alignItems:'stretch',gap:8,borderBottom:'none'}}>
                  <div style={{display:'flex',alignItems:'center',gap:8}}>
                    <Paperclip size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                    <span className="f-label">{t('pages.tasks.attachments')}</span>
                    <button
                      className="btn-secondary"
                      style={{height:32,padding:'0 12px',fontSize:13,marginLeft:'auto'}}
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                    >
                      {uploading ? <SvcIcon name="loader-2" size={13} style={{marginRight:4,animation:'tbs-rotate .8s linear infinite'}} /> : `+ ${t('pages.tasks.addAttachment','Attach')}`}
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      style={{display:'none'}}
                      onChange={e => {
                        const f = e.target.files?.[0]
                        if (f) uploadAttachment(selectedTask.id, f)
                        e.target.value = ''
                      }}
                    />
                  </div>
                  {selectedTask.attachments && selectedTask.attachments.length > 0 && (
                    <div style={{display:'flex',flexDirection:'column',gap:6}}>
                      {selectedTask.attachments.map(a => (
                        <div key={a.id} style={{display:'flex',alignItems:'center',gap:8,padding:'8px',border:'1px solid var(--color-border)',borderRadius:'var(--radius-md)',background:'var(--color-surface-offset)'}}>
                          <Paperclip size={13} style={{color:'var(--color-text-faint)',flexShrink:0}} />
                          <a
                            href={`/api/v1/crm/todo/tasks/${selectedTask.id}/attachments/${a.id}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{flex:1,minWidth:0,fontSize:12.5,color:'var(--color-primary)',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}
                            title={a.filename}
                          >{a.filename}</a>
                          <button
                            className="icon-btn-small"
                            onClick={() => deleteAttachment(selectedTask.id, a.id)}
                            title={t('common.delete')}
                            style={{color:'var(--color-notification)'}}
                          ><SvcIcon name="x" size={12} /></button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Notes — rich text editor w/ floating toolbar (design04 spec) */}
                <div className="dt-field" style={{flexDirection:'column',alignItems:'stretch',gap:6,borderBottom:'none'}}>
                  <div style={{display:'flex',alignItems:'center',gap:8}}>
                    <SvcIcon name="file-text" size={15} style={{color:'var(--color-text-muted)',flexShrink:0}} />
                    <span className="f-label">{t('pages.tasks.notes')}</span>
                    <span style={{marginLeft:'auto',fontSize:11,color:'var(--color-text-faint)'}}>{t('pages.tasks.notesHint','可貼 design link / Word / Google Sheet 連結')}</span>
                  </div>
                  <NexusEditor
                    content={selectedTask.notes_html || ''}
                    onChange={html => setSelectedTask({ ...selectedTask, notes_html: html })}
                    onSave={html => updateTask(selectedTask.id, { notes_html: html || null })}
                    placeholder={t('pages.tasks.addNotes')}
                    minHeight={140}
                    entityContext={{ type: 'task', id: selectedTask.id }}
                  />
                </div>
              </div>

              {/* Actions */}
              <div style={{borderTop:'1px solid var(--color-divider)',paddingTop:12,marginTop:4,display:'flex',gap:8}}>
                <button className="icon-btn-small" onClick={() => deleteTask(selectedTask.id)} title={t('common.delete')} style={{color:'var(--color-notification)'}}>
                  <SvcIcon name="trash-2" size={15} />
                </button>
                <button className="icon-btn-small" onClick={() => navigate(`/tasks/${selectedTask.id}`)} title={t('pages.tasks.openStandalone')} style={{marginLeft:'auto'}}>
                  <SvcIcon name="chevron-right" size={15} />
                </button>
              </div>
            </div>
          )}
        </aside>
      </div>

      {/* ── Share Dialog ── */}
      {showShare && activeList && (
        <ShareDialog listId={activeList.id} onClose={() => setShowShare(false)} />
      )}

      {/* ── Delete List Confirm (2026-08-18) ── */}
      {deleteTarget && (
        <div className="share-overlay" onClick={() => setDeleteTarget(null)}>
          <div className="share-dialog" onClick={e => e.stopPropagation()}>
            <h3>{t('pages.tasks.deleteListTitle', { defaultValue: '刪除清單' })}</h3>
            <p style={{ fontSize: 13.5, color: 'var(--color-text-secondary)', margin: '8px 0 16px', lineHeight: 1.5 }}>
              {t('pages.tasks.deleteListConfirm', { defaultValue: '確定要刪除「{{name}}」？入面嘅任務會移去「所有任務」。此操作無法還原。', name: deleteTarget.name })}
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn-secondary" onClick={() => setDeleteTarget(null)}>{t('common.cancel')}</button>
              <button className="btn-danger" style={{ background: 'var(--color-notification)', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }} onClick={confirmDeleteList}>
                {t('common.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/* ── Share Dialog Component ── */
function ShareDialog({ listId, onClose }: { listId: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [permission, setPermission] = useState('read')
  const [shares, setShares] = useState<{ user_email: string; permission: string }[]>([])

  useEffect(() => {
    apiClient.get<any[]>(`/api/v1/crm/todo/lists/${listId}/shares`).then(d => setShares(d || [])).catch(() => {})
  }, [listId])

  const addShare = async () => {
    if (!email.trim()) return
    try {
      await apiClient.post(`/api/v1/crm/todo/lists/${listId}/share`, { email: email.trim(), permission })
      setShares(prev => [...prev, { user_email: email.trim(), permission }])
      setEmail('')
    } catch {}
  }

  return (
    <div className="share-overlay" onClick={onClose}>
      <div className="share-dialog" onClick={e => e.stopPropagation()}>
        <h3>{t('pages.tasks.shareListTitle')}</h3>
        <div className="sd-field">
          <input type="text" placeholder={t('pages.tasks.shareEmailPlaceholder')} value={email} onChange={e => setEmail(e.target.value)} />
          <select value={permission} onChange={e => setPermission(e.target.value)}>
            <option value="read">{t('pages.tasks.sharePermissionRead')}</option>
            <option value="write">{t('pages.tasks.sharePermissionWrite')}</option>
          </select>
          <button className="btn-primary" style={{height:36,fontSize:12}} onClick={addShare}>{t('pages.tasks.shareAdd')}</button>
        </div>
        {shares.length > 0 && (
          <div className="sd-shared">
            {shares.map((s, i) => (
              <div key={i} className="sd-row">
                <span className="sd-email">{s.user_email}</span>
                <span className="sd-perm">{s.permission}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{textAlign:'right'}}>
          <button className="btn-secondary" onClick={onClose}>{t('common.close')}</button>
        </div>
      </div>
    </div>
  )
}

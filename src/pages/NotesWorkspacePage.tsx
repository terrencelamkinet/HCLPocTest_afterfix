import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { History, Maximize2, Minimize2, MoreHorizontal, RotateCcw } from 'lucide-react'
import SvcIcon from '../components/SvcIcon'
import NexusEditor from '../components/editor/NexusEditor'
import { useMobile } from '../components/editor/useMobile'
import { apiClient, errText, UUID_RE } from '../lib/api'
import { deriveAllNotesTotal, notebookCountOf } from '../lib/noteCounts'
import { nextStateOnBack, openState, shouldShowGlobalNav, type NotesMobileState } from '../lib/notesMobileState'
import SortSheet from '../components/notes/SortSheet'
import EditorMoreSheet from '../components/notes/EditorMoreSheet'
import { useKeyboardInsetVar } from '../lib/useKeyboardInset'
import {
  SAVE_STATUS_FALLBACK,
  SAVE_STATUS_KEY,
  createSaveSequencer,
  saveStatusAfter,
  type SaveStatus,
} from '../lib/saveSequencer'

/**
 * Notes module v2 — 3-pane workspace（T1.3 + T1.4，2026-09-11）
 *
 * SPEC: docs/notes-module-v2-SPEC.md
 *   T1.3  左 rail（可 collapse）/ 中列表（list・card・compact、搜尋、排序、釘選）/ 右 pane
 *   T1.4  右 pane = NexusEditor（checklist 持久化）+ Zen mode（全頁）
 *
 * Route: /notes/n/:notebookId  — notebookId = 'all' | 'uncat' | <uuid>
 * 筆記本體（私人筆記）由 API 層按 tenant 隔離；author-only 過濾係 T1.5。
 */

interface Notebook {
  id: string
  name: string
  color: string
  note_count: number
}

interface NoteLink {
  id: string
  entity_type: string
  entity_id?: string | null
  label?: string | null
  url?: string | null
}

interface Note {
  id: string
  title: string | null
  content: string | null
  pinned: boolean
  notebook_id: string | null
  note_links?: NoteLink[] | null
  updated_at: string
  created_at: string
  /** Stage C (T-02) 樂觀鎖用 */
  version?: number
  deleted_at?: string | null
}

type ViewMode = 'list' | 'card' | 'compact'

const SORTS = [
  { value: 'updated_desc', key: 'notes.sortUpdated' },
  { value: 'created_desc', key: 'notes.sortCreated' },
  { value: 'title_asc', key: 'notes.sortTitle' },
] as const

const RAIL_KEY = 'nw.rail.collapsed'
const VIEW_KEY = 'nw.view'
/** Stage D (T-10) 每頁筆記數 — 之前係一次過 200 條硬上限，500+ 篇會截斷 */
const PAGE_SIZE = 60

/** HTML（TipTap 出 HTML）→ 純文字摘要 */
function plain(html: string | null | undefined): string {
  if (!html) return ''
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

export default function NotesWorkspacePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isMobile = useMobile(900)

  /* P0-4（2026-09-13）：軟鍵盤高度寫入 CSS 變數 --kb-inset，底部固定元素
     （sort sheet／undo bar／editor accessory bar）靠 CSS 跟住鍵盤升，唔使 re-render。 */
  useKeyboardInsetVar()
  const { notebookId = 'all', noteId: deepNoteId } = useParams<{ notebookId?: string; noteId?: string }>()

  const [notebooks, setNotebooks] = useState<Notebook[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  /** Stage D (T-10) 增量載入 — SPEC edge case #9「500+ 篇仍然順」 */
  const [loadingMore, setLoadingMore] = useState(false)
  const offsetRef = useRef(0)
  /** Stage C (T-02) — 每個 note 嘅最新 version 鏡像。
      用 ref 而唔係 state：debounce 計時器（標題）／autosave 回呼拎嘅係舊 render 嘅
      closure，讀 state 會攞到過期 version → 假 409 衝突。 */
  const versionRef = useRef<Record<string, number>>({})
  const [error, setError] = useState('')
  /** 儲存錯誤獨立於一般 error：一般 error render 喺 list pane，而 mobile 去咗 editor
      pane 之後係睇唔到嘅（review T-01 補漏）。 */
  const [saveError, setSaveError] = useState('')
  /** P0-6（2026-09-13）：Saving／Saved／Offline changes／Save failed 要顯示出嚟，
      唔可以只喺 console 或者一個 banner。 */
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  /** P0-6：每個 note 一條 generation 序列 —— 舊 request 遲返嘅回應一律掉棄，
      否則會寫錯 version，之後全部變假 409 衝突。 */
  const saveSeqRef = useRef(createSaveSequencer())
  /** Stage B (T-04) 撤銷刪除 bar — soft delete 之後 6 秒內可以撳還原 */
  const [undo, setUndo] = useState<{ id: string; title: string; timer: any } | null>(null)
  /** Stage C (T-02) 樂觀鎖衝突（另一個 tab／裝置改過） */
  const [conflict, setConflict] = useState<{ current: number } | null>(null)
  /** Stage C (T-03) History drawer */
  const [history, setHistory] = useState<{ open: boolean; loading: boolean; items: any[] }>({ open: false, loading: false, items: [] })
  /** 還原 revision 之後要強制 remount NexusEditor（佢只在 init 讀 content） */
  const [edKey, setEdKey] = useState(0)
  /** 最後一次送出嘅 html — 衝突時揀「保留我嘅版本」要用 */
  const pendingHtml = useRef<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [sort, setSort] = useState<string>('updated_desc')
  const [view, setView] = useState<ViewMode>(() => (localStorage.getItem(VIEW_KEY) as ViewMode) || 'list')
  const [railCollapsed, setRailCollapsed] = useState(() => localStorage.getItem(RAIL_KEY) === '1')
  /* P0-2（2026-09-13）：mobile 任何時間只可以有一層擁有 bottom 區域。
     原本 railOpen / mobileEditor / tpl.open 三個 boolean 散落各處 → 會出現
     「global nav 同 sheet 同時爭 bottom」同「唔知邊個應該收」。改為單一狀態機
     （src/lib/notesMobileState.ts），以下兩個 flag 只係派生值。 */
  const [mobileState, setMobileState] = useState<NotesMobileState>('list')
  /* P1-⑪：「更多」sheet 係由邊個狀態開（editor 開 → 關咗要返 editor，唔係返 list） */
  const moreFromRef = useRef<NotesMobileState>('list')
  const [zen, setZen] = useState(false)
  /** 派生：桌面 3-pane 行為完全不變 */
  const railOpen = mobileState === 'drawer'
  const mobileEditor = mobileState === 'editor'

  const [newNbName, setNewNbName] = useState('')
  const [busy, setBusy] = useState(false)
  const titleTimer = useRef<number | null>(null)

  useEffect(() => { localStorage.setItem(VIEW_KEY, view) }, [view])
  useEffect(() => { localStorage.setItem(RAIL_KEY, railCollapsed ? '1' : '0') }, [railCollapsed])

  /* debounce search 300ms — 避免每隻字打一次 API */
  useEffect(() => {
    const h = window.setTimeout(() => setDebounced(search.trim()), 300)
    return () => window.clearTimeout(h)
  }, [search])

  const isUuid = UUID_RE.test(notebookId)
  const currentNotebook = useMemo(
    () => notebooks.find((n) => n.id === notebookId) || null,
    [notebooks, notebookId],
  )

  /** P0-1：權威總數。`/notebooks` 嘅 note_count 唔包含 notebook_id IS NULL 嘅未分類筆記。 */
  const [allNotesTotal, setAllNotesTotal] = useState<number | null>(null)
  const [uncatNotesTotal, setUncatNotesTotal] = useState<number | null>(null)

  /** limit=1 淨係要 `total` —— 唔好為咗個 count 拉 200 篇筆記 body（P0 performance）。 */
  const loadCounters = useCallback(async () => {
    const one = async (qs: string) => {
      try {
        const res = await apiClient.get<{ total: number }>(`/api/v1/crm/notes?limit=1${qs}`)
        return typeof res?.total === 'number' ? res.total : null
      } catch { return null }
    }
    const [all, uncat] = await Promise.all([one(''), one('&uncategorized=true')])
    if (all !== null) setAllNotesTotal(all)
    if (uncat !== null) setUncatNotesTotal(uncat)
  }, [])

  const loadNotebooks = useCallback(async () => {
    try {
      const rows = await apiClient.get<Notebook[]>('/api/v1/crm/notebooks')
      setNotebooks(Array.isArray(rows) ? rows : [])
    } catch { /* rail 顯示唔到唔應該擋住筆記 — 下面 loadNotes 自己報錯 */ }
    void loadCounters()
  }, [loadCounters])

  const loadNotes = useCallback(async (mode: 'reset' | 'more' = 'reset') => {
    /* — incremental load — */
    const off = mode === 'more' ? offsetRef.current : 0
    if (mode === 'more') setLoadingMore(true)
    else { setLoading(true); offsetRef.current = 0 }
    try {
      const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(off), sort })
      if (debounced) q.set('search', debounced)
      if (notebookId === 'uncat') q.set('uncategorized', 'true')
      else if (isUuid) q.set('notebook_id', notebookId)
      const res = await apiClient.get<{ items: Note[]; total: number }>(`/api/v1/crm/notes?${q.toString()}`)
      const items = res?.items || []
      setNotes((prev) => {
        /* 每次 list 回應都同步 versionRef —— 呢個係「最新 version」嘅唯一真實來源 */
        const applyVersions = (arr: Note[]) => {
          for (const n of arr) if (n.version != null) versionRef.current[n.id] = n.version
          return arr
        }
        if (mode !== 'more') { offsetRef.current = items.length; return applyVersions(items) }
        // 防重：如果期間有 note 被刪／還原，offset 會飄，靠 id 去重
        const seen = new Set(prev.map((n) => n.id))
        const merged = [...prev, ...items.filter((n) => !seen.has(n.id))]
        offsetRef.current = merged.length
        return applyVersions(merged)
      })
      setTotal(res?.total ?? items.length)
      setError('')
    } catch (e: any) {
      setError(errText(e) ?? 'Failed to load notes')
      if (mode !== 'more') { setNotes([]); setTotal(0); offsetRef.current = 0 }
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [notebookId, isUuid, debounced, sort])

  useEffect(() => { loadNotebooks() }, [loadNotebooks])
  useEffect(() => { loadNotes() }, [loadNotes])

  /* P0-2：有 blocking layer（drawer／create／editor／sheet）擁有畫面時，全域 Penguin
     bottom nav 要完全收埋 —— 唔可以喺 scrim 下邊仲撳得到。用 body class 交畀 CSS 做，
     唔使改 MobileNavHost（spec：extend 現有 overlay pattern，唔加第二個 manager）。 */
  useEffect(() => {
    const hide = !shouldShowGlobalNav(mobileState)
    document.body.classList.toggle('nw-nav-hidden', hide)
    return () => { if (hide) document.body.classList.remove('nw-nav-hidden') }
  }, [mobileState])

  /* P1：Android／browser Back 先關最頂層 transient layer，唔會一撳就離開 Notes。
     每個非 list 狀態加一個 history entry；popstate 時收返（唔會影響 route）。 */
  useEffect(() => {
    if (!isMobile || mobileState === 'list') return
    window.history.pushState({ nwState: mobileState }, '')
  }, [isMobile, mobileState])

  useEffect(() => {
    const onPop = () => setMobileState((s) => (s === 'list' ? s : nextStateOnBack(s, moreFromRef.current)))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  /* P0-6：離開／切走（鎖屏、切 app、關 tab）之前一定要 flush，唔好等 1.5s debounce。
     visibilitychange 喺 iOS 上係最可靠嘅一個；pagehide 補 Safari 嘅 bfcache。 */
  useEffect(() => {
    if (!selectedId) return
    /* 直接 dispatch（唔經 flushPendingSave）—— flushPendingSave 喺下面 actions 區先 declare，
       effect 早過佢，用佢會 "used before declaration"。行為同 flushPendingSave 一致。 */
    const flush = () => window.dispatchEvent(new CustomEvent('nexus-editor:flush-save'))
    const onVisibility = () => { if (document.visibilityState === 'hidden') flush() }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', flush)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', flush)
    }
  }, [selectedId])

  /* P0-6：「已儲存」唔應該長期霸住空間 —— 2.5 秒後收返 idle（saved 以外唔會變） */
  useEffect(() => {
    if (saveStatus !== 'saved') return
    const timer = window.setTimeout(() => setSaveStatus((s) => (s === 'saved' ? 'idle' : s)), 2500)
    return () => window.clearTimeout(timer)
  }, [saveStatus])

  /* P0-6：離線／返線要即時反映喺 save status */
  useEffect(() => {
    const onOffline = () => setSaveStatus('offline')
    const onOnline = () => setSaveStatus((s) => (s === 'offline' ? 'idle' : s))
    window.addEventListener('offline', onOffline)
    window.addEventListener('online', onOnline)
    return () => {
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('online', onOnline)
    }
  }, [])

  /* Stage D (T-10) — 列表滾到底自動載入下一頁（IntersectionObserver sentinel）。
     root 用 .nw-list-body（真正嘅 scroll container），rootMargin 300px 提早載。 */
  const hasMore = !loading && !error && notes.length < total
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !hasMore) return
    const root = el.closest('.nw-list-body') as Element | null
    const io = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !loadingMore) void loadNotes('more')
    }, { root, rootMargin: '300px' })
    io.observe(el)
    return () => io.disconnect()
  }, [hasMore, loadingMore, loadNotes])

  /* 換 notebook / 搜尋之後，選中嘅筆記可能唔喺列表 → 清走選擇。
     ⚠️ 2026-09-13：一定要等列表載入完（loading=false）先判斷 —— 唔係嘅話
     deep link（/notes/<id>）嘅選擇會被「notes 仲係 []」呢個假象清走（hard reload 實測中過）。 */
  useEffect(() => {
    if (loading) return
    if (selectedId && !notes.some((n) => n.id === selectedId)) {
      setSelectedId(null)
      setMobileState('list')
    }
  }, [notes, selectedId, loading])

  const selected = useMemo(() => notes.find((n) => n.id === selectedId) || null, [notes, selectedId])

  /* P0-1：用 server aggregate（包含未分類）；未載入完先 fallback notebook sum */
  const totalNotes = useMemo(
    () => deriveAllNotesTotal({ apiTotal: allNotesTotal, notebooks }),
    [allNotesTotal, notebooks],
  )

  /* ── actions ── */
  /** 2026-09-11 review T-08 / F-13：離開目前筆記之前，叫 NexusEditor 立即 flush
      pending autosave，唔好等 1.5s debounce window（mobile 撳 back／換筆記最易蝕字）。 */
  const flushPendingSave = useCallback(() => {
    if (selectedId) window.dispatchEvent(new CustomEvent('nexus-editor:flush-save'))
  }, [selectedId])

  const selectNote = (id: string) => {
    if (id !== selectedId) flushPendingSave()
    setSelectedId(id)
    if (isMobile) setMobileState((s) => openState(s, 'editor'))
  }

  /** mobile 由 editor pane 返 list：先 flush 再切 */
  const backToList = () => {
    flushPendingSave()
    setMobileState('list')
  }

  /* ── Deep link：/notes/<id>（search／command palette／AI 結果都會用呢個 url）──
     開 workspace → 攞返篇筆記 → 揀佢（手機連 editor 一齊開）。
     ⚠️ 2026-09-13 實測：一度寫成「揀完就 navigate 去 /notes/n/<notebook> 靚 URL」——
     path 一改就 match 唔同 route → 整個 page unmount→remount → selectedId 被清走，
     撳完 search 結果見到 workspace 但筆記冇揀中。所以呢度**唔改 URL**（deep link 本身
     就係 /notes/<id>，可以照 share）。筆記唔存在／冇權限 → 返回全部筆記，唔好白屏。 */
  useEffect(() => {
    if (!deepNoteId) return
    let alive = true
    ;(async () => {
      try {
        const n: any = await apiClient.get(`/api/v1/crm/notes/${deepNoteId}`)
        if (!alive) return
        setSelectedId(String(n.id))
        if (isMobile) setMobileState((s) => openState(s, 'editor'))
      } catch {
        if (alive) navigate('/notes/n/all', { replace: true })
      }
    })()
    return () => { alive = false }
  }, [deepNoteId, isMobile, navigate])

  /* ── 建立筆記：先揀範本 ──
     2026-09-11 用戶指示：範本只應該喺「建立筆記」嗰刻出現，唔應該佔 note dashboard 版面。
     原本 /notes dashboard 直接 render 範本 grid → 已移除，改為呢個 create-time 揀選器。 */
  /** `open` 已經搬去 mobileState（單一擁有者）—— tpl 只保留資料同 loading 狀態。 */
  const [tpl, setTpl] = useState<{ loading: boolean; items: any[]; busy: boolean; name: string; msg: string }>(
    { loading: false, items: [], busy: false, name: '', msg: '' },
  )

  /** 「新筆記」按鈕 → 開範本揀選器（唔再即刻開一篇空白） */
  /* 2026-09-13：改 useCallback —— 下面 ?new=1 嘅 effect 要用佢做 dep（Notes 首頁
     「新增筆記」掣會帶 ?new=1 入嚟，直接開建立筆記 sheet）。 */
  const openCreate = useCallback(async () => {
    if (busy) return
    flushPendingSave()
    setMobileState((s) => openState(s, 'create'))
    setTpl((s) => ({ ...s, msg: '', loading: s.items.length === 0 }))
    if (tpl.items.length) return
    try {
      const rows = await apiClient.get<any[]>('/api/v1/crm/note-templates')
      setTpl((s) => ({ ...s, loading: false, items: Array.isArray(rows) ? rows : [] }))
    } catch { setTpl((s) => ({ ...s, loading: false })) }
  }, [busy, flushPendingSave, tpl.items.length])

  /* 2026-09-13（用戶指示）：「新增筆記」由 Notes 首頁 ?new=1 入嚟 → 直接開建立 sheet，
     唔使用戶再撳一次「+」。開完即刻清走 query，返上一頁唔會又彈。 */
  const [sp, setSp] = useSearchParams()
  useEffect(() => {
    if (sp.get('new') !== '1') return
    // openCreate 有 `if (busy) return` guard；首次載入 busy=true 會靜靜食咗個請求
    // （實測：URL 清走咗但 sheet 冇開）→ 等載入完再開，唔清 query 住。
    if (busy) return
    void openCreate()
    const next = new URLSearchParams(sp)
    next.delete('new')
    setSp(next, { replace: true })
  }, [sp, setSp, openCreate, busy])

  /** 空白／範本兩條路都收口喺呢度：確保新 note 入目前 notebook 並且即刻選中 */
  const createFromTemplate = async (templateId: string | null) => {
    if (busy || tpl.busy) return
    setTpl((s) => ({ ...s, busy: true, msg: '' }))
    try {
      if (!templateId) {
        setTpl((s) => ({ ...s, busy: false }))
        setMobileState('list')
        await createNote()
        return
      }
      const body: Record<string, unknown> = { template_id: templateId }
      if (isUuid) body.notebook_id = notebookId
      const created: any = await apiClient.post('/api/v1/crm/notes/from-template', body)
      setTpl((s) => ({ ...s, busy: false }))
      setMobileState('list')
      await Promise.all([loadNotes(), loadNotebooks()])
      if (created?.id) selectNote(created.id)
    } catch (e: any) {
      setTpl((s) => ({ ...s, busy: false, msg: errText(e) ?? '建立失敗' }))
    }
  }

  /** 喺 create 情境建立自訂範本（功能保留，但唔再放喺 dashboard） */
  const createTplHere = async () => {
    const name = tpl.name.trim()
    if (!name || tpl.busy) return
    setTpl((s) => ({ ...s, busy: true, msg: '' }))
    try {
      await apiClient.post('/api/v1/crm/note-templates', {
        name, category: 'custom',
        blocks_json: {
          type: 'doc',
          content: [
            { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: name }] },
            { type: 'paragraph' },
          ],
        },
      })
      const rows = await apiClient.get<any[]>('/api/v1/crm/note-templates')
      setTpl((s) => ({ ...s, busy: false, name: '', items: Array.isArray(rows) ? rows : s.items }))
    } catch (e: any) {
      setTpl((s) => ({ ...s, busy: false, msg: errText(e) ?? '建立失敗' }))
    }
  }

  const createNote = async () => {
    if (busy) return
    setBusy(true)
    try {
      const body: Record<string, unknown> = { title: '', content: '' }
      if (isUuid) body.notebook_id = notebookId
      const created = await apiClient.post<Note>('/api/v1/crm/notes', body)
      await Promise.all([loadNotes(), loadNotebooks()])
      if (created?.id) selectNote(created.id)
    } catch (e: any) {
      setError(errText(e) ?? 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  const patchNote = async (id: string, patch: Partial<Note>): Promise<boolean> => {
    /* 所有 note 細項修改（標題／釘選／notebook）都經呢度。
       ⚠️ 一定要帶 expected_version：server 每次 PATCH 都 version + 1，
       如果呢度唔帶、而 autosave 帶，就會出現「改完標題再打字 → 假 409 衝突」
       （本地以為仲係 v1，server 已經 v2）。成功後亦一定要收返新 version。 */
    const expected = versionRef.current[id]
    setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } as Note : n)))
    try {
      const res: any = await apiClient.patch(`/api/v1/crm/notes/${id}`, {
        ...patch,
        ...(expected != null ? { expected_version: expected } : {}),
      })
      if (res?.version != null) {
        versionRef.current[id] = res.version
        setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, version: res.version } : n)))
      }
      return true
    } catch (e: any) {
      /* 失敗（含 409）：拉返 server 真實狀態，唔留假 UI。409 唔喺呢度出 banner ——
         banner 專屬「編輯器內容儲存」路徑（saveContent），因為只有嗰度有未存嘅文字。 */
      setError(e?.status === 409 ? '' : (errText(e) ?? 'Update failed'))
      await loadNotes()
      return false
    }
  }

  const togglePin = async (n: Note, e?: React.MouseEvent) => {
    e?.stopPropagation()
    await patchNote(n.id, { pinned: !n.pinned })
    await loadNotes() // 釘選會改排序（釘選浮頂）
  }

  const saveContent = async (html: string) => {
    if (!selected) return
    const id = selected.id
    pendingHtml.current = html
    const generation = saveSeqRef.current.next(id)
    setSaveStatus('saving')
    setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, content: html } : n)))
    try {
      const res: any = await apiClient.patch(`/api/v1/crm/notes/${id}`, {
        content: html,
        // Stage C (T-02) 樂觀鎖：由 versionRef 拎**最新** version（呢個回呼可能係舊
        // render 嘅 closure，讀 state 會過期 → 假 409）。另一個 tab／裝置改過才 409。
        ...(versionRef.current[id] != null ? { expected_version: versionRef.current[id] } : {}),
      })
      /* P0-6：已經有更新嘅 request 飛咗出去 → 呢個回應係 stale，唔可以寫 version／UI。 */
      if (!saveSeqRef.current.isLatest(id, generation)) return
      if (res?.version != null) {
        versionRef.current[id] = res.version
        setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, version: res.version } : n)))
      }
      setSaveError('')
      setConflict(null)
      setSaveStatus(saveStatusAfter({ ok: true, offline: !navigator.onLine }))
    } catch (e: any) {
      if (!saveSeqRef.current.isLatest(id, generation)) return
      if (e?.status === 409) {
        /* 版本衝突：retry 冇意義（只會再 409），所以**唔 rethrow**（唔好觸發
           NexusEditor 嘅 backoff retry），改為出 banner 俾用戶決定。 */
        setConflict({ current: e?.detail?.current_version ?? 0 })
        setSaveStatus('error')
        return
      }
      setSaveError(t('notes.saveFailed', { defaultValue: '儲存失敗 — 內容未寫入資料庫' }))
      setSaveStatus(saveStatusAfter({ ok: false, offline: !navigator.onLine }))
      /* ⚠️ 必須 rethrow：NexusEditor 嘅 autosave retry / saveState='error' 係靠 onSave
         reject 嚟觸發。原本 swallow 咗 error → 編輯器以為存成功（review T-01 嘅 retry
         建議如果照抄而唔 rethrow，係永遠唔會 retry 嘅）。 */
      throw e
    }
  }

  /** Stage C (T-02) 衝突處理：放棄我嘅改動，載入伺服器最新版 */
  const resolveConflictUseServer = async () => {
    setConflict(null)
    setSaveError('')
    await loadNotes()
    setEdKey((k) => k + 1) // 強制 remount，NexusEditor 會重新讀 content
  }

  /** Stage C (T-02) 衝突處理：保留我嘅版本（用最新 version 覆蓋） */
  const resolveConflictKeepMine = async () => {
    const html = pendingHtml.current
    if (!selected || html == null) return
    const id = selected.id
    try {
      const fresh: any = await apiClient.get(`/api/v1/crm/notes/${id}`)
      const res: any = await apiClient.patch(`/api/v1/crm/notes/${id}`, {
        content: html,
        expected_version: fresh?.version,
      })
      setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, version: res?.version ?? n.version, content: html } : n)))
      setConflict(null)
      setSaveError('')
    } catch (e: any) { setSaveError(errText(e) ?? 'Save failed') }
  }

  /* P1-⑪：手機 editor 嘅 ⋯ 入嚟（記住邊度開，關咗返原位） */
  const openMore = () => {
    moreFromRef.current = mobileState === 'editor' ? 'editor' : 'list'
    setMobileState((s) => openState(s, 'more'))
  }

  /** Stage C (T-03)：開 History drawer，拉 revision 清單 */
  const openHistory = async () => {
    if (!selected) return
    setHistory({ open: true, loading: true, items: [] })
    try {
      const res: any = await apiClient.get(`/api/v1/crm/notes/${selected.id}/revisions`)
      setHistory({ open: true, loading: false, items: res?.items || [] })
    } catch { setHistory({ open: true, loading: false, items: [] }) }
  }

  /** Stage C (T-03)：還原到某個版本（還原動作本身都會留底，可以再還原返轉頭） */
  const restoreRevision = async (revId: string) => {
    if (!selected) return
    try {
      await apiClient.post(`/api/v1/crm/notes/${selected.id}/revisions/${revId}/restore`, {})
      setHistory((h) => ({ ...h, open: false }))
      await loadNotes()
      setEdKey((k) => k + 1)
    } catch (e: any) { setError(errText(e) ?? 'Restore failed') }
  }

  /** Stage B (T-04)：撤銷刪除 */
  const undoDelete = async () => {
    if (!undo) return
    const { id, timer } = undo
    clearTimeout(timer)
    setUndo(null)
    try {
      await apiClient.post(`/api/v1/crm/notes/${id}/restore`, {})
      await Promise.all([loadNotes(), loadNotebooks()])
    } catch (e: any) { setError(errText(e) ?? 'Restore failed') }
  }

  const onTitleChange = (val: string) => {
    if (!selected) return
    const id = selected.id
    setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, title: val } : n)))
    if (titleTimer.current) window.clearTimeout(titleTimer.current)
    titleTimer.current = window.setTimeout(() => {
      // 經 patchNote → 會帶 expected_version + 收返新 version（見 patchNote 註解）
      void patchNote(id, { title: val })
    }, 600)
  }

  const deleteNote = async (n: Note) => {
    /* Stage B (T-04)：改為 soft delete + 6 秒撤銷 bar。
       唔再 window.confirm —— 誤刪可以一撳還原，加 confirm 只係多一層阻礙
       （Gmail / Notion 都係呢個做法），而且 confirm 對 mobile 體驗特別差。 */
    if (n.id === selectedId) flushPendingSave()
    if (undo?.timer) clearTimeout(undo.timer)

    // 樂觀更新：即刻由清單移走，唔等 server
    setNotes((prev) => prev.filter((x) => x.id !== n.id))
    setTotal((v) => Math.max(0, v - 1))
    const wasSelected = n.id === selectedId
    if (wasSelected) { setSelectedId(null); setMobileState('list') }
    setConflict(null)

    const timer = setTimeout(() => {
      setUndo((u) => (u && u.id === n.id ? null : u))
      void loadNotes()
    }, 6000)
    setUndo({ id: n.id, title: n.title || (t('notes.untitled', { defaultValue: '未命名筆記' }) as string), timer })

    try {
      await apiClient.delete(`/api/v1/crm/notes/${n.id}`)
      await loadNotebooks()
    } catch (e: any) {
      // 失敗：即刻還原畫面（唔好呃用戶以為刪咗）
      clearTimeout(timer)
      setUndo(null)
      setError(errText(e) ?? 'Delete failed')
      await loadNotes()
    }
  }

  const unlinkRecord = async (linkId: string) => {
    if (!selected) return
    try {
      await apiClient.delete(`/api/v1/crm/notes/${selected.id}/links/${linkId}`)
      await loadNotes()
    } catch { /* 唔阻住編輯 */ }
  }

  const createNotebook = async () => {
    const name = newNbName.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      const nb = await apiClient.post<Notebook>('/api/v1/crm/notebooks', { name, color: 'blue' })
      setNewNbName('')
      await loadNotebooks()
      if (nb?.id) navigate(`/notes/n/${nb.id}`)
    } catch (e: any) { setError(errText(e) ?? 'Create failed') }
    finally { setBusy(false) }
  }

  const goRail = (target: string) => {
    flushPendingSave()
    navigate(`/notes/n/${target}`)
    setMobileState('list')
    setSelectedId(null)
  }

  const fmt = (iso: string) => {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const diff = Date.now() - d.getTime()
    const min = Math.floor(diff / 60000)
    if (min < 1) return t('notes.justNow', { defaultValue: '剛剛' })
    if (min < 60) return t('notes.minutesAgo', { defaultValue: '{{n}} 分鐘前', n: min })
    const hr = Math.floor(min / 60)
    if (hr < 24) return t('notes.hoursAgo', { defaultValue: '{{n}} 小時前', n: hr })
    const sameYear = d.getFullYear() === new Date().getFullYear()
    return d.toLocaleDateString(undefined, sameYear ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' })
  }

  const railTitle = notebookId === 'all'
    ? t('notes.allNotes', { defaultValue: '全部筆記' })
    : notebookId === 'uncat'
      ? t('notes.uncategorized', { defaultValue: '未分類' })
      : (currentNotebook?.name || t('notes.notebooks', { defaultValue: 'Notebook' }))

  const toggleRail = () => {
    if (isMobile) setMobileState((s) => (s === 'drawer' ? 'list' : openState(s, 'drawer')))
    else setRailCollapsed((v) => !v)
  }

  /* ── rail ── */
  const rail = (
    <aside className={`nw-rail${railCollapsed ? ' is-collapsed' : ''}${railOpen ? ' is-open' : ''}`}>
      <div className="nw-rail-head">
        <span className="nw-rail-title">{t('notes.notebooks', { defaultValue: 'Notebook' })}</span>
        <button className="nw-icon-btn" onClick={toggleRail}
          title={railCollapsed ? t('notes.expandRail', { defaultValue: '展開側欄' }) : t('notes.collapseRail', { defaultValue: '收起側欄' })}
          aria-label={railCollapsed ? t('notes.expandRail', { defaultValue: '展開側欄' }) : t('notes.collapseRail', { defaultValue: '收起側欄' })}>
          <SvcIcon name={(!isMobile && railCollapsed) ? 'chevron-right' : 'chevron-left'} size={18} />
        </button>
      </div>

      <nav className="nw-rail-nav">
        <button className={`nw-rail-item${notebookId === 'all' ? ' is-active' : ''}`} onClick={() => goRail('all')}
          title={t('notes.allNotes', { defaultValue: '全部筆記' })}>
          <span className="nw-rail-dot" style={{ background: 'var(--color-text-faint)' }} />
          <span className="nw-rail-name">{t('notes.allNotes', { defaultValue: '全部筆記' })}</span>
          <span className="nw-rail-count">{totalNotes}</span>
        </button>

        <button className={`nw-rail-item${notebookId === 'uncat' ? ' is-active' : ''}`} onClick={() => goRail('uncat')}
          title={t('notes.uncategorized', { defaultValue: '未分類' })}>
          <span className="nw-rail-dot" style={{ background: 'var(--color-text-faint)' }} />
          <span className="nw-rail-name">{t('notes.uncategorized', { defaultValue: '未分類' })}</span>
          {uncatNotesTotal !== null && <span className="nw-rail-count">{uncatNotesTotal}</span>}
        </button>

        {notebooks.map((nb) => (
          <button key={nb.id} className={`nw-rail-item${notebookId === nb.id ? ' is-active' : ''}`}
            onClick={() => goRail(nb.id)} title={nb.name}>
            <span className="nw-rail-dot" style={{ background: `var(--color-${nb.color}, var(--color-blue))` }} />
            <span className="nw-rail-name">{nb.name}</span>
            <span className="nw-rail-count">{notebookCountOf(nb)}</span>
          </button>
        ))}
      </nav>

      <div className="nw-rail-foot">
        <div className="nw-toolbar" style={{ marginTop: 0 }}>
          <div className="nw-search" style={{ height: 34 }}>
            <input value={newNbName} maxLength={120} placeholder={t('notes.newNotebook', { defaultValue: '新增 Notebook' }) as string}
              onChange={(e) => setNewNbName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') createNotebook() }} />
          </div>
          <button className="nw-icon-btn" onClick={createNotebook} disabled={busy || !newNbName.trim()}
            title={t('notes.createNotebook', { defaultValue: '建立 Notebook' })} aria-label={t('notes.createNotebook', { defaultValue: '建立 Notebook' })}>
            <SvcIcon name="plus" size={17} />
          </button>
        </div>
      </div>
    </aside>
  )

  /* ── middle list ── */
  const list = (
    <section className="nw-list">
      <div className="nw-list-head">
        <div className="nw-list-title">
          {isMobile && (
            <button className="nw-icon-btn nw-back-btn" onClick={() => setMobileState((s) => openState(s, 'drawer'))}
              title={t('notes.openNotebooks', { defaultValue: '開啟 Notebook' }) as string}
              aria-label={t('notes.openNotebooks', { defaultValue: '開啟 Notebook' }) as string}>
              <SvcIcon name="menu" size={18} />
            </button>
          )}
          <span>{railTitle}</span>
        </div>
        <div className="nw-list-sub">
          {loading ? t('notes.loading', { defaultValue: '載入中…' }) : t('notes.noteCount', { defaultValue: '{{n}} 篇', n: total })}
        </div>

        <div className="nw-toolbar">
          <div className="nw-search">
            <SvcIcon name="search" size={16} />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={t('notes.searchPlaceholder', { defaultValue: '搜尋筆記…' }) as string} />
            {search && (
              <button className="nw-icon-btn" style={{ width: 22, height: 22 }} onClick={() => setSearch('')}
                aria-label={t('notes.clearSearch', { defaultValue: '清除搜尋' }) as string}>
                <SvcIcon name="x" size={14} />
              </button>
            )}
          </div>
          <button className="nw-new-btn" onClick={openCreate} disabled={busy} title={t('notes.newNote', { defaultValue: '新筆記' })}>
            <SvcIcon name="plus" size={16} /><span>{t('notes.newNote', { defaultValue: '新筆記' })}</span>
          </button>
          {/* P1（mobile Row2 = 全闊 search + 尾隨控制）：排序由下一行搬上嚟 —— mobile 專用，
              桌面靠 notes-mobile-layers.css 嘅 @media(min-width:901px) 收埋，桌面繼續用 native select。 */}
          <button type="button" className="nw-meta-btn"
            onClick={() => setMobileState((s) => openState(s, 'sort'))}
            aria-haspopup="dialog" aria-expanded={mobileState === 'sort'}
            title={t('notes.sortBy', { defaultValue: '排序' }) as string}>
            {t(SORTS.find((x) => x.value === sort)?.key || 'notes.sortBy', { defaultValue: '排序' })}
          </button>
        </div>

        {/* P1：桌面專用 row（排序 select + 檢視切換）。mobile 由 CSS 全行收埋 → 筆記列表
            緊接 search 出現，唔再有一行永久 white-row。 */}
        <div className="nw-toolbar nw-toolbar-meta">
          <select className="nw-meta-select nw-sort-select" value={sort} onChange={(e) => setSort(e.target.value)}
            title={t('notes.sortBy', { defaultValue: '排序' }) as string} aria-label={t('notes.sortBy', { defaultValue: '排序' }) as string}>
            {SORTS.map((s) => <option key={s.value} value={s.value}>{t(s.key, { defaultValue: s.value })}</option>)}
          </select>
          <span className="nw-spacer" />
          <div className="nw-view-switch" role="group" aria-label={t('notes.viewMode', { defaultValue: '檢視' }) as string}>
            {([['list', 'list-view'], ['card', 'card-view'], ['compact', 'table-view']] as const).map(([mode, icon]) => (
              <button key={mode} className={`nw-icon-btn${view === mode ? ' is-active' : ''}`} onClick={() => setView(mode)}
                aria-pressed={view === mode} title={t(`notes.view_${mode}`, { defaultValue: mode })} aria-label={t(`notes.view_${mode}`, { defaultValue: mode }) as string}>
                <SvcIcon name={icon} size={16} />
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={`nw-list-body ${view === 'card' ? 'is-cards' : view === 'compact' ? 'is-compact' : 'is-rows'}`}>
        {error ? (
          <p className="nw-empty" style={{ color: 'var(--color-error)' }}>{error}</p>
        ) : loading ? (
          /* review T-06 / F-03：原本 loading 只出「載入中…」文字，跳 notebook／搜尋時
             閃一下空白。改用 5 條 skeleton row（shimmer）＋ 螢幕閱讀器播報。 */
          <div className="nw-skeleton-list" aria-busy="true">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="nw-skeleton-row">
                <span className="nw-skeleton nw-skeleton-line w70" />
                <span className="nw-skeleton nw-skeleton-line w95" />
                <span className="nw-skeleton nw-skeleton-line w40" />
              </div>
            ))}
            <span className="sr-only" aria-live="polite">{t('notes.loading', { defaultValue: '載入中…' })}</span>
          </div>
        ) : notes.length === 0 ? (
          /* P1：可操作嘅 empty state —— 圖示 + 標題 + 解釋 + 一個明確 CTA。
             兩種情況唔可以撈埋：搜尋冇結果（CTA = 清除搜尋）／完全未有筆記（CTA = 新筆記）。 */
          <div className="nw-empty-state" role="status">
            <SvcIcon name={debounced ? 'search' : 'list-view'} size={30} />
            <strong>{debounced
              ? t('notes.noResultsTitle', { defaultValue: '冇符合嘅筆記' })
              : t('notes.emptyListTitle', { defaultValue: '未有筆記' })}</strong>
            <p>{debounced
              ? t('notes.noResults', { defaultValue: '試下換個關鍵字，或者清除搜尋睇全部。' })
              : t('notes.emptyList', { defaultValue: '撳下面「新筆記」開始寫第一篇。' })}</p>
            {debounced ? (
              <button className="nw-btn-sm" onClick={() => setSearch('')}>
                {t('notes.clearSearch', { defaultValue: '清除搜尋' })}
              </button>
            ) : (
              <button className="nw-btn-sm" onClick={openCreate} disabled={busy}>
                {t('notes.newNote', { defaultValue: '新筆記' })}
              </button>
            )}
          </div>
        ) : (
          <>
            {notes.map((n) => {
            const snippet = plain(n.content)
            return (
              /* a11y（2026-09-13）：原本 row = role="button" + tabindex 包住 .nw-pin-btn
                 → axe serious:nested-interactive（互動控件嵌套，讀屏會亂）。改成 row 做純容器，
                 .nw-note-main 做真正嘅 <button>（原生 Enter／Space），pin 掣做 sibling。 */
              <div key={n.id} data-note-id={n.id}
                className={`nw-note${n.id === selectedId ? ' is-active' : ''}`}>
                <button type="button" className="nw-note-main"
                  aria-current={n.id === selectedId ? 'true' : undefined}
                  onClick={() => selectNote(n.id)}>
                  <div className="nw-note-name">
                    <span>{n.title?.trim() || t('notes.untitled', { defaultValue: '未命名筆記' })}</span>
                  </div>
                  {snippet && <div className="nw-note-snippet">{snippet}</div>}
                  <div className="nw-note-meta">
                    <span>{fmt(n.updated_at)}</span>
                    {!!(n.note_links?.length) && (
                      <span>· <SvcIcon name="link" size={11} /> {n.note_links!.length}</span>
                    )}
                  </div>
                </button>
                <button className={`nw-pin-btn${n.pinned ? ' is-pinned' : ''}`} onClick={(e) => togglePin(n, e)}
                  aria-pressed={n.pinned}
                  title={n.pinned ? t('notes.unpin', { defaultValue: '取消釘選' }) : t('notes.pin', { defaultValue: '釘選' })}
                  aria-label={n.pinned ? t('notes.unpin', { defaultValue: '取消釘選' }) : t('notes.pin', { defaultValue: '釘選' })}>
                  <SvcIcon name="pin" size={15} />
                </button>
              </div>
            )
            })}
            {/* Stage D (T-10)：滾到底自動載入；亦保留手動按鈕（鍵盤／無 scroll 情況） */}
            {hasMore && (
              <div ref={sentinelRef} className="nw-load-more">
                {loadingMore ? (
                  <span className="nw-load-more-txt" role="status">{t('notes.loadingMore', { defaultValue: '載入更多…' })}</span>
                ) : (
                  <button className="nw-btn-sm" onClick={() => void loadNotes('more')}>
                    {t('notes.loadMore', { defaultValue: '載入更多' })}
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )

  /* ── right editor（T1.4） ── */
  const editor = (
    <section className="nw-editor">
      {loading && !selected ? (
        /* review T-06 / F-03：editor pane 載入中都出 skeleton（title bar + 4 行） */
        <div className="nw-skeleton-ed" aria-busy="true">
          <span className="nw-skeleton nw-skeleton-title" />
          {['w95', 'w70', 'w95', 'w40'].map((w, i) => (
            <span key={i} className={`nw-skeleton nw-skeleton-line ${w}`} />
          ))}
          <span className="sr-only" aria-live="polite">{t('notes.loading', { defaultValue: '載入中…' })}</span>
        </div>
      ) : !selected ? (
        <div className="nw-ed-empty">
          <SvcIcon name="book-open" size={30} />
          <div>{t('notes.selectHint', { defaultValue: '揀一篇筆記，或者撳「新筆記」開始寫。' })}</div>
          <button className="nw-new-btn" onClick={openCreate} disabled={busy}>
            <SvcIcon name="plus" size={16} /><span>{t('notes.newNote', { defaultValue: '新筆記' })}</span>
          </button>
        </div>
      ) : (
        <>
          <div className="nw-ed-head">
            <input className="nw-title-input" value={selected.title || ''} maxLength={200}
              placeholder={t('notes.untitled', { defaultValue: '未命名筆記' }) as string}
              onChange={(e) => onTitleChange(e.target.value)} />

            <div className="nw-meta-row">
              {isMobile && (
                <button className="nw-icon-btn nw-back-btn" onClick={backToList} aria-label={t('notes.backToList', { defaultValue: '返回列表' }) as string}>
                  <SvcIcon name="arrow-left" size={18} />
                </button>
              )}
              <span>{fmt(selected.updated_at)}</span>
              {/* P0-6：Saving／Saved／Offline changes／Save failed。
                  polite live region：讀屏會播報但唔搶 focus。 */}
              {saveStatus !== 'idle' && (
                <span className={`nw-save-status is-${saveStatus}`} role="status" aria-live="polite">
                  {t(SAVE_STATUS_KEY[saveStatus], { defaultValue: SAVE_STATUS_FALLBACK[saveStatus] })}
                </span>
              )}
              {/* Desktop：notebook select + 釘選 + 全頁 + 版本 + 刪除，全部照舊 */}
              {!isMobile && (
                <>
                  <select className="nw-meta-select" value={selected.notebook_id || ''}
                    onChange={(e) => patchNote(selected.id, { notebook_id: e.target.value || null })}
                    title={t('notes.notebooks', { defaultValue: 'Notebook' }) as string} aria-label={t('notes.notebooks', { defaultValue: 'Notebook' }) as string}>
                    <option value="">{t('notes.uncategorized', { defaultValue: '未分類' })}</option>
                    {notebooks.map((nb) => <option key={nb.id} value={nb.id}>{nb.name}</option>)}
                  </select>
                  <span className="nw-spacer" />
                  <button className={`nw-icon-btn${selected.pinned ? ' is-active' : ''}`} onClick={(e) => togglePin(selected, e)}
                    aria-pressed={selected.pinned}
                    title={selected.pinned ? t('notes.unpin', { defaultValue: '取消釘選' }) : t('notes.pin', { defaultValue: '釘選' })}
                    aria-label={selected.pinned ? t('notes.unpin', { defaultValue: '取消釘選' }) : t('notes.pin', { defaultValue: '釘選' })}>
                    <SvcIcon name="pin" size={16} />
                  </button>
                  <button className="nw-icon-btn" onClick={() => setZen((v) => !v)} aria-pressed={zen}
                    title={zen ? t('notes.exitZen', { defaultValue: '還原 3-pane' }) : t('notes.zen', { defaultValue: '全頁' })}
                    aria-label={zen ? t('notes.exitZen', { defaultValue: '還原 3-pane' }) : t('notes.zen', { defaultValue: '全頁' })}>
                    {zen ? <Minimize2 size={16} strokeWidth={1.75} /> : <Maximize2 size={16} strokeWidth={1.75} />}
                  </button>
                  <button className="nw-icon-btn" onClick={openHistory}
                    title={t('notes.history', { defaultValue: '版本紀錄' })} aria-label={t('notes.history', { defaultValue: '版本紀錄' }) as string}>
                    <History size={16} strokeWidth={1.75} />
                  </button>
                  <button className="nw-icon-btn is-danger" onClick={() => deleteNote(selected)}
                    title={t('common.delete', { defaultValue: '刪除' })} aria-label={t('common.delete', { defaultValue: '刪除' })}>
                    <SvcIcon name="trash-2" size={16} />
                  </button>
                </>
              )}
              {/* Mobile（P1-⑪）：頂欄只留 ⋯ —— native select 唔再出現喺手機（同 P0-3 排序同一原則），
                  pin／移動／版本／刪除全部入 sheet（spec：Delete 唔做 primary，唔會一撳就中）。 */}
              {isMobile && (
                <>
                  <span className="nw-spacer" />
                  <button className="nw-icon-btn" onClick={openMore}
                    aria-haspopup="dialog" aria-expanded={mobileState === 'more'}
                    title={t('notes.more', { defaultValue: '更多' })} aria-label={t('notes.more', { defaultValue: '更多' }) as string}>
                    <MoreHorizontal size={18} strokeWidth={1.75} />
                  </button>
                </>
              )}
            </div>

            {saveError && (
              <div className="nw-save-error" role="alert">
                <SvcIcon name="alert-triangle" size={14} />
                <span>{saveError}</span>
                <button className="nw-icon-btn" style={{ width: 22, height: 22 }} onClick={() => setSaveError('')} aria-label={t('common.close', { defaultValue: '關閉' }) as string}>
                  <SvcIcon name="x" size={13} />
                </button>
              </div>
            )}

            {conflict && (
              <div className="nw-conflict" role="alert">
                <SvcIcon name="alert-triangle" size={14} />
                <span>{t('notes.conflict', { defaultValue: '呢篇筆記已經喺第 {{v}} 版被另一處改過，你嘅改動未儲存。', v: conflict.current })}</span>
                <button className="nw-btn-sm" onClick={resolveConflictKeepMine}>{t('notes.keepMine', { defaultValue: '保留我嘅版本' })}</button>
                <button className="nw-btn-sm is-ghost" onClick={resolveConflictUseServer}>{t('notes.loadLatest', { defaultValue: '載入最新' })}</button>
              </div>
            )}

            {!!(selected.note_links?.length) && (
              <div className="nw-chips">
                {selected.note_links!.map((lk) => (
                  <span key={lk.id} className="nw-chip">
                    {lk.label || lk.entity_type}
                    <button onClick={() => unlinkRecord(lk.id)} title={t('notes.unlink', { defaultValue: '解除關聯' })}
                      aria-label={t('notes.unlink', { defaultValue: '解除關聯' }) as string}>✕</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="nw-ed-body">
            <NexusEditor
              key={`${selected.id}:${edKey}`}
              content={selected.content || ''}
              onSave={saveContent}
              minHeight={320}
              entityContext={{ type: 'note', id: selected.id, name: selected.title || undefined }}
            />
          </div>
        </>
      )}
    </section>
  )

  return (
    <div className={`nw-page${railOpen ? ' is-rail-open' : ''}${zen ? ' is-zen' : ''}${mobileEditor ? ' is-mobile-editor' : ''}`}
      data-notes-state={mobileState}>
      {rail}
      <button className="nw-scrim" aria-label={t('notes.collapseRail', { defaultValue: '收起側欄' }) as string} onClick={() => setMobileState('list')} />
      {list}
      {editor}

      {/* Stage B (T-04)：撤銷刪除 bar（soft delete 之後 6 秒內可還原） */}
      {undo && (
        <div className="nw-undo-bar" role="status">
          <span>{t('notes.deleted', { defaultValue: '已刪除「{{t}}」', t: undo.title })}</span>
          <button className="nw-undo-btn" onClick={undoDelete}>
            <RotateCcw size={14} strokeWidth={1.75} />
            {t('notes.undo', { defaultValue: '撤銷' })}
          </button>
        </div>
      )}

      {/* 建立筆記：範本揀選器（只在 create 嗰刻出現） */}
      {mobileState === 'sort' && (
        <SortSheet value={sort} options={SORTS}
          onSelect={(v) => { setSort(v); setMobileState('list') }}
          onClose={() => setMobileState('list')} />
      )}

      {/* P1-⑪：手機 editor 嘅「更多」sheet（pin／移動 notebook／版本紀錄／刪除） */}
      {mobileState === 'more' && selected && (
        <EditorMoreSheet
          pinned={!!selected.pinned}
          notebookId={selected.notebook_id}
          notebooks={notebooks.map((nb) => ({ id: nb.id, name: nb.name }))}
          onTogglePin={() => { void togglePin(selected) }}
          onMove={(nbId) => { void patchNote(selected.id, { notebook_id: nbId }) }}
          onHistory={() => { void openHistory() }}
          onDelete={() => { void deleteNote(selected) }}
          onClose={() => setMobileState((s) => nextStateOnBack(s, moreFromRef.current))}
        />
      )}

      {mobileState === 'create' && (
        <>
          <button className="nw-drawer-scrim" aria-label={t('common.close', { defaultValue: '關閉' }) as string}
            onClick={() => setMobileState('list')} />
          <div className="nw-tpl-sheet" role="dialog" aria-modal="true"
            aria-label={t('notes.chooseTemplate', { defaultValue: '建立筆記' }) as string}>
            <div className="nw-tpl-head">
              <strong>{t('notes.chooseTemplate', { defaultValue: '建立筆記' })}</strong>
              <button className="nw-icon-btn" onClick={() => setMobileState('list')}
                aria-label={t('common.close', { defaultValue: '關閉' }) as string}>
                <SvcIcon name="x" size={15} />
              </button>
            </div>
            {tpl.loading ? (
              <div className="nw-skeleton-list" aria-busy="true">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="nw-skeleton-row"><span className="nw-skeleton nw-skeleton-line w70" /></div>
                ))}
              </div>
            ) : (
              <>
                <button className="nw-tpl-blank" onClick={() => createFromTemplate(null)} disabled={tpl.busy}>
                  <SvcIcon name="plus" size={15} />
                  <span>{t('notes.blankNote', { defaultValue: '空白筆記' })}</span>
                </button>
                {tpl.items.length > 0 && (
                  <ul className="nw-tpl-list">
                    {tpl.items.map((x: any) => (
                      <li key={x.id}>
                        <button className="nw-tpl-item" onClick={() => createFromTemplate(x.id)} disabled={tpl.busy}>
                          <span className="nw-tpl-name">{x.name}</span>
                          <span className="nw-tpl-cat">
                            {x.is_system ? t('notes.builtin', { defaultValue: '內建' }) : t('notes.custom', { defaultValue: '自訂' })}
                            {x.category ? ` · ${x.category}` : ''}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="nw-tpl-new">
                  <input className="nw-tpl-input" maxLength={120} value={tpl.name}
                    placeholder={t('notes.templateName', { defaultValue: '自訂範本名稱' }) as string}
                    onChange={(e) => setTpl((s) => ({ ...s, name: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === 'Enter') void createTplHere() }} />
                  <button className="nw-btn-sm" onClick={createTplHere} disabled={tpl.busy || !tpl.name.trim()}>
                    {t('notes.createTemplate', { defaultValue: '建立自訂範本' })}
                  </button>
                </div>
                {tpl.msg && <p className="nw-tpl-msg">{tpl.msg}</p>}
              </>
            )}
          </div>
        </>
      )}

      {/* Stage C (T-03)：版本紀錄 drawer */}
      {history.open && (
        <>
          <button className="nw-drawer-scrim" aria-label={t('common.close', { defaultValue: '關閉' }) as string}
            onClick={() => setHistory((h) => ({ ...h, open: false }))} />
          <aside className="nw-history" role="dialog" aria-modal="false"
            aria-label={t('notes.history', { defaultValue: '版本紀錄' }) as string}>
            <div className="nw-history-head">
              <strong>{t('notes.history', { defaultValue: '版本紀錄' })}</strong>
              <button className="nw-icon-btn" onClick={() => setHistory((h) => ({ ...h, open: false }))}
                aria-label={t('common.close', { defaultValue: '關閉' }) as string}>
                <SvcIcon name="x" size={15} />
              </button>
            </div>
            {history.loading ? (
              <div className="nw-skeleton-list" aria-busy="true">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="nw-skeleton-row">
                    <span className="nw-skeleton nw-skeleton-line w70" />
                    <span className="nw-skeleton nw-skeleton-line w95" />
                  </div>
                ))}
              </div>
            ) : history.items.length === 0 ? (
              <p className="nw-empty">{t('notes.noHistory', { defaultValue: '仲未有舊版本。改完內容過幾分鐘就會有。' })}</p>
            ) : (
              <ul className="nw-history-list">
                {history.items.map((r: any) => (
                  <li key={r.id} className="nw-history-item">
                    <div className="nw-history-meta">
                      <span className="nw-history-v">v{r.version}</span>
                      <span className="nw-history-time">{new Date(r.created_at).toLocaleString()}</span>
                    </div>
                    <div className="nw-history-title">{r.title || t('notes.untitled', { defaultValue: '未命名筆記' })}</div>
                    <div className="nw-history-prev">{r.preview}</div>
                    <button className="nw-btn-sm" onClick={() => restoreRevision(r.id)}>
                      {t('notes.restore', { defaultValue: '還原' })}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </>
      )}
    </div>
  )
}

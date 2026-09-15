import { useState, useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Table from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Highlight from '@tiptap/extension-highlight'
import Color from '@tiptap/extension-color'
import TextStyle from '@tiptap/extension-text-style'
/* 2026-09-14：StarterKit v2 唔含 Underline（用戶報「editor 冇 underline」）→ 獨立 extension */
import Underline from '@tiptap/extension-underline'
import CharacterCount from '@tiptap/extension-character-count'
import Dropcursor from '@tiptap/extension-dropcursor'
import { Bold, Italic, Underline as UnderlineIcon, Strikethrough, Code, Heading1, Heading2, Heading3, ListOrdered, ListChecks, Quote, Minus, Link as LinkIcon, Table as TableIcon, Undo2, Redo2, ListPlus, ScissorsLineDashed, Languages, SpellCheck2, Palette, ArrowRightLeft, Keyboard, Highlighter, ImageIcon, List, Sparkles, Wand2, Video as VideoIcon, Mic, Paperclip } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import { useToast } from '../v4/useToast'
import { SlashCommand, executeSlashCommand, buildSlashItems } from './SlashCommand'
import { Video, Audio } from './MediaNodes'
import { RecordMention } from './RecordMention'
import type { SlashItem } from './SlashCommand'
import { BLOCK_GROUP_I18N, blockResultCount, groupBlocks } from '../../lib/blockSheet'
import { useMobile } from './useMobile'
import { useHardwareKeyboard } from './useHardwareKeyboard'
import { useTranslation } from 'react-i18next';

/* ═══════════════════════════════════════════════════════════
   NexusEditor v2 — Notion-grade block editor for CRM records.

   New in v2 (per brief):
   1. Notion UX      — hover gutter block handle (⋮⋮ drag, +
                        insert), block context menu (Turn into,
                        Duplicate, Colors, Copy link, Delete),
                        drag-to-reorder with drop indicator,
                        Mod-Shift-Up/Down keyboard reorder.
   2. Mobile (iOS/    — toolbar docked ABOVE the on-screen
      Android)          keyboard (not floating over content,
                        matches Notion mobile + native iOS/
                        Android text-input accessory pattern),
                        horizontally scrollable action strip,
                        "+" opens a full-screen block-type
                        bottom sheet (Notion mobile pattern),
                        long-press block to reorder (haptic-
                        style visual ring).
   3. Hardware        — full desktop shortcut set surfaced as
      keyboard           visible <kbd> hints on hover; detects
                        a physical keyboard on tablets (iPad
                        Magic Keyboard / Android Bluetooth kb)
                        via keydown heuristics and swaps the
                        mobile toolbar back to the desktop one.
   4. More power       — text/highlight color picker, "Turn
                        into" block conversion, character
                        count + reading time, table/task/
                        quote/code blocks, AI actions unchanged
                        from v1 but now also reachable via ⌘J
                        and inside the block context menu.
   ═══════════════════════════════════════════════════════════ */

export interface NexusEditorProps {
  content?: string
  onChange?: (html: string) => void
  onSave?: (html: string) => Promise<void> | void
  placeholder?: string
  autosaveMs?: number
  minHeight?: number
  entityContext?: { type: string; id: string; name?: string }
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

/* i18n：module scope 冇 t() → 只存 key + 中文 fallback，render 時才翻譯
   （array 唔會 cache 住翻譯好嘅字，換語言即時更新） */
const AI_ACTIONS = [
  { id: 'improve', labelKey: 'editor.aiImprove', fallback: '改善寫作', icon: Wand2, kbd: '⌘⇧I' },
  { id: 'shorten', labelKey: 'editor.aiShorten', fallback: '精簡內容', icon: ScissorsLineDashed, kbd: '⌘⇧S' },
  { id: 'expand', labelKey: 'editor.aiExpand', fallback: '擴充內容', icon: ListPlus, kbd: '⌘⇧E' },
  { id: 'translate', labelKey: 'editor.aiTranslate', fallback: '翻譯做英文', icon: Languages, kbd: '' },
  { id: 'fix', labelKey: 'editor.aiFix', fallback: '修正文法', icon: SpellCheck2, kbd: '' },
  { id: 'summarize', labelKey: 'editor.aiSummarize', fallback: '生成摘要', icon: Sparkles, kbd: '' },
]

const BLOCK_COLORS = ['#EF4444', '#F59E0B', '#22C55E', '#3B82F6', '#7C5CFC', '#EC4899', '#6B7280', '#000000']

/* 2026-09-14：AI 提案卡嘅預覽 —— 只保留白名單 tag 並 strip 所有屬性。
   原因：預覽用 dangerouslySetInnerHTML render LLM 輸出；屬性（onerror / href=javascript: 等）
   一律唔准入 DOM，所以先拆乾淨。真正寫入 editor 嘅係原始 HTML —— ProseMirror 只 parse
   schema 內嘅 node／mark，唔會執行 script，Link extension 亦會 validate URL protocol。 */
const PREVIEW_OK_TAGS = new Set(['P', 'BR', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'CODE', 'PRE', 'H1', 'H2', 'H3', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'DIV', 'SPAN'])
function sanitizeForPreview(html: string): string {
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const out = document.createElement('div')
    const walk = (src: Node, dst: Node) => {
      src.childNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          dst.appendChild(document.createTextNode(node.textContent ?? ''))
          return
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return
        const el = node as Element
        if (!PREVIEW_OK_TAGS.has(el.tagName.toUpperCase())) { walk(el, dst); return } // 唔准嘅 tag → 只留文字
        const clone = document.createElement(el.tagName.toLowerCase())
        walk(el, clone)
        dst.appendChild(clone)
      })
    }
    walk(doc.body, out)
    return out.innerHTML
  } catch { return '' }
}

/* Highlight marker 色盤 — 7 個 default + 可以再揀 */
const HIGHLIGHT_COLORS = [
  { nameKey: 'editor.hlYellow', fallback: '黃', value: '#FEF08A' },
  { nameKey: 'editor.hlOrange', fallback: '橙', value: '#FED7AA' },
  { nameKey: 'editor.hlGreen', fallback: '綠', value: '#BBF7D0' },
  { nameKey: 'editor.hlBlue', fallback: '藍', value: '#BFDBFE' },
  { nameKey: 'editor.hlPink', fallback: '粉紅', value: '#FBCFE8' },
  { nameKey: 'editor.hlPurple', fallback: '紫', value: '#E9D5FF' },
  { nameKey: 'editor.hlCyan', fallback: '青', value: '#A5F3FC' },
]

/* Radial 8 格佈局 — 7 色 + 1 edit（最後一格） */
const HL_RADIAL_SLOTS = 8
const HL_RADIAL_R = 52 // px 半徑
const HL_CUSTOM_KEY = 'nexus_editor_hl_custom'
const HL_CUSTOM_MAX = 7

/* 自訂 highlight 色（localStorage persist，最多 7 個，超出 FIFO 輪替） */
function loadCustomHl(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(HL_CUSTOM_KEY) || '[]')
    return Array.isArray(raw) ? raw.filter((c): c is string => typeof c === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(c)).slice(0, HL_CUSTOM_MAX) : []
  } catch { return [] }
}

/* Stage D (T-14) — 自訂色同步去 server（per-user preference），localStorage 做即時 cache。
   舊版本只存 localStorage：換機／清 cache／換瀏覽器就冇晒自訂色。 */
const HL_PREF_KEY = 'editor.hl_custom'
const HL_HEX_RE = /^#[0-9a-fA-F]{3,8}$/

function cleanHlList(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((c): c is string => typeof c === 'string' && HL_HEX_RE.test(c)).slice(0, HL_CUSTOM_MAX)
    : []
}

/** localStorage 即時寫（同步、唔會失敗得滯）＋ server fire-and-forget */
function persistCustomHl(next: string[]) {
  try { localStorage.setItem(HL_CUSTOM_KEY, JSON.stringify(next)) } catch { /* private mode */ }
  void apiClient.put(`/api/v1/crm/preferences/${HL_PREF_KEY}`, { value: next }).catch(() => { /* 離線唔應該擋住編輯 */ })
}

export default function NexusEditor({
  content = '', onChange, onSave, placeholder: placeholderProp,
  autosaveMs = 1500, minHeight = 180, entityContext,
}: NexusEditorProps) {
  const { t } = useTranslation();
  const placeholder = placeholderProp ?? t('editor.placeholder', { defaultValue: '輸入內容，或按 "/" 開啟快速選單，"⌘+J" 呼叫 AI…' });
  /* AI action 標籤：key 存喺 module scope 嘅 AI_ACTIONS，喺呢度才翻譯 */
  const aiLabel = (a: { labelKey: string; fallback: string }) => t(a.labelKey, { defaultValue: a.fallback })
  const { showToast } = useToast()
  const isMobileViewport = useMobile(720)
  const hasHardwareKeyboard = useHardwareKeyboard()
  // On tablets with a hardware keyboard attached, prefer the desktop toolbar
  const useMobileUI = isMobileViewport && !hasHardwareKeyboard

  const [focused, setFocused] = useState(false)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [aiMenuOpen, setAiMenuOpen] = useState(false)
  const [aiBubbleOpen, setAiBubbleOpen] = useState(false)
  const [aiRunning, setAiRunning] = useState(false)
  /* 2026-09-14（用戶報 AI 助手直接取代文字、冇得還原）：AI 結果唔再自動寫入 —— 先出提案卡，
     撳「套用」才落 editor；落完出「還原」bar（TipTap history，一撳 undo 返之前內容）。 */
  const [aiProposal, setAiProposal] = useState<{ actionId: string; html: string; from: number; to: number; source: string } | null>(null)
  const [aiUndoVisible, setAiUndoVisible] = useState(false)
  const [linkPopover, setLinkPopover] = useState<{ x: number; y: number } | null>(null)
  const [linkValue, setLinkValue] = useState('')
  const [blockHandlePos, setBlockHandlePos] = useState<number | null>(null)
  const [blockMenuOpen, setBlockMenuOpen] = useState<{ x: number; y: number; pos: number } | null>(null)
  const [colorSubmenuOpen, setColorSubmenuOpen] = useState(false)
  const [mobileSheetOpen, setMobileSheetOpen] = useState(false)
  const [selectionBubble, setSelectionBubble] = useState<{ x: number; y: number } | null>(null)
  /* 2026-09-14：bubble 位置要量度 menu 自身大細後才算（見下面 useLayoutEffect） */
  const [bubblePos, setBubblePos] = useState<{ left: number; top: number } | null>(null)
  const [slashMenu, setSlashMenu] = useState<{ x: number; y: number; items: SlashItem[]; selected: number; range?: any } | null>(null)
  /* P1-⑦：mobile 插入區塊 sheet 嘅搜尋字串 */
  const [blockQuery, setBlockQuery] = useState('')
  const bubbleRef = useRef<HTMLDivElement>(null)
  const slashRef = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  /* 2026-09-11 review T-01/T-08：用 ref 拎最新嘅 onSave。
     原因：`useEditor({...})` 預設只 create 一次，裡面嘅 onUpdate closure 會鎖死
     第一次 render 嘅 onSave（stale prop）。同埋 flush / retry 要喺 render 之外叫。 */
  const onSaveRef = useRef(onSave)
  const retryRef = useRef(0)
  useEffect(() => { onSaveRef.current = onSave }, [onSave])

  /** 即時儲存（唔等 debounce）— debounce timer、retry、flush 三者共用 */
  const saveNow = useCallback(async (html: string) => {
    if (!onSaveRef.current) return
    if (saveTimer.current) { clearTimeout(saveTimer.current); saveTimer.current = null }
    setSaveState('saving')
    try {
      await onSaveRef.current(html)
      retryRef.current = 0
      setSaveState('saved')
    } catch {
      /* 原本冇 try/catch：onSave reject 之後 setSaveState('saved') 永遠跑唔到 →
         UI 卡死喺「正在儲存…」，而最新內容其實從未落 DB（用戶以為安全）。
         改為明確 'error' + 有限次數 backoff retry（2s / 5s / 10s），最終彈 toast。 */
      setSaveState('error')
      if (retryRef.current < 3) {
        retryRef.current += 1
        const delay = [2000, 5000, 10000][retryRef.current - 1]
        saveTimer.current = setTimeout(() => { void saveNow(html) }, delay)
      } else {
        showToast(t('editor.saveFailedRetry', { defaultValue: '儲存失敗，請檢查網絡後再試' }))
      }
    }
  }, [showToast, t])

  /** 停手 autosaveMs 之後儲存 */
  const scheduleSave = useCallback((html: string) => {
    if (!onSaveRef.current) return
    setSaveState('saving')
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => { void saveNow(html) }, autosaveMs)
  }, [autosaveMs, saveNow])
  const blockMenuRef = useRef<HTMLDivElement>(null)
  const contentAreaRef = useRef<HTMLDivElement>(null)

  /* ── Highlight radial menu ── */
  const [hlRadial, setHlRadial] = useState<{ x: number; y: number } | null>(null)
  const [hlEditOpen, setHlEditOpen] = useState(false)
  const [hlCustom, setHlCustom] = useState<string[]>(loadCustomHl)
  const [hlNewColor, setHlNewColor] = useState('#FDE047')
  const hlRadialRef = useRef<HTMLDivElement>(null)

  const aiMenuRef = useRef<HTMLDivElement>(null)

  const editor = useEditor({
    shouldRerenderOnTransaction: false,
    /* a11y：ProseMirror 嘅 contenteditable 原本自帶 role="textbox" 但冇 accessible name
       （axe serious:aria-input-field-name）。用 editorProps.attributes 補 aria-label 時
       **會覆蓋** Tiptap 預設 attribute（連 role 都會冇 → 變成 aria-prohibited-attr），
       所以要連 role／aria-multiline 一齊寫返。 */
    editorProps: {
      attributes: {
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-label': t('editor.contentLabel', { defaultValue: '筆記內容' }),
      },
    },
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] }, dropcursor: false }),
      Placeholder.configure({ placeholder }),
      Link.configure({ openOnClick: false, autolink: true }),
      Image.configure({ inline: false, allowBase64: true }),
      Video,
      Audio,
      RecordMention,
      Table.configure({ resizable: true }),
      TableRow, TableHeader, TableCell,
      TaskList,
      TaskItem.configure({ nested: true }),
      Highlight.configure({ multicolor: true }),
      TextStyle, Color,
      Underline,
      CharacterCount,
      Dropcursor.configure({ color: 'var(--color-primary)', width: 3 }),
      SlashCommand,
    ],
    content,
    onUpdate: ({ editor }) => {
      const html = editor.getHTML()
      onChange?.(html)
      // caret 自動 scroll — 打字時字唔會隱藏喺 scroll container 底部
      editor.commands.scrollIntoView()
      scheduleSave(html)
    },
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    onSelectionUpdate: ({ editor: ed }) => {
      const { from, to } = ed.state.selection
      if (from === to) { setSelectionBubble(null); setBubblePos(null); return }
      /* 2026-09-14（用戶報 quick style editor 遮住選中文字）：錄選字「尾端」座標，
         x 貼字尾；垂直位置等 layout effect 量完 menu 高度才算（唔會疊住選字）。 */
      const end = ed.view.coordsAtPos(to)
      setSelectionBubble({ x: end.right, y: end.top })
    },
  })

  const hideBubbleAfterAction = () => {
    setSelectionBubble(null)
  }

  /* ── Highlight Radial 選單 ── */
  const openHlRadial = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setHlRadial({ x: rect.left + rect.width / 2, y: rect.top - 6 })
    setHlEditOpen(false)
  }, [])

  const applyHlColor = useCallback((color: string) => {
    if (!editor) return
    editor.chain().focus().setHighlight({ color }).run()
    setHlRadial(null); setHlEditOpen(false)
  }, [editor])

  const clearHl = useCallback(() => {
    if (!editor) return
    editor.chain().focus().unsetHighlight().run()
    setHlRadial(null); setHlEditOpen(false)
  }, [editor])

  /* 自訂色加入 — 放第一格，最多 7 個，超出最舊輪替走。
     加完保留 radial 打開，令用戶即時見到新色喺第二行 */
  const addCustomHlColor = useCallback(() => {
    const color = hlNewColor.trim().toLowerCase()
    if (!/^#[0-9a-f]{3,8}$/.test(color)) return
    setHlCustom(prev => {
      const next = [color, ...prev.filter(c => c !== color)].slice(0, HL_CUSTOM_MAX)
      persistCustomHl(next)
      return next
    })
    if (editor) editor.chain().focus().setHighlight({ color }).run()
    setHlEditOpen(false)
  }, [hlNewColor, editor])

  /* Stage D (T-14)：mount 時由 server 拉返自訂色（cross-device sync）。
     server 未有記錄（null）→ 保留本機 localStorage 版本，唔會清走用戶現有設定。 */
  useEffect(() => {
    let alive = true
    apiClient.get<{ value: unknown }>(`/api/v1/crm/preferences/${HL_PREF_KEY}`)
      .then((r) => {
        if (!alive) return
        const clean = cleanHlList(r?.value)
        if (clean.length) {
          setHlCustom(clean)
          try { localStorage.setItem(HL_CUSTOM_KEY, JSON.stringify(clean)) } catch { /* ignore */ }
        }
      })
      .catch(() => { /* 離線／未登入 → 照用 localStorage */ })
    return () => { alive = false }
  }, [])

  /* radial click outside → 關 */
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (hlRadialRef.current && !hlRadialRef.current.contains(e.target as Node)) {
        setHlRadial(null); setHlEditOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  /* Esc → 關 popup / radial */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setAiMenuOpen(false); setAiBubbleOpen(false); setHlRadial(null); setHlEditOpen(false) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /* click outside bubble → hide */
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (bubbleRef.current && !bubbleRef.current.contains(e.target as Node)) {
        setSelectionBubble(null)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  useEffect(() => { if (!selectionBubble) setBubblePos(null) }, [selectionBubble])

  /* ── 2026-09-14：量度 bubble 實際大細，將 menu 放喺選字「之上」，右邊貼齊選字尾，再夾入 viewport。
     之前寫死 left = 選字左邊、top = 選字頂 - 8，menu 高度 ~40px → 正好疊住選中文字。 ── */
  useLayoutEffect(() => {
    if (!selectionBubble || !bubbleRef.current) { setBubblePos(null); return }
    const w = bubbleRef.current.offsetWidth
    const h = bubbleRef.current.offsetHeight
    if (!w || !h) return
    const vw = window.innerWidth
    const left = Math.min(Math.max(8, selectionBubble.x - w), Math.max(8, vw - w - 8))
    const top = Math.max(8, selectionBubble.y - h - 10)
    setBubblePos({ left, top })
  }, [selectionBubble])

  /* ── Notion-style hover gutter: track which block the pointer is over ── */
  const handleContentMouseMove = useCallback((e: React.MouseEvent) => {
    if (!editor || useMobileUI) return
    const view = editor.view
    const coords = { left: e.clientX, top: e.clientY }
    const posInfo = view.posAtCoords(coords)
    if (!posInfo) return
    const resolved = view.state.doc.resolve(posInfo.pos)
    const blockPos = resolved.before(1)
    setBlockHandlePos(blockPos)
  }, [editor, useMobileUI])

  /* ── Hardware keyboard: Mod-Shift-ArrowUp/Down block reorder ── */
  useEffect(() => {
    const onKeydown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); setAiMenuOpen(v => !v); return }
      if (!editor) return
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        e.preventDefault()
        const dir = e.key === 'ArrowUp' ? -1 : 1
        moveCurrentBlock(dir)
      }
    }
    window.addEventListener('keydown', onKeydown)
    return () => window.removeEventListener('keydown', onKeydown)
  }, [editor])

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (blockMenuRef.current && !blockMenuRef.current.contains(e.target as Node)) { setBlockMenuOpen(null); setColorSubmenuOpen(false) }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const moveCurrentBlock = (dir: 1 | -1) => {
    if (!editor) return
    const { $from } = editor.state.selection
    const blockPos = $from.before(1)
    const node = editor.state.doc.nodeAt(blockPos)
    if (!node) return
    const size = node.nodeSize
    const targetPos = dir === -1 ? blockPos : blockPos + size
    if (targetPos < 0 || targetPos > editor.state.doc.content.size) return
    const tr = editor.state.tr.delete(blockPos, blockPos + size)
    const insertAt = dir === -1 ? targetPos : targetPos - size
    tr.insert(insertAt, node)
    editor.view.dispatch(tr)
    showToast(dir === -1
      ? t('editor.blockMovedUp', { defaultValue: '區塊已上移' })
      : t('editor.blockMovedDown', { defaultValue: '區塊已下移' }))
  }

  const openBlockMenu = (e: React.MouseEvent) => {
    if (blockHandlePos === null) return
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setBlockMenuOpen({ x: rect.left, y: rect.bottom + 4, pos: blockHandlePos })
  }

  const turnBlockInto = (type: 'paragraph' | 'heading1' | 'heading2' | 'bulletList' | 'orderedList' | 'taskList' | 'blockquote') => {
    if (!editor) return
    editor.chain().focus()
    if (type === 'paragraph') editor.chain().focus().setParagraph().run()
    else if (type === 'heading1') editor.chain().focus().setHeading({ level: 1 }).run()
    else if (type === 'heading2') editor.chain().focus().setHeading({ level: 2 }).run()
    else if (type === 'bulletList') editor.chain().focus().toggleBulletList().run()
    else if (type === 'orderedList') editor.chain().focus().toggleOrderedList().run()
    else if (type === 'taskList') editor.chain().focus().toggleTaskList().run()
    else if (type === 'blockquote') editor.chain().focus().toggleBlockquote().run()
    setBlockMenuOpen(null)
  }

  const duplicateBlock = () => {
    if (!editor || blockMenuOpen === null) return
    const node = editor.state.doc.nodeAt(blockMenuOpen.pos)
    if (!node) return
    const endPos = blockMenuOpen.pos + node.nodeSize
    editor.view.dispatch(editor.state.tr.insert(endPos, node))
    setBlockMenuOpen(null)
    showToast(t('editor.blockCopied', { defaultValue: '已複製區塊' }))
  }

  const deleteBlock = () => {
    if (!editor || blockMenuOpen === null) return
    const node = editor.state.doc.nodeAt(blockMenuOpen.pos)
    if (!node) return
    editor.view.dispatch(editor.state.tr.delete(blockMenuOpen.pos, blockMenuOpen.pos + node.nodeSize))
    setBlockMenuOpen(null)
  }

  const applyBlockColor = (color: string) => {
    if (!editor || blockMenuOpen === null) return
    const node = editor.state.doc.nodeAt(blockMenuOpen.pos)
    if (!node) return
    editor.chain().setTextSelection({ from: blockMenuOpen.pos, to: blockMenuOpen.pos + node.nodeSize }).setColor(color).run()
    setBlockMenuOpen(null); setColorSubmenuOpen(false)
  }

  const copyBlockLink = () => {
    navigator.clipboard?.writeText(`${window.location.href}#block-${blockMenuOpen?.pos}`)
    showToast(t('editor.blockLinkCopied', { defaultValue: '已複製區塊連結' }))
    setBlockMenuOpen(null)
  }

  const runAiAction = useCallback(async (actionId: string) => {
    if (!editor) return
    setAiMenuOpen(false); setAiBubbleOpen(false); setBlockMenuOpen(null); setAiRunning(true)
    const { from, to } = editor.state.selection
    const selectedText = editor.state.doc.textBetween(from, to, ' ')
    const scope = selectedText.trim() ? selectedText : editor.getText()
    try {
      const data = await apiClient.post<{ result: string }>('/api/v1/ai/editor-assist', {
        action: actionId, text: scope, entity: entityContext,
      })
      if (!data?.result) throw new Error('empty')
      /* 2026-09-14（用戶指示）：AI 唔准直接取代原文 → 出提案卡，等用戶撳「套用」。
         記住當時嘅 range 同原文，套用前會 re-validate。 */
      setAiProposal({ actionId, html: data.result, from, to, source: selectedText })
    } catch { showToast(t('editor.aiRequestFailed', { defaultValue: 'AI 請求失敗，請重試' })) }
    finally { setAiRunning(false) }
  }, [editor, entityContext, showToast, t])

  /* 套用 AI 提案。
     ⚠️ 唔好喺 setState／await 之後即刻 dispatch — dispatch 觸發 onUpdate → onChange →
     parent setState → NexusEditor re-render，會撞 ProseMirror DOM update 而 insertBefore crash。
     setTimeout(0) 等 React render cycle 完成先改 editor state。
     - 有選字而且 range 仍然有效 → 用 insertContentAt({from,to}) 取代（HTML 由 ProseMirror parse → style 入到 editor）
     - range 失效（用戶中途改過文）→ 唔亂覆蓋，改成新增喺文末 + toast 講明
     - 冇選字 → append 做新 paragraph */
  const applyAiProposal = useCallback(() => {
    if (!editor || !aiProposal) return
    const { html, from, to, source } = aiProposal
    setAiProposal(null)
    setTimeout(() => {
      const size = editor.state.doc.content.size
      const hasSelection = !!source.trim()
      const stillValid = hasSelection && from < size && to <= size
        && editor.state.doc.textBetween(from, to, ' ') === source
      if (hasSelection && stillValid) {
        editor.chain().focus().insertContentAt({ from, to }, html).run()
      } else {
        if (hasSelection) showToast(t('editor.aiRangeLost', { defaultValue: '原文已改動，AI 結果改為新增喺文末' }))
        editor.chain().focus().insertContentAt(size, { type: 'paragraph' }).run()
        editor.chain().focus().insertContent(html).run()
      }
      showToast(t('editor.aiEditDone', { defaultValue: 'AI 已完成編輯' }))
      setAiUndoVisible(true)
      window.setTimeout(() => setAiUndoVisible(false), 10000)
    }, 0)
  }, [editor, aiProposal, showToast, t])

  /* 「還原」= TipTap history 一步 undo（套用係單一 transaction） */
  const undoAiApply = useCallback(() => {
    if (!editor) return
    editor.chain().focus().undo().run()
    setAiUndoVisible(false)
  }, [editor])

  /* ── Slash menu AI items (SlashCommand.ts dispatches nexus-editor:ai-slash) ── */
  useEffect(() => {
    const onAiSlash = (e: Event) => {
      const detail = (e as CustomEvent).detail as { id?: string } | undefined
      if (!detail?.id || !editor) return
      if (detail.id === 'ai') runAiAction('improve')
      else if (detail.id === 'ai-summarize') runAiAction('summarize')
    }
    window.addEventListener('nexus-editor:ai-slash', onAiSlash)
    return () => window.removeEventListener('nexus-editor:ai-slash', onAiSlash)
  }, [editor, runAiAction])

  /* ── Slash menu (NexusEditor 自己 render — 唔用 tippy，避 React 19 crash) ── */
  useEffect(() => {
    const onOpen = (e: Event) => {
      const d = (e as CustomEvent).detail as { x: number; y: number; range?: any }
      setSlashMenu({ x: d.x, y: d.y, items: buildSlashItems(), selected: 0, range: d.range })
    }
    const onUpdate = (e: Event) => {
      const d = (e as CustomEvent).detail as { x: number; y: number; items?: SlashItem[]; range?: any }
      setSlashMenu(prev => ({ x: d.x, y: d.y, items: d.items ?? prev?.items ?? buildSlashItems(), selected: 0, range: d.range ?? prev?.range }))
    }
    const onKeydown = (e: Event) => {
      const d = (e as CustomEvent).detail as { key: string }
      setSlashMenu(prev => {
        if (!prev || !prev.items.length) return prev
        const n = prev.items.length
        if (d.key === 'ArrowUp') return { ...prev, selected: (prev.selected + n - 1) % n }
        if (d.key === 'ArrowDown') return { ...prev, selected: (prev.selected + 1) % n }
        return prev
      })
    }
    const onEnter = () => {
      setSlashMenu(prev => {
        if (prev && prev.items[prev.selected] && editor) {
          const item = prev.items[prev.selected]
          const range = prev.range
          setTimeout(() => executeSlashCommand(editor, item.id, range), 0)
        }
        return null
      })
    }
    const onClose = () => setSlashMenu(null)
    window.addEventListener('nexus-editor:slash-open', onOpen)
    window.addEventListener('nexus-editor:slash-update', onUpdate)
    window.addEventListener('nexus-editor:slash-keydown', onKeydown)
    window.addEventListener('nexus-editor:slash-enter', onEnter)
    window.addEventListener('nexus-editor:slash-close', onClose)
    return () => {
      window.removeEventListener('nexus-editor:slash-open', onOpen)
      window.removeEventListener('nexus-editor:slash-update', onUpdate)
      window.removeEventListener('nexus-editor:slash-keydown', onKeydown)
      window.removeEventListener('nexus-editor:slash-enter', onEnter)
      window.removeEventListener('nexus-editor:slash-close', onClose)
    }
  }, [editor])

  const openLinkPopover = useCallback(() => {
    if (!editor) return
    const { from, to } = editor.state.selection
    if (from === to) { showToast(t('editor.selectTextFirst', { defaultValue: '請先選取文字' })); return }
    setLinkValue(editor.getAttributes('link').href || '')
    const coords = editor.view.coordsAtPos(from)
    setLinkPopover({ x: coords.left, y: coords.bottom + 8 })
  }, [editor, showToast, t])

  const applyLink = () => {
    if (!editor) return
    if (linkValue.trim()) editor.chain().focus().setLink({ href: linkValue.trim() }).run()
    else editor.chain().focus().unsetLink().run()
    setLinkPopover(null)
  }

  /* ── Notes v2 (T3.2): media upload → real storage URL（唔係 blob:，跨 session 開到）── */
  const mediaInputRef = useRef<HTMLInputElement | null>(null)
  const mediaKindRef = useRef<'image' | 'video' | 'audio' | 'file'>('image')

  const pickMedia = useCallback((kind: 'image' | 'video' | 'audio' | 'file') => {
    mediaKindRef.current = kind
    const el = mediaInputRef.current
    if (!el) return
    el.accept = kind === 'image' ? 'image/*' : kind === 'video' ? 'video/*' : kind === 'audio' ? 'audio/*' : '*/*'
    el.value = ''
    el.click()
  }, [])

  const onMediaPicked = useCallback(async (file: File | null | undefined) => {
    if (!file || !editor) return
    const kind = mediaKindRef.current
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await apiClient.postForm<{ url: string; filename?: string }>('/api/v1/crm/notes/media', fd)
      const url = res?.url
      if (!url) throw new Error(t('editor.uploadFailed', { defaultValue: '上載失敗' }))
      if (kind === 'image') editor.chain().focus().setImage({ src: url }).run()
      else if (kind === 'video') editor.chain().focus().insertContent({ type: 'video', attrs: { src: url } }).run()
      else if (kind === 'audio') editor.chain().focus().insertContent({ type: 'audio', attrs: { src: url } }).run()
      else editor.chain().focus().insertContent(`<a href="${url}" target="_blank" rel="noopener">📎 ${(res.filename || t('editor.attachment', { defaultValue: '附件' })).replace(/[<>&"]/g, '')}</a>`).run()
      showToast(t('editor.uploadDone', { defaultValue: '已上載' }))
    } catch (e: any) {
      showToast(e?.detail || e?.message || t('editor.uploadFailed', { defaultValue: '上載失敗' }))
    }
  }, [editor, showToast, t])

  const insertImage = useCallback(() => pickMedia('image'), [pickMedia])

  const insertTable = useCallback(() => {
    editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
    setMobileSheetOpen(false)
  }, [editor])

  /* 2026-09-11 review：
     • T-08 / F-13 — host（NotesWorkspacePage）喺 mobile 返回列表／換筆記之前 dispatch
       `flush-save`，即時寫 DB，唔好等 1.5s debounce window 白蝕最後幾個字。
     • T-07 / F-08 — slash `image` 唔再用 window.prompt，改為經呢個事件叫返
       同一條 pickMedia() 上載流程（Video/Audio 已用同一條路）。 */
  useEffect(() => {
    const onFlush = () => {
      if (!editor) return
      void saveNow(editor.getHTML())
    }
    const onPickMedia = (e: Event) => {
      const kind = (e as CustomEvent).detail?.kind
      if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'file') {
        pickMedia(kind)
      }
    }
    window.addEventListener('nexus-editor:flush-save', onFlush)
    window.addEventListener('nexus-editor:pick-media', onPickMedia as EventListener)
    return () => {
      window.removeEventListener('nexus-editor:flush-save', onFlush)
      window.removeEventListener('nexus-editor:pick-media', onPickMedia as EventListener)
    }
  }, [editor, saveNow, pickMedia])

  if (!editor) return null

  const wordCount = editor.storage.characterCount?.words?.() ?? 0
  const readingMin = Math.max(1, Math.round(wordCount / 200))

  /* P1-⑦：加 group（文字／工作／媒體 —— 手機 sheet 要「想插入邊類內容」）＋ keywords
     （令打英文都搵到：table → 表格、checklist → 待辦清單）。 */
  const MOBILE_BLOCK_TYPES = [
    { id: 'h1', label: t('editor.slashH1', { defaultValue: '大標題' }), group: 'text' as const, keywords: ['heading', 'h1', 'title'], icon: Heading1, run: () => editor.chain().focus().toggleHeading({ level: 1 }).run() },
    { id: 'h2', label: t('editor.slashH2', { defaultValue: '中標題' }), group: 'text' as const, keywords: ['heading', 'h2', 'subtitle'], icon: Heading2, run: () => editor.chain().focus().toggleHeading({ level: 2 }).run() },
    { id: 'bullet', label: t('editor.bulletList', { defaultValue: '項目列表' }), group: 'text' as const, keywords: ['bullet', 'list', 'ul'], icon: List, run: () => editor.chain().focus().toggleBulletList().run() },
    { id: 'ordered', label: t('editor.slashOrdered', { defaultValue: '編號列表' }), group: 'text' as const, keywords: ['numbered', 'ordered', 'ol'], icon: ListOrdered, run: () => editor.chain().focus().toggleOrderedList().run() },
    { id: 'quote', label: t('editor.slashQuote', { defaultValue: '引言' }), group: 'text' as const, keywords: ['quote', 'blockquote'], icon: Quote, run: () => editor.chain().focus().toggleBlockquote().run() },
    { id: 'task', label: t('editor.taskList', { defaultValue: '待辦清單' }), group: 'work' as const, keywords: ['task', 'todo', 'checklist', 'checkbox'], icon: ListChecks, run: () => editor.chain().focus().toggleTaskList().run() },
    { id: 'table', label: t('editor.slashTable', { defaultValue: '表格' }), group: 'work' as const, keywords: ['table', 'grid'], icon: TableIcon, run: insertTable },
    { id: 'image', label: t('editor.slashImage', { defaultValue: '圖片' }), group: 'media' as const, keywords: ['image', 'photo', 'camera', 'picture'], icon: ImageIcon, run: insertImage },
    { id: 'video', label: t('editor.slashVideo', { defaultValue: '影片' }), group: 'media' as const, keywords: ['video', 'movie', 'record'], icon: VideoIcon, run: () => pickMedia('video') },
    { id: 'audio', label: t('editor.slashAudio', { defaultValue: '語音' }), group: 'media' as const, keywords: ['audio', 'voice', 'mic'], icon: Mic, run: () => pickMedia('audio') },
    { id: 'file', label: t('editor.attachment', { defaultValue: '附件' }), group: 'media' as const, keywords: ['file', 'attach', 'upload'], icon: Paperclip, run: () => pickMedia('file') },
  ]
  const mobileBlockGroups = groupBlocks(MOBILE_BLOCK_TYPES, blockQuery)

  return (
    <div className={`nxe-root ${focused ? 'focused' : ''}`}>
      {/* Notes v2 (T3.2): hidden media picker — 手機可拍／揀檔 */}
      <input
        ref={mediaInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; onMediaPicked(f) }}
      />
      {/* ═══ DESKTOP / HARDWARE-KEYBOARD TOOLBAR ═══ */}
      {!useMobileUI && (
        <div className="nxe-toolbar">
          <div className="nxe-tb-group">
            <button className="nxe-tb-btn" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}>
              <Undo2 size={15} /><span className="nxe-kbd-tip">Undo <kbd>⌘Z</kbd></span>
            </button>
            <button className="nxe-tb-btn" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}>
              <Redo2 size={15} /><span className="nxe-kbd-tip">Redo <kbd>⌘⇧Z</kbd></span>
            </button>
          </div>
          <div className="nxe-tb-group">
            <button className={`nxe-tb-btn ${editor.isActive('heading', { level: 1 }) ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}>
              <Heading1 size={15} /><span className="nxe-kbd-tip">Heading 1 <kbd>⌘⌥1</kbd></span>
            </button>
            <button className={`nxe-tb-btn ${editor.isActive('heading', { level: 2 }) ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>
              <Heading2 size={15} /><span className="nxe-kbd-tip">Heading 2 <kbd>⌘⌥2</kbd></span>
            </button>
            <button className={`nxe-tb-btn ${editor.isActive('heading', { level: 3 }) ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>
              <Heading3 size={15} />
            </button>
          </div>
          <div className="nxe-tb-group">
            <button className={`nxe-tb-btn ${editor.isActive('bold') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleBold().run()}>
              <Bold size={15} /><span className="nxe-kbd-tip">Bold <kbd>⌘B</kbd></span>
            </button>
            <button className={`nxe-tb-btn ${editor.isActive('italic') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleItalic().run()}>
              <Italic size={15} /><span className="nxe-kbd-tip">Italic <kbd>⌘I</kbd></span>
            </button>
            <button className={`nxe-tb-btn ${editor.isActive('underline') ? 'active' : ''}`} title={t('editor.underline', { defaultValue: '底線' })} aria-label={t('editor.underline', { defaultValue: '底線' }) as string} onClick={() => editor.chain().focus().toggleUnderline().run()}>
              <UnderlineIcon size={15} /><span className="nxe-kbd-tip">Underline <kbd>⌘U</kbd></span>
            </button>
            <button className={`nxe-tb-btn ${editor.isActive('strike') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleStrike().run()}><Strikethrough size={15} /></button>
            <button className={`nxe-tb-btn ${editor.isActive('code') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleCode().run()}>
              <Code size={15} /><span className="nxe-kbd-tip">Code <kbd>⌘E</kbd></span>
            </button>
          </div>
          <div className="nxe-tb-group">
            <button className={`nxe-tb-btn ${editor.isActive('bulletList') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleBulletList().run()}><SvcIcon name="list" size={15} /></button>
            <button className={`nxe-tb-btn ${editor.isActive('orderedList') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleOrderedList().run()}><ListOrdered size={15} /></button>
            <button className={`nxe-tb-btn ${editor.isActive('taskList') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleTaskList().run()}><ListChecks size={15} /></button>
            <button className={`nxe-tb-btn ${editor.isActive('blockquote') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleBlockquote().run()}><Quote size={15} /></button>
            <button className="nxe-tb-btn" onClick={() => editor.chain().focus().setHorizontalRule().run()}><Minus size={15} /></button>
          </div>
          <div className="nxe-tb-group">
            <button className={`nxe-tb-btn ${editor.isActive('link') ? 'active' : ''}`} onClick={openLinkPopover}>
              <LinkIcon size={15} /><span className="nxe-kbd-tip">Link <kbd>⌘K</kbd></span>
            </button>
            <button className="nxe-tb-btn" onClick={insertImage}><SvcIcon name="image" size={15} /></button>
            <button className="nxe-tb-btn" title={t('editor.slashVideo', { defaultValue: '影片' })} onClick={() => pickMedia('video')}><VideoIcon size={15} /></button>
            <button className="nxe-tb-btn" title={t('editor.audioMemo', { defaultValue: '語音備忘' })} onClick={() => pickMedia('audio')}><Mic size={15} /></button>
            <button className="nxe-tb-btn" title={t('editor.attachment', { defaultValue: '附件' })} onClick={() => pickMedia('file')}><Paperclip size={15} /></button>
            <button className="nxe-tb-btn" onClick={insertTable}><TableIcon size={15} /></button>
          </div>

          <div className="nxe-tb-spacer" />
          {hasHardwareKeyboard && isMobileViewport && (
            <span className="nxe-hwkb-badge"><Keyboard size={11} />{t('editor.hardwareKeyboard', { defaultValue: '已連接實體鍵盤' })}</span>
          )}
          <span className="nxe-tb-wordcount">{t('editor.wordCount', { defaultValue: '{{words}} 字 · {{min}} 分鐘閱讀', words: wordCount, min: readingMin })}</span>

          <div style={{ position: 'relative' }} ref={aiMenuRef}>
            <button className="nxe-ai-btn" onClick={() => setAiMenuOpen(v => !v)}>
              <SvcIcon name="sparkles" size={13} />{t('editor.aiAssistant', { defaultValue: 'AI 助手' })}<SvcIcon name="chevron-down" size={12} />
            </button>
            {aiMenuOpen && (
              <div className="nxe-ai-menu" style={{ right: 0 }}>
                {AI_ACTIONS.map(a => {
                  const Icon = a.icon
                  return (
                    <button key={a.id} className="nxe-ai-menu-item" onClick={() => runAiAction(a.id)}>
                      <span className="nxe-ai-menu-item-left"><Icon size={15} /> {aiLabel(a)}</span>
                      {a.kbd && <span className="nxe-ai-menu-kbd">{a.kbd}</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {aiRunning && <div className="nxe-ai-loading-bar" data-testid="ai-loading" />}

      {/* ═══ AI 提案卡（2026-09-14）═══
          用戶指示：AI 唔可以靜默取代原有 wording。呢張卡先展示建議，撳「套用」才寫入 editor。 */}
      {aiProposal && (
        <div className="nxe-ai-proposal" role="dialog" data-testid="ai-proposal"
          aria-label={t('editor.aiProposalTitle', { defaultValue: 'AI 建議' }) as string}>
          <div className="nxe-ai-proposal-head">
            <SvcIcon name="sparkles" size={13} />
            <span>{t('editor.aiProposalTitle', { defaultValue: 'AI 建議' })}</span>
            <span className="nxe-ai-proposal-action">{aiLabel(AI_ACTIONS.find(a => a.id === aiProposal.actionId) ?? AI_ACTIONS[0])}</span>
          </div>
          <div className="nxe-ai-proposal-body" data-testid="ai-proposal-body"
            dangerouslySetInnerHTML={{ __html: sanitizeForPreview(aiProposal.html) }} />
          <div className="nxe-ai-proposal-actions">
            <button className="nxe-ai-proposal-apply" onClick={applyAiProposal}>
              {t('editor.aiApply', { defaultValue: '套用' })}
            </button>
            <button className="nxe-ai-proposal-cancel" onClick={() => setAiProposal(null)}>
              {t('editor.aiCancel', { defaultValue: '取消' })}
            </button>
          </div>
        </div>
      )}

      {/* 套用後嘅還原入口（用戶指示：要提供 redo option）*/}
      {aiUndoVisible && (
        <div className="nxe-ai-undo-bar" role="status" data-testid="ai-undo-bar">
          <span>{t('editor.aiApplied', { defaultValue: 'AI 已套用' })}</span>
          <button className="nxe-ai-undo-btn" onClick={undoAiApply}>
            {t('editor.aiRevert', { defaultValue: '還原' })}
          </button>
        </div>
      )}

      {/* ═══ SELECTION BUBBLE (self-made — 唔用 tippy BubbleMenu，避免 React 19 DOM commit crash) ═══ */}
      {editor && selectionBubble && (
        <div className="nxe-bubble-menu" ref={bubbleRef}
          style={{
            position: 'fixed',
            left: bubblePos?.left ?? selectionBubble.x,
            top: bubblePos?.top ?? selectionBubble.y,
            /* 未量度完唔顯示 —— 否則會有一格係「疊住選字」嘅位置 */
            visibility: bubblePos ? 'visible' : 'hidden',
            zIndex: 50,
          }}>
          <button className={`nxe-bubble-btn ${editor.isActive('bold') ? 'active' : ''}`} onClick={() => { editor.chain().focus().toggleBold().run(); hideBubbleAfterAction() }}><Bold size={13} /></button>
          <button className={`nxe-bubble-btn ${editor.isActive('italic') ? 'active' : ''}`} onClick={() => { editor.chain().focus().toggleItalic().run(); hideBubbleAfterAction() }}><Italic size={13} /></button>
          <button className={`nxe-bubble-btn ${editor.isActive('underline') ? 'active' : ''}`} title={t('editor.underline', { defaultValue: '底線' })} aria-label={t('editor.underline', { defaultValue: '底線' }) as string} onClick={() => { editor.chain().focus().toggleUnderline().run(); hideBubbleAfterAction() }}><UnderlineIcon size={13} /></button>
          <button className={`nxe-bubble-btn ${editor.isActive('highlight') ? 'active' : ''}`} title={t('editor.highlightColor', { defaultValue: 'Highlight 顏色' })} onClick={openHlRadial}><Highlighter size={13} /></button>
          <button className="nxe-bubble-btn" onClick={openLinkPopover}><LinkIcon size={13} /></button>
          <div className="nxe-tb-divider" />
          <button className="nxe-bubble-ai-btn" onClick={() => setAiBubbleOpen(v => !v)}><SvcIcon name="sparkles" size={12} /> AI</button>
          {aiBubbleOpen && (
            <div className="nxe-ai-menu" style={{ top: '110%', left: 0 }}>
              {AI_ACTIONS.slice(0, 4).map(a => {
                const Icon = a.icon
                return <button key={a.id} className="nxe-ai-menu-item" onClick={() => runAiAction(a.id)}><span className="nxe-ai-menu-item-left"><Icon size={15} /> {aiLabel(a)}</span></button>
              })}
            </div>
          )}
        </div>
      )}

      {/* ═══ SLASH MENU (self-rendered — 唔用 tippy) ═══
          ⚠️ 注意：live 嘅 slash menu 係喺呢度 inline render，唔係
          `components/editor/SlashMenu.tsx`（嗰個只淨返 `import type { SlashItem }`
          — v6.51 改 custom-event 之後已成 dead code）。加 ARIA／改樣都改呢度。 */}
      {slashMenu && (
        <div ref={slashRef} className="nxe-slash-menu" role="listbox"
          aria-label={t('editor.slashMenu', { defaultValue: '插入區塊' }) as string}
          aria-activedescendant={`nxe-slash-opt-${slashMenu.selected}`}
          style={{ position: 'fixed', left: slashMenu.x, top: slashMenu.y, zIndex: 50 }}>
          {(() => {
            const groups = Array.from(new Set(slashMenu.items.map(i => i.group)))
            return groups.map(group => (
              <div key={group} role="presentation">
                <div className="nxe-slash-group-label" role="presentation">{group}</div>
                {slashMenu.items.filter(i => i.group === group).map((item) => {
                  const idx = slashMenu.items.indexOf(item)
                  return (
                    <div key={item.id} id={`nxe-slash-opt-${idx}`} role="option"
                      aria-selected={idx === slashMenu.selected}
                      className={`nxe-slash-item ${idx === slashMenu.selected ? 'selected' : ''}`}
                      onMouseEnter={() => setSlashMenu(prev => prev ? { ...prev, selected: idx } : prev)}
                      onClick={() => { const it = slashMenu.items[slashMenu.selected]; const range = slashMenu.range; setSlashMenu(null); setTimeout(() => it && executeSlashCommand(editor, it.id, range), 0) }}>
                      <div className="nxe-slash-item-label">{item.label}</div>
                      <div className="nxe-slash-sub">{item.sub}</div>
                    </div>
                  )
                })}
              </div>
            ))
          })()}
          {/* 螢幕閱讀器播報：結果數量／目前選中項 */}
          <div className="sr-only" aria-live="polite">
            {t('editor.slashResults', { defaultValue: '{{n}} 個選項', n: slashMenu.items.length })}
          </div>
        </div>
      )}

      <div className="nxe-content-wrap">
        <div ref={contentAreaRef} className="nxe-content" style={{ minHeight }} onMouseMove={handleContentMouseMove}>
          {!useMobileUI && blockHandlePos !== null && (
            <div className="nxe-block-handle visible" style={{ top: 16 }}>
              <button className="nxe-handle-btn" onClick={() => editor.chain().focus().insertContentAt(blockHandlePos, '<p></p>').run()}><SvcIcon name="plus" size={14} /></button>
              <button className="nxe-handle-btn grip" onClick={openBlockMenu}><SvcIcon name="grip-vertical" size={14} /></button>
            </div>
          )}
          <EditorContent editor={editor} />
        </div>

        {linkPopover && (
          <div className="nxe-link-popover" style={{ left: 12, top: 8 }}>
            <input className="nxe-link-input" autoFocus value={linkValue} onChange={(e) => setLinkValue(e.target.value)}
              placeholder="https://…" onKeyDown={(e) => e.key === 'Enter' && applyLink()} />
            <button className="nxe-link-go" onClick={applyLink}><LinkIcon size={13} /></button>
            <button className="nxe-bubble-btn" onClick={() => setLinkPopover(null)}><SvcIcon name="x" size={13} /></button>
          </div>
        )}

        {blockMenuOpen && (
          <div className="nxe-block-context-menu" ref={blockMenuRef} style={{ left: 46, top: 40 }}>
            <div className="nxe-bcm-item" onClick={duplicateBlock}><SvcIcon name="copy" size={14} />{t('editor.duplicateBlock', { defaultValue: '複製區塊' })}</div>
            <div className="nxe-bcm-item" onClick={copyBlockLink}><SvcIcon name="link-2" size={14} />{t('editor.copyLink', { defaultValue: '複製連結' })}</div>
            <div className="nxe-bcm-sep" />
            <div className="nxe-bcm-item" onClick={() => turnBlockInto('paragraph')}><ArrowRightLeft size={14} />{t('editor.toParagraph', { defaultValue: '轉為段落' })}</div>
            <div className="nxe-bcm-item" onClick={() => turnBlockInto('heading1')}><Heading1 size={14} />{t('editor.toHeading', { defaultValue: '轉為大標題' })}</div>
            <div className="nxe-bcm-item" onClick={() => turnBlockInto('taskList')}><ListChecks size={14} />{t('editor.toTodo', { defaultValue: '轉為待辦' })}</div>
            <div className="nxe-bcm-item" onClick={() => setColorSubmenuOpen(v => !v)}><Palette size={14} />{t('editor.color', { defaultValue: '顏色' })}</div>
            {colorSubmenuOpen && (
              <div className="nxe-bcm-colors">
                {BLOCK_COLORS.map(c => <button key={c} className="nxe-bcm-color-swatch" style={{ background: c }} onClick={() => applyBlockColor(c)} />)}
              </div>
            )}
            <div className="nxe-bcm-sep" />
            <div className="nxe-bcm-item danger" onClick={deleteBlock}><SvcIcon name="trash-2" size={14} />{t('editor.deleteBlock', { defaultValue: '刪除區塊' })}</div>
          </div>
        )}
      </div>

      {/* ═══ MOBILE TOOLBAR — docked above on-screen keyboard ═══ */}
      {useMobileUI && (
        <div className="nxe-mobile-toolbar">
          <button className="nxe-mtb-btn" onClick={() => { setBlockQuery(''); setMobileSheetOpen(true) }}
            aria-label={t('editor.insertBlock', { defaultValue: '插入區塊' }) as string}><SvcIcon name="plus" size={19} /></button>
          {/* P1-⑦：spec 要求嘅 primary accessory = Add block／Undo／Redo／Bold／Checklist／Link／AI。
              Undo/Redo 係呢條 bar 之前冇嘅（desktop 一直有）；disabled 跟 editor.can() 同 desktop 一致。 */}
          <button className="nxe-mtb-btn" disabled={!editor.can().undo()} onClick={() => editor.chain().focus().undo().run()}
            aria-label={t('editor.undo', { defaultValue: '復原' }) as string}><Undo2 size={18} /></button>
          <button className="nxe-mtb-btn" disabled={!editor.can().redo()} onClick={() => editor.chain().focus().redo().run()}
            aria-label={t('editor.redo', { defaultValue: '重做' }) as string}><Redo2 size={18} /></button>
          <div className="nxe-mtb-divider" />
          <button className={`nxe-mtb-btn ${editor.isActive('bold') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleBold().run()}
            aria-pressed={editor.isActive('bold')} aria-label={t('editor.bold', { defaultValue: '粗體' }) as string}><Bold size={18} /></button>
          <button className={`nxe-mtb-btn ${editor.isActive('italic') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleItalic().run()}
            aria-pressed={editor.isActive('italic')} aria-label={t('editor.italic', { defaultValue: '斜體' }) as string}><Italic size={18} /></button>
          <button className={`nxe-mtb-btn ${editor.isActive('highlight') ? 'active' : ''}`} onClick={openHlRadial}
            aria-pressed={editor.isActive('highlight')} aria-label={t('editor.highlight', { defaultValue: '螢光標示' }) as string}><Highlighter size={18} /></button>
          <button className={`nxe-mtb-btn ${editor.isActive('link') ? 'active' : ''}`} onClick={openLinkPopover}
            aria-pressed={editor.isActive('link')} aria-label={t('editor.link', { defaultValue: '連結' }) as string}><LinkIcon size={18} /></button>
          <button className={`nxe-mtb-btn ${editor.isActive('bulletList') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleBulletList().run()}
            aria-pressed={editor.isActive('bulletList')} aria-label={t('editor.bulletList', { defaultValue: '項目列表' }) as string}><SvcIcon name="list" size={18} /></button>
          <button className={`nxe-mtb-btn ${editor.isActive('taskList') ? 'active' : ''}`} onClick={() => editor.chain().focus().toggleTaskList().run()}
            aria-pressed={editor.isActive('taskList')} aria-label={t('editor.taskList', { defaultValue: '待辦清單' }) as string}><ListChecks size={18} /></button>
          <div className="nxe-mtb-divider" />
          <button className="nxe-mtb-ai" onClick={() => setAiMenuOpen(true)}><SvcIcon name="sparkles" size={14} /> AI</button>
          <button className="nxe-mtb-kbd-dismiss" onClick={() => (document.activeElement as HTMLElement)?.blur()}
            aria-label={t('editor.hideKeyboard', { defaultValue: '收起鍵盤' }) as string}><SvcIcon name="chevron-down" size={18} /></button>
        </div>
      )}

      {mobileSheetOpen && (
        <div className="nxe-mobile-sheet-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setMobileSheetOpen(false) }}>
          <div className="nxe-mobile-sheet" role="dialog" aria-modal="true"
            aria-label={t('editor.insertBlock', { defaultValue: '插入區塊' }) as string}>
            <div className="nxe-mobile-sheet-handle" />
            {/* P1-⑦：可搜尋（11 個 block 之前要逐格搵）＋ 分組（文字／工作／媒體） */}
            <input className="nxe-sheet-search" value={blockQuery} onChange={(e) => setBlockQuery(e.target.value)}
              placeholder={t('editor.searchBlocks', { defaultValue: '搜尋區塊…' }) as string}
              aria-label={t('editor.searchBlocks', { defaultValue: '搜尋區塊…' }) as string} />
            <div className="sr-only" aria-live="polite">
              {t('editor.blockResults', { defaultValue: '{{n}} 個區塊', n: blockResultCount(MOBILE_BLOCK_TYPES, blockQuery) })}
            </div>
            {mobileBlockGroups.length === 0 ? (
              <div className="nxe-sheet-empty">{t('editor.noBlocks', { defaultValue: '冇符合嘅區塊' })}</div>
            ) : (
              mobileBlockGroups.map(({ group, items }) => (
                <div key={group} className="nxe-sheet-group">
                  <div className="nxe-sheet-group-label">{t(BLOCK_GROUP_I18N[group], { defaultValue: group }) as string}</div>
                  <div className="nxe-mobile-block-grid">
                    {items.map(b => {
                      const Icon = b.icon
                      return (
                        <button key={b.id} className="nxe-mobile-block-item"
                          onClick={() => { b.run(); setBlockQuery(''); setMobileSheetOpen(false) }}>
                          <span className="nxe-mobile-block-icon"><Icon size={19} /></span>
                          <span className="nxe-mobile-block-label">{b.label}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ═══ HIGHLIGHT RADIAL MENU（8 格環 + 自訂色第二行） ═══ */}
      {hlRadial && (
        (() => {
          const cx = Math.min(Math.max(hlRadial.x, 78), window.innerWidth - 78)
          const cy = Math.min(Math.max(hlRadial.y, 84), window.innerHeight - 120)
          return (
            <div ref={hlRadialRef} className="nxe-hl-radial-wrap"
              style={{ position: 'fixed', left: cx, top: cy, zIndex: 60 }}
              onMouseDown={(e) => e.stopPropagation()}>
              {/* 中心：移除 highlight */}
              <button className="nxe-hl-center" title={t('editor.removeHighlight', { defaultValue: '移除 Highlight' })} onClick={clearHl}><SvcIcon name="x" size={13} /></button>
              {/* 8 格環：7 色 + edit */}
              {Array.from({ length: HL_RADIAL_SLOTS }).map((_, i) => {
                const angle = -Math.PI / 2 + (i * 2 * Math.PI) / HL_RADIAL_SLOTS
                const left = Math.round(HL_RADIAL_R * Math.cos(angle))
                const top = Math.round(HL_RADIAL_R * Math.sin(angle))
                if (i < HIGHLIGHT_COLORS.length) {
                  const c = HIGHLIGHT_COLORS[i]
                  return (
                    <button key={c.value} title={t('editor.highlightNamed', { defaultValue: 'Highlight {{name}}', name: t(c.nameKey, { defaultValue: c.fallback }) })}
                      className={`nxe-hl-radial-slot ${editor.isActive('highlight', { color: c.value }) ? 'active' : ''}`}
                      style={{ left, top, background: c.value }}
                      onClick={() => applyHlColor(c.value)} />
                  )
                }
                return (
                  <button key="edit" title={t('editor.customColor', { defaultValue: '自訂顏色' })}
                    className="nxe-hl-radial-slot nxe-hl-radial-edit"
                    style={{ left, top }}
                    onClick={(e) => { e.stopPropagation(); setHlEditOpen(v => !v) }}>
                    <Palette size={12} />
                  </button>
                )
              })}
              {/* 第二行：自訂色（最多 7 個） */}
              {hlCustom.length > 0 && (
                <div className="nxe-hl-custom-row">
                  {hlCustom.map(c => (
                    <button key={c} title={t('editor.customColorNamed', { defaultValue: '自訂 {{hex}}', hex: c })}
                      className={`nxe-hl-custom-swatch ${editor.isActive('highlight', { color: c }) ? 'active' : ''}`}
                      style={{ background: c }}
                      onClick={() => applyHlColor(c)} />
                  ))}
                </div>
              )}
              {/* Edit：native 色盤 */}
              {hlEditOpen && (
                <div className="nxe-hl-edit-pop" onClick={(e) => e.stopPropagation()}>
                  <input type="color" value={hlNewColor} onChange={(e) => setHlNewColor(e.target.value)} />
                  <button className="nxe-hl-edit-add" onClick={addCustomHlColor}><SvcIcon name="check" size={12} />{t('editor.add', { defaultValue: '加入' })}</button>
                </div>
              )}
            </div>
          )
        })()
      )}

      {/* ═══ MOBILE AI SHEET（fallback 版 — AI action 直接寫入 note） ═══ */}
      {aiMenuOpen && useMobileUI && (
        <div className="nxe-mobile-sheet-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setAiMenuOpen(false) }}>
          <div className="nxe-mobile-sheet">
            <div className="nxe-mobile-sheet-handle" />
            {AI_ACTIONS.map(a => {
              const Icon = a.icon
              return (
                <div key={a.id} className="nxe-bcm-item" style={{ padding: '12px 16px', fontSize: 14 }} onClick={() => runAiAction(a.id)}>
                  <Icon size={17} /> {aiLabel(a)}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {onSave && (
        <div className="nxe-footer">
          <div className={`nxe-footer-save${saveState === 'error' ? ' is-error' : ''}`}>
            <span className={`nxe-save-dot ${saveState === 'saving' ? 'saving' : ''}${saveState === 'error' ? ' error' : ''}`} />
            {saveState === 'saving' ? t('editor.saveSaving', { defaultValue: '正在儲存…' })
              : saveState === 'saved' ? t('editor.saveSaved', { defaultValue: '已儲存' })
              : saveState === 'error' ? t('editor.saveError', { defaultValue: '儲存失敗，重試中…' })
              : t('editor.saveReady', { defaultValue: '準備就緒' })}
          </div>
          <div className="nxe-footer-hint">
            <kbd>⌘⇧↑↓</kbd>{t('editor.moveBlock', { defaultValue: '移動區塊 ·' })}<kbd>/</kbd>{t('editor.insert', { defaultValue: '插入 ·' })}<kbd>⌘J</kbd> AI
          </div>
        </div>
      )}
    </div>
  )
}

import { Node, mergeAttributes } from '@tiptap/core'
import Suggestion from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'
import { apiClient } from '../../lib/api'
import i18n from '../../i18n/config'

/* 同上（SlashCommand.ts）：@tiptap/suggestion 2.27 嘅 default pluginKey 係共用
   instance — 唔各自開 key 就會同 SlashCommand 撞（RangeError: Adding different
   instances of a keyed plugin）。 */
export const RecordMentionPluginKey = new PluginKey('recordMention')

/**
 * Notes v2 (T3.1) — @mention / record link chip.
 *
 * Typing `@` opens a cross-entity search popup (contact / company / project /
 * task / touchpoint). Selecting inserts an inline chip node carrying
 * entityType + entityId + label. The note content HTML keeps these spans
 * (data-record-mention), so the host can persist them as note_links rows and
 * re-render the chip after reopening the note.
 */

export interface RecordItem {
  id: string
  type: string
  label: string
  sub?: string
  url?: string
}

const ICONS: Record<string, string> = {
  contact: '👤', company: '🏢', project: '📁', task: '✅', touchpoint: '🔗',
}

export const RecordMention = Node.create({
  name: 'recordMention',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: false,

  addAttributes() {
    return {
      entityType: { default: null },
      entityId: { default: null },
      label: { default: null },
    }
  },

  parseHTML() {
    return [{
      tag: 'span[data-record-mention]',
      getAttrs: (el: any) => ({
        entityType: el.getAttribute('data-entity-type'),
        entityId: el.getAttribute('data-entity-id'),
        label: el.getAttribute('data-label') || (el.textContent || '').replace(/^@/, ''),
      }),
    }]
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, {
      'data-record-mention': 'true',
      'data-entity-type': HTMLAttributes.entityType,
      'data-entity-id': HTMLAttributes.entityId,
      'data-label': HTMLAttributes.label,
      class: 'nxe-mention',
    }), `@${HTMLAttributes.label || ''}`]
  },

  addProseMirrorPlugins() {
    const editor = this.editor
    // 2026-09-11 review T-09: per-editor abort handle — 每個 keystroke 取消上一個未完成嘅搜尋
    let searchAbort: AbortController | null = null
    /* 2026-09-13：draw() 要知用戶打咗字未 —— 未打字（query 空）唔應該報「冇符合」。 */
    let curQuery = ''
    return [
      Suggestion<RecordItem>({
        pluginKey: RecordMentionPluginKey,
        editor,
        char: '@',
        /* ⚠️ 2026-09-13 真兇（手機實測）：
           @tiptap/suggestion 嘅 default 係 `allowedPrefixes = [' ']` —— 即係只有
           「空格之後」打 @ 才會觸發 suggestions。用戶喺文字中間打（例如「客戶：@kin」
           或者「填充行 40@kin」）→ popup 完全唔出，感覺就係「@ 搜唔到 object」。
           設 null = 任何前置字元都接受。 */
        allowedPrefixes: null,
        allowSpaces: false,
        startOfLine: false,
        items: async ({ query }) => {
          curQuery = query
          if (!query || query.trim().length < 1) return []
          // 180ms debounce + abort：快速輸入唔會產生重疊 request，亦唔會用過期結果覆蓋新結果
          searchAbort?.abort()
          const ctrl = new AbortController()
          searchAbort = ctrl
          await new Promise((r) => setTimeout(r, 180))
          if (ctrl.signal.aborted) return []
          try {
            const res: any = await apiClient.get('/api/v1/crm/search', {
              params: { q: query, limit: '8', types: 'contact,company,project,task,touchpoint' },
              signal: ctrl.signal,
            })
            if (ctrl.signal.aborted) return []
            /* ⚠️ 2026-09-13 修：backend `/crm/search` 回嘅係 {results: […], total: n}，
               原本只讀 `res.items` → rows 永遠係 []，popup 永遠出「冇符合嘅 record」，
               即係「@ record 加唔到 object」。順手容忍 items（向後／向前兼容）。 */
            const rows: any[] = Array.isArray(res) ? res : (res?.results || res?.items || [])
            return rows.slice(0, 8).map(r => ({ id: String(r.id), type: String(r.type), label: String(r.label || ''), sub: r.sub, url: r.url }))
          } catch { return [] }
        },
        command: ({ editor: ed, range, props }) => {
          ed.chain().focus().insertContentAt(range, [
            { type: 'recordMention', attrs: { entityType: props.type, entityId: props.id, label: props.label } },
            { type: 'text', text: ' ' },
          ]).run()
        },
        render: () => {
          let el: HTMLDivElement | null = null
          let items: RecordItem[] = []
          let selected = 0
          /* aria-live region 喺 onStart 建立，之後每次 draw 由 el 拎返（唔用 closure 變數，
             避免 TS 對 captured let 收窄成 never） */
          const liveText = (msg: string) => {
            const lv = el?.querySelector<HTMLDivElement>('.nxe-mention-live')
            if (lv) lv.textContent = msg
          }

          /* 2026-09-11 review T-05 / F-06：
             ① XSS — 原本 `row.innerHTML` 直插 `${it.label}`，label 嚟自 /crm/search
                （contact / company / project 名），即係 CRM 使用者可控資料。一個叫
                `<img src=x onerror=…>` 嘅 contact 就係 stored XSS。改為逐個 element +
                `textContent` 賦值，任何 HTML 字元都只會當純文字。
             ② ARIA — listbox / option / aria-selected / aria-activedescendant + 一個
                aria-live 區域播報結果數，螢幕閱讀器先感知到選單彈出同選中項。 */
          const draw = () => {
            if (!el) return
            // 只清走上一輪嘅 row／empty，保留 aria-live region（清空 textContent 會連佢一齊殺）
            el.querySelectorAll('.nxe-mention-row, .nxe-mention-empty').forEach(n => n.remove())
            if (!items.length) {
              const empty = document.createElement('div')
              empty.className = 'nxe-mention-empty'
              /* 2026-09-13 修（用戶報）：一撳 @ 就出「冇符合嘅 record」——但用戶根本未打字，
                 冇搜過就唔存在「冇符合」。空 query → 出提示；真係搜唔到才出「冇符合」。
                 （順手 i18n：原本呢句同下面結果數都 hardcode 中文，違反 UI 文字全 i18n 規矩。） */
              const typed = curQuery.trim().length > 0
              empty.textContent = typed
                ? i18n.t('editor.mentionNoMatch', { defaultValue: '冇符合嘅 record' })
                : i18n.t('editor.mentionHint', { defaultValue: '輸入關鍵字搵 record' })
              el.appendChild(empty)
              el.removeAttribute('aria-activedescendant')
              // hint 唔經 aria-live 播報（唔係結果、亦唔係錯誤）；真「冇符合」才播
              liveText(typed ? empty.textContent : '')
              return
            }
            items.forEach((it, i) => {
              const row = document.createElement('div')
              row.className = 'nxe-mention-row' + (i === selected ? ' active' : '')
              row.id = `nxe-mention-opt-${i}`
              row.setAttribute('role', 'option')
              row.setAttribute('aria-selected', String(i === selected))

              const ico = document.createElement('span')
              ico.className = 'nxe-mention-ico'
              ico.textContent = ICONS[it.type] || '•'
              const label = document.createElement('span')
              label.className = 'nxe-mention-label'
              label.textContent = it.label || ''
              const sub = document.createElement('span')
              sub.className = 'nxe-mention-sub'
              sub.textContent = it.sub || it.type

              row.append(ico, label, sub)
              /* 2026-09-13：pointerdown 取代 mousedown。手機 touch 嘅 mousedown 係
                 合成事件，喺可捲動 popup 上面經常唔 fire（要 tap 兩次／撳唔到）；
                 pointerdown 統一覆蓋 mouse / touch / pen，一樣 preventDefault 保 caret。 */
              row.addEventListener('pointerdown', e => {
                e.preventDefault()
                choose(i)
              })
              el!.appendChild(row)
            })
            el.setAttribute('aria-activedescendant', `nxe-mention-opt-${selected}`)
            liveText(
              i18n.t('editor.mentionResults', {
                n: items.length,
                label: items[selected]?.label || '',
                defaultValue: '{{n}} 個結果：{{label}}',
              })
            )
          }

          const choose = (i: number) => {
            const it = items[i]
            if (it) (el as any).__cmd?.(it)
          }

          /* ⚠️ 2026-09-13 手機實測修正：
             ① 一定要用 window.visualViewport 而唔係 innerHeight —— 軟鍵盤一開，
                可視高度淨返一半，原本 `top = caret.bottom + 6` 會令 popup 跌落
                鍵盤後面（用戶睇唔到、撳唔到，感覺就係「@ 冇嘢出」）。
             ② 下面唔夠位就反上去 caret 對上；左右／上下都夾返入可視範圍。
             ③ max-height 唔好高過半個可視高度。 */
          const place = (props: any) => {
            if (!el) return
            const rect = props.clientRect?.()
            if (!rect) return
            const vv = window.visualViewport
            const vw = vv?.width ?? window.innerWidth
            const vh = vv?.height ?? window.innerHeight
            const vTop = vv?.offsetTop ?? 0
            const w = el.offsetWidth || 240
            const h = Math.min(el.scrollHeight || 260, 260)
            el.style.maxHeight = `${Math.max(120, Math.min(260, Math.round(vh * 0.5)))}px`
            el.style.maxWidth = `${Math.round(vw - 16)}px`
            const left = Math.max(8, Math.min(Math.round(rect.left), Math.round(vw - w - 8)))
            const below = rect.bottom + 6
            const above = rect.top - h - 6
            let top = below + h <= vTop + vh - 8 ? below : above
            top = Math.max(vTop + 8, Math.min(top, vTop + vh - h - 8))
            el.style.left = `${left}px`
            el.style.top = `${Math.round(top)}px`
          }

          return {
            onStart: (props: any) => {
              items = props.items || []
              selected = 0
              el = document.createElement('div')
              el.className = 'nxe-mention-popup'
              el.setAttribute('role', 'listbox')
              el.setAttribute('aria-label', '記錄搜尋結果')
              // 螢幕閱讀器播報區（視覺隱藏）— 每次 draw 更新結果數／選中項
              const live = document.createElement('div')
              live.className = 'nxe-mention-live sr-only'
              live.setAttribute('aria-live', 'polite')
              el.appendChild(live)
              ;(el as any).__cmd = props.command
              document.body.appendChild(el)
              draw()
              place(props)
            },
            onUpdate: (props: any) => {
              items = props.items || []
              selected = 0
              if (el) (el as any).__cmd = props.command
              draw()
              place(props)
            },
            onKeyDown: (props: any) => {
              if (props.event.key === 'Escape') { el?.remove(); el = null; return true }
              if (!items.length) return false
              if (props.event.key === 'ArrowDown') { selected = (selected + 1) % items.length; draw(); return true }
              if (props.event.key === 'ArrowUp') { selected = (selected - 1 + items.length) % items.length; draw(); return true }
              if (props.event.key === 'Enter') { choose(selected); return true }
              return false
            },
            onExit: () => { el?.remove(); el = null },
          }
        },
      }),
    ]
  },
})

/** Extract record mentions from saved note HTML → for note_links persistence. */
export function extractRecordMentions(html: string): { entity_type: string; entity_id: string; label: string }[] {
  if (!html) return []
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const out: { entity_type: string; entity_id: string; label: string }[] = []
    doc.querySelectorAll('span[data-record-mention]').forEach(el => {
      const t = el.getAttribute('data-entity-type')
      const id = el.getAttribute('data-entity-id')
      if (t && id) out.push({ entity_type: t, entity_id: id, label: el.getAttribute('data-label') || '' })
    })
    return out
  } catch { return [] }
}

import { Extension } from '@tiptap/core'
import Suggestion from '@tiptap/suggestion'
import { PluginKey } from '@tiptap/pm/state'
import i18n from '../../i18n/config'

/* Slash menu 項目（原喺 components/editor/SlashMenu.tsx）。該檔自 v6.51「slash menu 改
   dispatch custom event」之後已經冇任何 runtime 引用（只剩 `import type`），live 嘅
   slash menu 係 NexusEditor.tsx 直接 render（見 `nxe-slash-menu` 嗰段）——2026-09-11
   已刪除該死檔，type 搬返嚟呢度做單一來源。 */
export interface SlashItem { id: string; label: string; sub: string; group: string }

/* ⚠️ 一定要有自己嘅 pluginKey（2026-09-11 T1.4 實證）：
   @tiptap/suggestion 2.27 嘅 `SuggestionPluginKey` 係 module-level 共用 instance，
   Suggestion() 唔傳 pluginKey 就用嗰個共用 key。NexusEditor 同時掛 SlashCommand（/）
   同 RecordMention（@）兩個 Suggestion extension → 兩個 plugin 撞同一個 key →
   ProseMirror Configuration ctor 拋 `RangeError: Adding different instances of a
   keyed plugin (suggestion$)` → 成個編輯器（連 host page）render 期間炸。 */
export const SlashCommandPluginKey = new PluginKey('slashCommand')

/* Notion-style "/" slash command — same interaction model as
   Notion's block insert menu: type "/", get a filtered list,
   arrow keys to navigate, Enter to insert, Esc to dismiss.

   ⚠️ v6.51 fix: 原本用 ReactRenderer + tippy 整 popup — React 19 下
   tippy 將 React-managed DOM 搬去 body，NexusEditor re-render 時 React
   commit 撞 DOM 而 crash（insertBefore not a child of this node）。
   而家改為 dispatch custom events，由 NexusEditor 用 React state 自己
   render slash menu（同 selection bubble 一致），完全唔經 tippy。 */

/* i18n（t12）：module scope 冇 hook → item 只存「key + 原文 fallback」，
   真正翻譯喺 buildSlashItems() 開選單時用 i18n.t() 做。
   ⚠️ 一定要 function，唔可以係 const array：const 只會喺 import 時翻一次，
   之後換語言會殘留舊語言（同 NexusEditor 嘅 AI_ACTIONS 同一個坑）。
   sub 係英文小提示（zh-TW 介面本身都係咁顯示），只有本身寫中文嗰兩條要翻。 */
const SLASH_ITEM_DEFS: Array<{
  id: string
  labelKey: string
  label: string
  sub: string
  subKey?: string
  groupKey: string
  group: string
}> = [
  { id: 'h1', labelKey: 'editor.slashH1', label: '大標題', sub: 'Heading 1', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'h2', labelKey: 'editor.slashH2', label: '中標題', sub: 'Heading 2', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'h3', labelKey: 'editor.slashH3', label: '小標題', sub: 'Heading 3', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'bullet', labelKey: 'editor.bulletList', label: '項目列表', sub: 'Bulleted list', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'ordered', labelKey: 'editor.slashOrdered', label: '編號列表', sub: 'Numbered list', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'task', labelKey: 'editor.taskList', label: '待辦清單', sub: 'Task list', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'quote', labelKey: 'editor.slashQuote', label: '引言', sub: 'Quote', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'divider', labelKey: 'editor.slashDivider', label: '分隔線', sub: 'Divider', groupKey: 'editor.slashGroupBasic', group: '基本' },
  { id: 'table', labelKey: 'editor.slashTable', label: '表格', sub: 'Insert table', groupKey: 'editor.slashGroupAdvanced', group: '進階' },
  { id: 'image', labelKey: 'editor.slashImageUpload', label: '圖片上載', sub: 'Upload image', groupKey: 'editor.slashGroupAdvanced', group: '進階' },
  { id: 'image-url', labelKey: 'editor.slashImageUrl', label: '圖片連結', sub: 'Image from URL', groupKey: 'editor.slashGroupAdvanced', group: '進階' },
  { id: 'code', labelKey: 'editor.slashCode', label: '程式碼區塊', sub: 'Code block', groupKey: 'editor.slashGroupAdvanced', group: '進階' },
  { id: 'ai', labelKey: 'editor.slashAiContinue', label: 'AI 續寫', sub: '由 AI 接續內容', subKey: 'editor.slashSubAiContinue', groupKey: 'editor.slashGroupAi', group: 'AI' },
  { id: 'ai-summarize', labelKey: 'editor.slashAiSummarize', label: 'AI 摘要', sub: '為以上內容生成摘要', subKey: 'editor.slashSubAiSummarize', groupKey: 'editor.slashGroupAi', group: 'AI' },
]

/** 每次開選單／改 query 都重新建 → 跟隨目前介面語言（亦令搜尋 match 到畫面上嘅字） */
export function buildSlashItems(): SlashItem[] {
  return SLASH_ITEM_DEFS.map((d) => ({
    id: d.id,
    label: i18n.t(d.labelKey, { defaultValue: d.label }) as string,
    sub: d.subKey ? (i18n.t(d.subKey, { defaultValue: d.sub }) as string) : d.sub,
    group: i18n.t(d.groupKey, { defaultValue: d.group }) as string,
  }))
}

export function executeSlashCommand(editor: any, id: string, range?: any) {
  if (!editor) return
  // delete "/" 字元（suggestion range）先 — 唔 delete 會殘留
  if (range) {
    editor.chain().focus().deleteRange(range).run()
  }
  const chain = editor.chain().focus()
  switch (id) {
    case 'h1': chain.setHeading({ level: 1 }).run(); break
    case 'h2': chain.setHeading({ level: 2 }).run(); break
    case 'h3': chain.setHeading({ level: 3 }).run(); break
    case 'bullet': chain.toggleBulletList().run(); break
    case 'ordered': chain.toggleOrderedList().run(); break
    case 'task': chain.toggleTaskList().run(); break
    case 'quote': chain.toggleBlockquote().run(); break
    case 'divider': chain.setHorizontalRule().run(); break
    case 'code': chain.toggleCodeBlock().run(); break
    case 'table': chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(); break
    case 'image': {
      // 2026-09-11 review T-07 / F-08：原本淨係 window.prompt 貼 URL，同 Video/Audio
      // 已經有嘅上載 flow 唔一致。改為 dispatch 事件，由 NexusEditor 用返
      // 同一條 pickMedia('image') → POST /api/v1/crm/notes/media。
      // 想貼外部連結就用下面 'image-url'（prompt 保留做 fallback，唔再係唯一路徑）。
      window.dispatchEvent(new CustomEvent('nexus-editor:pick-media', { detail: { kind: 'image' } }))
      break
    }
    case 'image-url': {
      const url = window.prompt(i18n.t('editor.imageUrlPrompt', { defaultValue: '圖片網址 (URL)：' }) as string)
      if (url) chain.setImage({ src: url }).run()
      break
    }
    case 'ai':
    case 'ai-summarize':
      window.dispatchEvent(new CustomEvent('nexus-editor:ai-slash', { detail: { id } }))
      break
  }
}

export const SlashCommand = Extension.create({
  name: 'slashCommand',
  addOptions() {
    return {
      suggestion: {
        char: '/',
        startOfLine: false,
        command: ({ editor, props }: any) => {
          executeSlashCommand(editor, props.id as string)
        },
      },
    }
  },
  addProseMirrorPlugins() {
    return [
      Suggestion({
        pluginKey: SlashCommandPluginKey,
        editor: this.editor,
        char: '/',
        items: ({ query }: { query: string }): SlashItem[] =>
          buildSlashItems().filter(i => (i.label + i.sub).toLowerCase().includes(query.toLowerCase())).slice(0, 10),
        render: () => {
          return {
            onStart: (props: any) => {
              const rect = props.clientRect()
              window.dispatchEvent(new CustomEvent('nexus-editor:slash-open', {
                detail: { x: rect?.left ?? 0, y: (rect?.bottom ?? 0) + 6, range: props.range, editor: props.editor },
              }))
            },
            onUpdate: (props: any) => {
              const rect = props.clientRect()
              window.dispatchEvent(new CustomEvent('nexus-editor:slash-update', {
                detail: { x: rect?.left ?? 0, y: (rect?.bottom ?? 0) + 6, range: props.range, query: props.query, items: props.items },
              }))
            },
            onKeyDown: (props: any) => {
              if (props.event.key === 'Escape') {
                window.dispatchEvent(new CustomEvent('nexus-editor:slash-close'))
                return true
              }
              if (props.event.key === 'ArrowUp' || props.event.key === 'ArrowDown') {
                window.dispatchEvent(new CustomEvent('nexus-editor:slash-keydown', { detail: { key: props.event.key } }))
                return true
              }
              if (props.event.key === 'Enter') {
                window.dispatchEvent(new CustomEvent('nexus-editor:slash-enter'))
                return true
              }
              return false
            },
            onExit: () => {
              window.dispatchEvent(new CustomEvent('nexus-editor:slash-close'))
            },
          }
        },
      }),
    ]
  },
})

/**
 * blockSheet.ts — mobile「插入區塊」sheet 嘅搜尋／分組純邏輯（P1-⑦）。
 *
 * 點解要抽做 pure function：NexusEditor 本身 900+ 行、仲要係 editor 共用組件，
 * DOM 層嘅嘢交 Playwright 驗；但「filter 得唔得、group 次序對唔對」係可以
 * unit test 鎖死嘅，放喺呢度每次改都即刻知。
 *
 * 分組用 spec 嘅三分法（文字／工作／媒體），唔係 slash menu 嘅基本／進階 ——
 * 手機 sheet 要嘅係「我想插入邊類內容」，唔係「呢個功能難唔難」。
 */

export type BlockGroup = 'text' | 'work' | 'media'

/** 分組顯示次序（跟 spec：Text → Work → Media） */
export const BLOCK_GROUP_ORDER: BlockGroup[] = ['text', 'work', 'media']

/** 分組對應嘅 i18n key（唔喺度寫死中文，UI 文字一律走 i18n） */
export const BLOCK_GROUP_I18N: Record<BlockGroup, string> = {
  text: 'editor.blockGroupText',
  work: 'editor.blockGroupWork',
  media: 'editor.blockGroupMedia',
}

export interface SearchableBlock {
  id: string
  label: string
  /** 英文／拼音關鍵字，令中英夾雜嘅用戶都搵得到（例如打 "table" 搵「表格」） */
  keywords?: string[]
  group: BlockGroup
}

/** 正規化：trim + lower，令「  Table 」都搵得到 */
export function normalizeQuery(q: string): string {
  return (q || '').trim().toLowerCase()
}

/** 一隻 block 係唔係 match query（空 query = 全部） */
export function blockMatches(block: SearchableBlock, query: string): boolean {
  const q = normalizeQuery(query)
  if (!q) return true
  const hay = [block.label, ...(block.keywords || [])].join(' ').toLowerCase()
  return hay.includes(q)
}

/**
 * Filter + 按 spec 次序分組。
 *
 * 空 query：所有 block 都出，而且**保持原本（策劃好嘅）次序**
 * 有 query：分組次序不變，但組內按原本次序
 * 冇 match：回空 array（UI 要自己出「冇符合」而唔係靜靜地空白）
 */
export function groupBlocks<T extends SearchableBlock>(blocks: T[], query: string): Array<{ group: BlockGroup; items: T[] }> {
  const kept = blocks.filter((b) => blockMatches(b, query))
  if (kept.length === 0) return []
  const used = BLOCK_GROUP_ORDER.filter((g) => kept.some((b) => b.group === g))
  /* 有未知 group（將來加）都要出得返，唔好靜靜地唔見咗 */
  const unknowns = Array.from(new Set(kept.map((b) => b.group))).filter((g) => !BLOCK_GROUP_ORDER.includes(g)) as BlockGroup[]
  return [...used, ...unknowns].map((group) => ({ group, items: kept.filter((b) => b.group === group) }))
}

/** 搜尋結果總數（螢幕閱讀器 live region 用） */
export function blockResultCount(blocks: SearchableBlock[], query: string): number {
  return blocks.filter((b) => blockMatches(b, query)).length
}

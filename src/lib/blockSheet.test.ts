import { describe, expect, it } from 'vitest'
import { BLOCK_GROUP_ORDER, blockMatches, blockResultCount, groupBlocks, normalizeQuery } from './blockSheet'

type B = { id: string; label: string; keywords?: string[]; group: 'text' | 'work' | 'media' }

/* 用真實 MOBILE_BLOCK_TYPES 嘅形狀（NexusEditor 內），唔另作一套 */
const BLOCKS: B[] = [
  { id: 'h1', label: '大標題', keywords: ['heading', 'h1'], group: 'text' },
  { id: 'h2', label: '中標題', keywords: ['heading', 'h2'], group: 'text' },
  { id: 'bullet', label: '項目列表', keywords: ['bullet', 'list'], group: 'text' },
  { id: 'ordered', label: '編號列表', keywords: ['numbered', 'ordered'], group: 'text' },
  { id: 'quote', label: '引言', keywords: ['quote'], group: 'text' },
  { id: 'task', label: '待辦清單', keywords: ['task', 'todo', 'checklist'], group: 'work' },
  { id: 'table', label: '表格', keywords: ['table'], group: 'work' },
  { id: 'image', label: '圖片', keywords: ['image', 'photo'], group: 'media' },
  { id: 'video', label: '影片', keywords: ['video'], group: 'media' },
  { id: 'file', label: '附件', keywords: ['file', 'attach'], group: 'media' },
]

describe('normalizeQuery', () => {
  it('trim + lower', () => {
    expect(normalizeQuery('  Table ')).toBe('table')
    expect(normalizeQuery(undefined as unknown as string)).toBe('')
  })
})

describe('blockMatches', () => {
  it('空 query = 全部', () => {
    expect(BLOCKS.every((b) => blockMatches(b, ''))).toBe(true)
  })
  it('中文 label 部分命中', () => {
    expect(blockMatches(BLOCKS[0], '標題')).toBe(true)
  })
  it('英文 keyword 命中（中英夾雜用戶）', () => {
    expect(blockMatches(BLOCKS[6], 'table')).toBe(true)
    expect(blockMatches(BLOCKS[5], 'checklist')).toBe(true)
  })
  it('大小寫／前後空白唔影響', () => {
    expect(blockMatches(BLOCKS[6], '  TABLE  ')).toBe(true)
  })
  it('唔中就 false', () => {
    expect(blockMatches(BLOCKS[6], 'zzzz')).toBe(false)
  })
})

describe('groupBlocks', () => {
  it('空 query：全部出，而且分 3 組按 spec 次序 text → work → media', () => {
    const g = groupBlocks(BLOCKS, '')
    expect(g.map((x) => x.group)).toEqual(['text', 'work', 'media'])
    expect(g.reduce((n, x) => n + x.items.length, 0)).toBe(BLOCKS.length)
  })

  it('分組次序唔受輸入次序影響（打亂輸入都一樣）', () => {
    /* 故意用亂序輸入：media → work → text */
    const shuffled = [BLOCKS[9], BLOCKS[6], BLOCKS[0], BLOCKS[5]]
    const g = groupBlocks(shuffled, '')
    expect(g.map((x) => x.group)).toEqual(['text', 'work', 'media'])
    expect(g[0].items.map((i) => i.id)).toEqual(['h1'])
    expect(g[2].items.map((i) => i.id)).toEqual(['file'])
  })

  it('中文 query：只出 text 組嘅兩個標題', () => {
    const g = groupBlocks(BLOCKS, '標題')
    expect(g).toHaveLength(1)
    expect(g[0].group).toBe('text')
    expect(g[0].items.map((i) => i.id)).toEqual(['h1', 'h2'])
  })

  it('英文 query 跨組：list（text 嘅項目列表 + work 嘅 checklist）', () => {
    /* 'list' 命中 bullet（label「項目列表」＋keyword list）同 task（keyword checklist） */
    const g = groupBlocks(BLOCKS, 'list')
    expect(g.map((x) => x.group)).toEqual(['text', 'work'])
    expect(g[0].items.some((i) => i.id === 'bullet')).toBe(true)
    expect(g[1].items.some((i) => i.id === 'task')).toBe(true)
  })

  it('冇 match → 空 array（UI 要出「冇符合」而唔係空白）', () => {
    expect(groupBlocks(BLOCKS, 'zzzz')).toEqual([])
  })

  it('組內保持原本策劃次序（唔會調亂）', () => {
    const g = groupBlocks(BLOCKS, '')
    expect(g[0].items.map((i) => i.id)).toEqual(['h1', 'h2', 'bullet', 'ordered', 'quote'])
  })

  it('將來新增未知 group 都唔會靜靜地消失（排最後）', () => {
    const withNew = [...BLOCKS, { id: 'x', label: 'CRM 記錄', group: 'crm' as unknown as 'text' }]
    const g = groupBlocks(withNew, '')
    expect(g.map((x) => x.group)).toEqual([...BLOCK_GROUP_ORDER, 'crm'])
    expect(g[g.length - 1].items[0].id).toBe('x')
  })
})

describe('blockResultCount', () => {
  it('數 match 數量（live region 用）', () => {
    expect(blockResultCount(BLOCKS, '')).toBe(BLOCKS.length)
    expect(blockResultCount(BLOCKS, '標題')).toBe(2)
    expect(blockResultCount(BLOCKS, 'zzzz')).toBe(0)
  })
})

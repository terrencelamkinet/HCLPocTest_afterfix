import type { FieldConfig } from '../module-types'

/** 可以由 CSV 入／出嘅欄位（跳過系統生成同檔案欄位） */
const SKIP_TYPES = ['rollup', 'formula', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by', 'files', 'rich_text']

export function csvFields(fields: FieldConfig[]): FieldConfig[] {
  return fields.filter(f => !SKIP_TYPES.includes(f.type))
}

export function csvColumn(f: FieldConfig): string {
  return (f as any).apiKey || f.key
}

function esc(v: unknown): string {
  const s = v == null ? '' : String(v)
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

/** 產生 CSV（加 BOM，令 Excel 正確顯示中文） */
export function buildCsv(fields: FieldConfig[], rows: Record<string, any>[]): string {
  const cols = csvFields(fields)
  const lines = [cols.map(csvColumn).join(',')]
  for (const r of rows) {
    lines.push(
      cols
        .map(f => {
          const raw = r[csvColumn(f)] ?? r[f.key]
          if (Array.isArray(raw)) return esc(raw.join('|'))
          if (raw && typeof raw === 'object') return esc((raw as any).name || (raw as any).title || '')
          return esc(raw)
        })
        .join(','),
    )
  }
  return '\uFEFF' + lines.join('\r\n')
}

/** 解析 CSV — 支援 quoted field / 逗號 / 換行 / CRLF / BOM */
export function parseCsv(text: string): { headers: string[]; rows: string[][] } {
  const s = text.replace(/^\uFEFF/, '')
  const out: string[][] = []
  let row: string[] = []
  let cur = ''
  let q = false
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (q) {
      if (c === '"') {
        if (s[i + 1] === '"') { cur += '"'; i++ } else q = false
      } else cur += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(cur); cur = '' }
    else if (c === '\n') { row.push(cur); out.push(row); row = []; cur = '' }
    else if (c === '\r') { /* skip */ }
    else cur += c
  }
  if (cur !== '' || row.length) { row.push(cur); out.push(row) }
  const nonEmpty = out.filter(r => r.some(x => (x ?? '').trim() !== ''))
  const headers = (nonEmpty.shift() || []).map(h => h.trim())
  return { headers, rows: nonEmpty }
}

export interface RowIssue {
  row: number
  column: string
  message: string
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** 先 scan：逐行驗證，回傳所有問題（唔會寫入任何資料） */
export function scanRows(
  fields: FieldConfig[],
  headers: string[],
  rows: string[][],
): { issues: RowIssue[]; unknownColumns: string[]; mapped: Record<string, any>[] } {
  const cols = csvFields(fields)
  const byColumn = new Map<string, FieldConfig>()
  cols.forEach(f => byColumn.set(csvColumn(f), f))
  const idx = new Map<string, number>()
  headers.forEach((h, i) => idx.set(h, i))

  const unknownColumns = headers.filter(h => h && !byColumn.has(h))
  const issues: RowIssue[] = []
  const mapped: Record<string, any>[] = []

  rows.forEach((r, ri) => {
    const out: Record<string, any> = {}
    for (const f of cols) {
      const col = csvColumn(f)
      const i = idx.get(col)
      const raw = i === undefined ? '' : (r[i] ?? '').trim()
      const label = f.label || col

      if (!raw) {
        if (f.required) issues.push({ row: ri + 1, column: col, message: `${label} 係必填，但空白` })
        out[col] = null
        continue
      }

      if (f.type === 'number') {
        const n = Number(raw.replace(/[$,\s]/g, ''))
        if (Number.isNaN(n)) { issues.push({ row: ri + 1, column: col, message: `${label} 應該係數字，收到「${raw}」` }); continue }
        out[col] = n
      } else if (f.type === 'date') {
        const d = new Date(raw)
        if (Number.isNaN(d.getTime())) { issues.push({ row: ri + 1, column: col, message: `${label} 日期格式唔啱（建議 YYYY-MM-DD），收到「${raw}」` }); continue }
        out[col] = raw
      } else if (f.type === 'select') {
        const opts = (f.options || []).map((o: any) => String(o.value ?? o))
        if (opts.length && !opts.includes(raw)) { issues.push({ row: ri + 1, column: col, message: `${label} 只可以係：${opts.join(' / ')}，收到「${raw}」` }); continue }
        out[col] = raw
      } else if (f.type === 'multi_select') {
        out[col] = raw.split('|').map(x => x.trim()).filter(Boolean)
      } else if (f.type === 'checkbox') {
        out[col] = /^(1|true|yes|y|是|✓)$/i.test(raw)
      } else if (f.type === 'relation') {
        if (!UUID_RE.test(raw)) issues.push({ row: ri + 1, column: col, message: `${label} 需要係記錄 ID（UUID）；Demo CSV 已填好可直接用，收到「${raw}」` })
        else out[col] = raw
      } else {
        if (raw.length > 2000) issues.push({ row: ri + 1, column: col, message: `${label} 太長（${raw.length} 字）` })
        out[col] = raw
      }
    }
    mapped.push(out)
  })

  return { issues, unknownColumns, mapped }
}

/** 由 config 產生 5 條模擬記錄（每條盡量填滿所有欄位） */
export async function buildDemoRows(fields: FieldConfig[], apiClient: any): Promise<Record<string, string>[]> {
  const cols = csvFields(fields)
  // relation 欄位：攞該 resource 第一條記錄嘅 id，令 Demo 直接上載得入
  const relCache = new Map<string, string>()
  for (const f of cols) {
    const res = (f as any).relation?.resource
    if (f.type !== 'relation' || !res || relCache.has(res)) continue
    try {
      // users 唔喺 /crm/<res> 之下，要用 todo/users（回 array）；其他 resource 回 {items}
      const url = res === 'users' ? '/api/v1/crm/todo/users' : `/api/v1/crm/${res}?limit=1`
      const d = await apiClient.get(url)
      const list = Array.isArray(d) ? d : (d?.items || [])
      const first = list[0]
      relCache.set(res, first?.id || '')
    } catch { relCache.set(res, '') }
  }

  const pad = (d: Date) => d.toISOString().slice(0, 10)
  const rows: Record<string, string>[] = []
  for (let i = 1; i <= 5; i++) {
    const row: Record<string, string> = {}
    for (const f of cols) {
      const col = csvColumn(f)
      const label = f.label || f.key
      let v = ''
      switch (f.type) {
        case 'number':
          v = String((f as any).format === 'hkd' ? 12000 + i * 2500 : 10 + i)
          break
        case 'date': {
          const d = new Date(); d.setDate(d.getDate() + i); v = pad(d); break
        }
        case 'select':
          v = String(((f.options || [])[0] as any)?.value ?? '')
          break
        case 'multi_select':
          v = String(((f.options || [])[0] as any)?.value ?? '')
          break
        case 'checkbox':
          v = i % 2 === 1 ? 'TRUE' : 'FALSE'
          break
        case 'relation':
          v = relCache.get((f as any).relation?.resource) || ''
          break
        case 'email':
          v = `demo${i}@example.com`
          break
        case 'phone':
          v = `+852 9000 000${i}`
          break
        default:
          v = `${label} Demo ${i}`
      }
      row[col] = v
    }
    rows.push(row)
  }
  return rows
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

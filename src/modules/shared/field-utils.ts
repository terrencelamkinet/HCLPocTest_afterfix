import type { FieldConfig } from '../module-types'

export function buildPayload(form: Record<string, any>, fields: FieldConfig[]): Record<string, any> {
  const payload: Record<string, any> = {}
  for (const f of fields) {
    if (['rollup', 'formula', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by'].includes(f.type)) continue
    const val = form[f.key]
    const targetKey = f.apiKey || f.key
    if (f.type === 'multi_select') payload[targetKey] = Array.isArray(val) ? val : []
    else if (f.type === 'relation') payload[targetKey] = val || null
    else if (f.type === 'checkbox') payload[targetKey] = !!val
    else if (f.type === 'number') payload[targetKey] = val ? Number(val) : null
    else payload[targetKey] = val || null
  }
  return payload
}

export function defaultForm(fields: FieldConfig[]): Record<string, any> {
  const form: Record<string, any> = {}
  for (const f of fields) {
    if (['rollup', 'formula', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by'].includes(f.type)) continue
    if (f.type === 'multi_select' || f.type === 'files') form[f.key] = []
    else if (f.type === 'checkbox') form[f.key] = false
    else form[f.key] = ''
  }
  return form
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) }
  catch { return '—' }
}

export function formatRelativeDate(d: string): string {
  if (!d) return ''
  const diff = Date.now() - new Date(d).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return formatDate(d)
}

export function formatAmount(v: number | null): string {
  if (v == null) return '$0'
  return `$${v.toLocaleString()}`
}

export function apiErrorToString(e: any): string {
  if (e && typeof e.detail === 'string') return e.detail
  if (e && Array.isArray(e.detail)) {
    return e.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
  }
  if (e && typeof e.detail === 'object') return JSON.stringify(e.detail)
  return e?.message || 'An error occurred'
}

export function formatFieldValue(value: any, field: FieldConfig): string {
  if (value == null) return '—'
  if (field.type === 'relation' && typeof value === 'object') return (value as any).name || (value as any).title || '—'
  if (field.type === 'multi_select' && Array.isArray(value)) return value.join(', ')
  if (field.type === 'date' || field.type === 'created_time' || field.type === 'last_edited_time') return formatDate(value)
  if (field.type === 'number' && field.format === 'hkd') return formatAmount(value)
  if (field.type === 'number' && field.format === 'percent') return `${value}%`
  if (field.type === 'checkbox') return value ? '✅' : '—'
  return String(value)
}

export function pickFormValue(entity: any, field: FieldConfig): any {
  const val = entity?.[field.key]
  if (val == null) {
    if (field.type === 'multi_select' || field.type === 'files') return []
    if (field.type === 'checkbox') return false
    return ''
  }
  if (field.type === 'relation' && typeof val === 'object') return val.id || ''
  if (field.type === 'relation' && typeof val === 'string') return val
  return val
}

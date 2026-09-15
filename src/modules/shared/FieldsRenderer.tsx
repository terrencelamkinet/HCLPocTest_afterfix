import type { FieldConfig } from '../module-types'
import { optionColorToClass } from '../module-types'
import { formatDate, formatRelativeDate, formatAmount } from './field-utils'
import EntitySearch from './EntitySearch'
import { isModuleEnabled } from '../enabled-modules'
import { useTranslation } from 'react-i18next'
import { useMemo, useState, useRef, useEffect } from 'react'
import { localizeFieldLabel } from './labels'
import SelectCombobox from './SelectCombobox'
import NexusEditor from '../../components/editor/NexusEditor'
import { apiClient } from '../../lib/api'

const RELATION_ROUTES: Record<string, string> = {
  contacts: '/contacts',
  companies: '/companies',
  projects: '/projects',
  tasks: '/tasks',
  touchpoints: '/touchpoints',
  users: '',
}

// relation resource → entity-search URL (users live under /todo/users,
// not /crm/users, and are email-keyed)
const RELATION_SEARCH_URL: Record<string, string> = {
  contacts: '/api/v1/crm/contacts',
  companies: '/api/v1/crm/companies',
  projects: '/api/v1/crm/projects',
  tasks: '/api/v1/crm/tasks',
  touchpoints: '/api/v1/crm/touchpoints',
  notes: '/api/v1/crm/notes',
  users: '/api/v1/crm/todo/users',
}

interface Props {
  field: FieldConfig
  entity?: any
  form?: Record<string, any>
  onChange?: (key: string, value: any) => void
  editOpen?: boolean
  /** Extra lookup data for relation fields */
  relationData?: Record<string, { id: string; name: string }[]>
  /** Callback when a relation link is clicked — navigates to detail page */
  onNavigate?: (url: string) => void
  /** Extra select/status options merged after field.options (dedupe by value, defaults first) */
  extraOptions?: Record<string, { value: string; label: string; id?: string; isCustom?: boolean }[]>
  /** ＋Create click — parent persist (POST /field-options) 後先 pick */
  onCreateCustom?: (fieldKey: string, label: string) => void
  /** custom option 右邊 × — parent delete (DELETE /field-options/{id}) */
  onDeleteOption?: (fieldKey: string, id: string) => void
}

// ═══ TABLE CELL RENDERER ═══
/* T9 (2026-09-07): 電話國碼選單 — 國家名 alphabetical（Terrence:「以國家名排列 + 國碼」）—
   由舊 src/pages/ContactsPage.tsx 搬入共用 FieldsRenderer（create/edit form 都用） */
const COUNTRY_CODES: { name: string; code: string }[] = [
  { name: 'Australia', code: '+61' }, { name: 'Austria', code: '+43' },
  { name: 'Bangladesh', code: '+880' }, { name: 'Belgium', code: '+32' },
  { name: 'Brazil', code: '+55' }, { name: 'Cambodia', code: '+855' },
  { name: 'China', code: '+86' }, { name: 'Denmark', code: '+45' },
  { name: 'Finland', code: '+358' }, { name: 'France', code: '+33' },
  { name: 'Germany', code: '+49' }, { name: 'Hong Kong', code: '+852' },
  { name: 'India', code: '+91' }, { name: 'Indonesia', code: '+62' },
  { name: 'Ireland', code: '+353' }, { name: 'Israel', code: '+972' },
  { name: 'Italy', code: '+39' }, { name: 'Japan', code: '+81' },
  { name: 'Macau', code: '+853' }, { name: 'Malaysia', code: '+60' },
  { name: 'Mexico', code: '+52' }, { name: 'Myanmar', code: '+95' },
  { name: 'Netherlands', code: '+31' }, { name: 'New Zealand', code: '+64' },
  { name: 'Norway', code: '+47' }, { name: 'Philippines', code: '+63' },
  { name: 'Poland', code: '+48' }, { name: 'Portugal', code: '+351' },
  { name: 'Russia', code: '+7' }, { name: 'Saudi Arabia', code: '+966' },
  { name: 'Singapore', code: '+65' }, { name: 'South Africa', code: '+27' },
  { name: 'South Korea', code: '+82' }, { name: 'Spain', code: '+34' },
  { name: 'Sweden', code: '+46' }, { name: 'Switzerland', code: '+41' },
  { name: 'Taiwan', code: '+886' }, { name: 'Thailand', code: '+66' },
  { name: 'Turkey', code: '+90' }, { name: 'UAE', code: '+971' },
  { name: 'United Kingdom', code: '+44' }, { name: 'United States', code: '+1' },
  { name: 'Vietnam', code: '+84' },
].sort((a, b) => a.name.localeCompare(b.name));

/* parse "+85200000000" → { code: '+852', local: '91234567' }（冇 match code → defCode） */
function splitPhone(raw: string | null | undefined, defCode: string): { code: string; local: string } {
  const v = (raw || '').replace(/\s+/g, '');
  if (!v) return { code: defCode, local: '' };
  if (v.startsWith('+')) {
    const hit = COUNTRY_CODES.find(c => v.startsWith(c.code));
    if (hit) return { code: hit.code, local: v.slice(hit.code.length) };
  }
  return { code: defCode, local: v };
}

/* Phone input：國碼 select（國家名排列）+ 號碼 input — 儲存合併做 "+85200000000" */
function PhoneField({ value, onChange, placeholder }: { value: any; onChange?: (v: string) => void; placeholder?: string }) {
  const [code, setCode] = useState('+852')
  const [local, setLocal] = useState('')
  const synced = useRef<string | null>(null)
  // 外部 value 變（AI fill / edit load）→ sync 入 local state
  useEffect(() => {
    const v = value == null ? '' : String(value).replace(/\s+/g, '')
    if (v === synced.current) return
    const sp = splitPhone(v, '+852')
    setCode(sp.code); setLocal(sp.local)
    synced.current = v
  }, [value])
  const emit = (c: string, l: string) => {
    synced.current = c + l
    onChange?.(c + l)
  }
  return (
    <div className="phone-field" style={{ display: 'flex', gap: 6 }}>
      <select className="phone-code-select" style={{ flex: '0 0 118px', height: 38 }} value={code}
        aria-label="Country code"
        onChange={e => { setCode(e.target.value); emit(e.target.value, local) }}>
        {COUNTRY_CODES.map(c => (
          <option key={c.code} value={c.code}>{c.name} {c.code}</option>
        ))}
      </select>
      <input type="tel" className="input-field" style={{ flex: 1, height: 38 }} value={local}
        placeholder={placeholder || '電話號碼'} inputMode="tel"
        onChange={e => { const l = e.target.value.replace(/[^0-9+\-() ]/g, ''); setLocal(l); emit(code, l) }} />
    </div>
  )
}

export function CellRenderer({ value, field, onNavigate }: { value: any; field: FieldConfig; onNavigate?: (url: string) => void }) {
  const { t } = useTranslation()
  if (field.dependsOnModule && !isModuleEnabled(field.dependsOnModule)) return null
  if (value == null) return <span className="text-faint">—</span>

  switch (field.type) {
    case 'select':
    case 'status': {
      const opt = field.options?.find(o => o.value === value || o.label === value)
      const cls = opt?.color ? (optionColorToClass[opt.color] || 'tag-default') : 'tag-default'
      return <span className={`select-tag ${cls}`}>{opt?.label || value}</span>
    }
    case 'multi_select': {
      const arr = Array.isArray(value) ? value : []
      return (
        <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {arr.map((v: string) => <span key={v} className="tag">{v}</span>)}
        </span>
      )
    }
    case 'person': {
      const name = typeof value === 'object' ? value.name || value.email : String(value)
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="avatar-sm">{name.split(' ').map((n: string) => n[0]).join('').slice(0, 2).toUpperCase()}</span>
          {name}
        </span>
      )
    }
    case 'date':
    case 'created_time':
    case 'last_edited_time': {
      const d = formatDate(value)
      const rel = formatRelativeDate(value)
      const isOverdue = new Date(value).getTime() < Date.now() && field.key === 'deadline'
      // Overdue deadline = status highlight via COLOR only (keeps cells normal-weight;
      // only the name column is bold per table style rule). No font-weight bold here.
      return <span style={isOverdue ? { color: 'var(--color-notification)' } : {}} title={rel}>{d}</span>
    }
    case 'number': {
      if (field.format === 'hkd') return <span>{formatAmount(value)}</span>  // normal weight
      if (field.format === 'percent') return <span>{value}%</span>
      return <span>{value}</span>
    }
    case 'checkbox':
      return <span>{value ? '✅' : '⬜'}</span>
    case 'url':
    case 'email':
      return <a href={field.type === 'email' ? `mailto:${value}` : value} target="_blank" rel="noopener"
        style={{ color: 'var(--color-primary)', textDecoration: 'none' }}
        onClick={e => e.stopPropagation()}>{value}</a>
    case 'relation': {
      if (Array.isArray(value)) {
        // Multi-relation (e.g. touchpoint participants) → badge list
        if (value.length === 0) return <span className="text-faint">—</span>
        return (
          <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
            {value.map((v, i) => {
              const item = (typeof v === 'object' && v) ? v : { id: String(v), name: String(v) }
              return (
                <span key={i} className="badge badge-p3" style={{ color: 'var(--color-primary)' }}>
                  {item.name || item.title || item.id}
                </span>
              )
            })}
          </span>
        )
      }
      if (typeof value === 'object' && value) {
        const resource = field.relation?.resource || ''
        const route = RELATION_ROUTES[resource]
        const href = route ? `${route}/${value.id}` : ''
        if (href && onNavigate) {
          return (
            <a href={href} onClick={e => { e.preventDefault(); onNavigate(href) }}
              className="badge badge-p3"
              style={{ color: 'var(--color-primary)', cursor: 'pointer', textDecoration: 'none' }}>
              {value.name || value.title || value.id}
            </a>
          )
        }
        return <span className="badge badge-p3">{value.name || value.title || value.id}</span>
      }
      return <span className="text-faint">{String(value)}</span>
    }
    case 'files': {
      const arr = Array.isArray(value) ? value : []
      return <span>{t('common.fileCount', { count: arr.length })}</span>
    }
    default:
      return <span>{String(value)}</span>
  }
}

// ═══ MULTI-RELATION PICKER（e.g. touchpoint 人物 — 多於一個 contact）═══
function MultiRelationPicker({ field, options, value, label, onPick }: {
  field: FieldConfig
  options: { id: string; name: string }[]
  value: any
  label: React.ReactNode
  onPick?: (key: string, ids: string[]) => void
}) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const curArr: string[] = Array.isArray(value)
    ? value.map(v => (typeof v === 'object' && v ? String(v.id) : String(v)))
    : value ? [String(value)] : []
  const shown = options.filter(r =>
    !curArr.includes(r.id) &&
    (r.name || '').toLowerCase().includes(q.toLowerCase())
  ).slice(0, 8)
  return (
    <div className="form-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
      {label}
      <div className="quick-field pos-relative" style={{ marginTop: 6 }}>
        <div className="tp-chips">
          {curArr.map(id => {
            const c = options.find(r => r.id === id)
            return (
              <span key={id} className="tp-chip">
                {c?.name || id}
                <button type="button" className="tp-chip-x" onClick={() => onPick?.(field.key, curArr.filter(x => x !== id))}>✕</button>
              </span>
            )
          })}
          <input value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={t('touchpoint.searchPlaceholder', { defaultValue: 'Search…' })}
            style={{ flex: 1, minWidth: 120, border: 'none', outline: 'none', fontSize: 13, padding: '4px 0', background: 'transparent' }} />
        </div>
        {q && (
          <div className="tp-dropdown">
            {shown.length === 0 && <div className="tp-dropdown-item text-faint">—</div>}
            {shown.map(r => (
              <div key={r.id} className="tp-dropdown-item" onMouseDown={() => { onPick?.(field.key, [...curArr, r.id]); setQ('') }}>
                <span className="avatar-xs">{String(r.name || '?').slice(0, 2).toUpperCase()}</span>
                {r.name}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


// ═══ DETAIL / FORM FIELD RENDERER ═══
export function FieldsRenderer({ field, entity, form, onChange, editOpen, onNavigate, relationData, extraOptions, onCreateCustom, onDeleteOption }: Props) {
  const { t } = useTranslation()
  const label = <div className="field-label">{localizeFieldLabel(field, t)}{field.required ? ' *' : ''}</div>
  const isReadonly = !editOpen || field.editable === false
    || ['rollup', 'formula', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by', 'unique_id'].includes(field.type)
  const value = form?.[field.key] ?? entity?.[field.key]
  const displayVal = entity?.[field.key]
  // merged select/status options（config defaults + tenant/user extraOptions，dedupe by value，defaults 行先）
  const mergedSelectOptions = useMemo(() => {
    const defaults = (field.options || []).map(o => ({ value: String(o.value), label: String(o.label ?? o.value) }))
    const extra = (extraOptions?.[field.key] || [])
    const seen = new Set(defaults.map(o => o.value))
    const out = [...defaults]
    for (const o of extra) {
      if (seen.has(o.value)) continue
      seen.add(o.value)
      out.push({
        value: String(o.value),
        label: String(o.label ?? o.value),
        ...(o.id ? { id: o.id } : {}),
        ...(o.isCustom ? { isCustom: true } : {}),
      })
    }
    return out
  }, [field.options, extraOptions, field.key])

  // Readonly display
  if (isReadonly) {
    return (
      <div className="form-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
        {label}
        <CellRenderer value={displayVal} field={field} onNavigate={onNavigate} />
      </div>
    )
  }

  // Editable form inputs
  if (['select', 'status'].includes(field.type)) {
    const stringValue = value == null ? '' : String(value)
    return (
      <div className="form-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
        <SelectCombobox
          value={stringValue}
          options={mergedSelectOptions}
          onChange={v => onChange?.(field.key, v)}
          label={localizeFieldLabel(field, t) + (field.required ? ' *' : '')}
          onCreateCustom={onCreateCustom ? (lbl: string) => onCreateCustom(field.key, lbl) : undefined}
          onDeleteOption={onDeleteOption ? (id: string) => onDeleteOption(field.key, id) : undefined}
        />
      </div>
    )
  }

  if (field.type === 'multi_select') {
    const selected: string[] = value ?? []
    return (
      <div className="form-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
        {label}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {field.options?.filter(o => !selected.includes(o.value)).map(o => (
            <button key={o.value} type="button" className="tag" style={{ cursor: 'pointer' }}
              onClick={() => onChange?.(field.key, [...selected, o.value])}>
              +{o.label}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
          {selected.map(s => (
            <span key={s} className="badge badge-tag" style={{ cursor: 'pointer' }}
              onClick={() => onChange?.(field.key, selected.filter(x => x !== s))}>
              {s} ✕
            </span>
          ))}
        </div>
        {/* T9 (2026-09-07): 自訂標籤 — 舊 file checkbox-group 有 custom add；共用 renderer 補返 */}
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          <input type="text" className="input-field checkbox-custom-input" style={{ flex: 1, height: 32 }}
            placeholder="新增標籤…（Enter 加入）" maxLength={20}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                const v = (e.target as HTMLInputElement).value.trim()
                if (v && !selected.includes(v)) onChange?.(field.key, [...selected, v])
                ;(e.target as HTMLInputElement).value = ''
              }
            }} />
          <button type="button" className="checkbox-custom-btn" aria-label="新增標籤"
            onClick={e => {
              const inp = (e.currentTarget.parentElement?.querySelector('input.checkbox-custom-input')) as HTMLInputElement | null
              const v = (inp?.value || '').trim()
              if (v && !selected.includes(v)) onChange?.(field.key, [...selected, v])
              if (inp) inp.value = ''
            }}>＋</button>
        </div>
      </div>
    )
  }

  if (field.type === 'phone') {
    return (
      <div className="floating-field">
        <PhoneField value={value} onChange={v => onChange?.(field.key, v)} placeholder={localizeFieldLabel(field, t)} />
      </div>
    )
  }

  if (field.type === 'date') {
    /* 2026-09-11: `format: 'datetime'` adds a TIME picker. The touchpoint was
       date-only, so it could not record WHEN something happened — 「During 沒有時間
       選擇」. datetime-local shows the browser's local zone (HKT for this tenant)
       and we store ISO, so a 14:30 HKT meeting round-trips as 14:30 rather than
       the UTC 06:30 held in the raw value. */
    if (field.format === 'datetime') {
      let dtLocal = ''
      if (value) {
        const d = new Date(String(value))
        if (!isNaN(d.getTime())) {
          const p = (n: number) => String(n).padStart(2, '0')
          dtLocal = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
        }
      }
      return (
        <div className="floating-field">
          <input
            type="datetime-local"
            value={dtLocal}
            onChange={e => onChange?.(field.key, e.target.value ? new Date(e.target.value).toISOString() : '')}
            className="input-field floating-input"
            placeholder={localizeFieldLabel(field, t)}
          />
          <label className="floating-label">{localizeFieldLabel(field, t)}</label>
        </div>
      )
    }
    const dateVal = value ? String(value).slice(0, 10) : ''
    return (
      <div className="floating-field">
        <input type="date" value={dateVal} onChange={e => onChange?.(field.key, e.target.value)} className="input-field floating-input" placeholder={localizeFieldLabel(field, t)} />
        <label className="floating-label">{localizeFieldLabel(field, t)}</label>
      </div>
    )
  }

  if (field.type === 'person') {
    return (
      <div className="floating-field">
        <input type="text" value={value ?? ''} onChange={e => onChange?.(field.key, e.target.value)}
          className="input-field floating-input" placeholder={field.label} />
        <label className="floating-label">{field.label}</label>
      </div>
    )
  }

  if (field.type === 'checkbox') {
    return (
      <div className="form-field" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input type="checkbox" checked={!!value} onChange={e => onChange?.(field.key, e.target.checked)}
          style={{ width: 18, height: 18 }} />
        {label}
      </div>
    )
  }

  if (field.type === 'relation') {
    const resource = field.relation?.resource || ''
    // ── Multi-relation (multiple: true) — chips + dropdown picker ──
    if (field.relation?.multiple) {
      return (
        <MultiRelationPicker
          field={field}
          options={relationData?.[resource] || []}
          value={value}
          label={label}
          onPick={(key, ids) => onChange?.(key, ids)}
        />
      )
    }
    const searchUrl = RELATION_SEARCH_URL[resource] || `/api/v1/crm/${resource}`
    const currentVal = (typeof value === 'object' ? value?.id : value) ?? ''
    const titleFields = ['tasks', 'touchpoints', 'notes', 'projects']
    const createTitleField = titleFields.includes(resource) ? 'title' : 'name'
    const createLabelMap: Record<string, string> = {
      companies: 'Company', contacts: 'Contact', tasks: 'Task',
      touchpoints: 'Touchpoint', notes: 'Note', projects: 'Project',
    }
    return (
      <div className="form-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
        <EntitySearch
          searchUrl={searchUrl}
          value={currentVal}
          onChange={(id) => onChange?.(field.key, id)}
          placeholder={t('common.searchResource', { resource })}
          label={field.label}
          required={field.required}
          displayField={resource === 'users' ? 'email' : (field.relation?.displayField || 'name')}
          createLabel={resource === 'users' ? undefined : (createLabelMap[resource] || 'Company')}
          createTitleField={createTitleField}
        />
      </div>
    )
  }

  if (field.type === 'email') {
    return (
      <div className="floating-field">
        <input type="email" value={value ?? ''} onChange={e => onChange?.(field.key, e.target.value)}
          className="input-field floating-input" placeholder={field.label} />
        <label className="floating-label">{field.label}</label>
      </div>
    )
  }

  if (field.type === 'url') {
    return (
      <div className="floating-field">
        <input type="text" value={value ?? ''} onChange={e => onChange?.(field.key, e.target.value)}
          className="input-field floating-input" placeholder={field.label} />
        <label className="floating-label">{field.label}</label>
      </div>
    )
  }

  if (field.type === 'number') {
    return (
      <div className="floating-field">
        <input type="number" value={value ?? ''} onChange={e => onChange?.(field.key, e.target.valueAsNumber ?? '')}
          className="input-field floating-input" placeholder={field.label} />
        <label className="floating-label">{field.label}</label>
      </div>
    )
  }

  if (field.type === 'rich_text') {
    return (
      <div className="floating-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
        <NexusEditor
          content={String(value ?? '')}
          onChange={html => onChange?.(field.key, html)}
          placeholder={field.label}
          minHeight={120}
        />
        <label className="floating-label">{field.label}</label>
      </div>
    )
  }

  // Location autocomplete (touchpoint 地點 — CRM 地址 + 歷史, 2026-09-09)
  if (field.type === 'text' && field.key === 'location') {
    return (
      <LocationField value={String(value ?? '')} onChange={v => onChange?.(field.key, v)} label={localizeFieldLabel(field, t)} required={field.required} gridColumn={field.gridColumn} />
    )
  }

  // Default text input
  return (
    <div className="floating-field" style={field.gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
      <input type="text" value={value ?? ''} onChange={e => onChange?.(field.key, e.target.value)}
        className="input-field floating-input" placeholder={field.label} />
      <label className="floating-label">{field.label}{field.required ? ' *' : ''}</label>
    </div>
  )
}

// ═══ LOCATION AUTOCOMPLETE（A: Google Places + B: CRM 地址／歷史 — 2026-09-11）═══
// Opens against /touchpoints/place-suggest, which merges the tenant's own
// addresses (companies/contacts/touchpoint history) FIRST and fills the rest
// from Google Places. The endpoint degrades to local-only if Places is unhappy.
function LocationField({ value, onChange, label, required, gridColumn }: {
  value: string
  onChange: (v: string) => void
  label: string
  required?: boolean
  gridColumn?: string
}) {
  const [q, setQ] = useState(value)
  const [items, setItems] = useState<{ value: string; source: string }[]>([])
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!q.trim() || q.trim() === value) { setItems([]); return }
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        const res = await apiClient.get<{ items: { value: string; source: string }[] }>('/api/v1/crm/touchpoints/place-suggest', { params: { q } })
        setItems(res.items || [])
        setOpen(true)
      } catch { setItems([]) }
    }, 300)
  }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="floating-field pos-relative" style={gridColumn === 'full' ? { gridColumn: '1 / -1' } : {}}>
      <input type="text" value={q} autoComplete="off"
        onChange={e => { setQ(e.target.value); onChange(e.target.value) }}
        onFocus={() => { if (items.length) setOpen(true) }}
        onBlur={() => { blurTimer.current = setTimeout(() => setOpen(false), 150) }}
        className="input-field floating-input" placeholder={label} />
      <label className="floating-label">{label}{required ? ' *' : ''}</label>
      {open && items.length > 0 && (
        <div className="tp-dropdown" style={{ top: 'calc(100% + 4px)', left: 0, right: 0, position: 'absolute', zIndex: 30 }}>
          {items.map(it => (
            <div key={it.value} className="tp-dropdown-item" onMouseDown={() => { setQ(it.value); onChange(it.value); setOpen(false) }}>
              <span className="avatar-xs">{it.source === 'google' ? '🌐' : '📍'}</span>
              <span style={{ flex: 1 }}>{it.value}</span>
              {it.source === 'google' && (
                <span style={{ fontSize: 10, opacity: 0.55, whiteSpace: 'nowrap' }}>Google</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

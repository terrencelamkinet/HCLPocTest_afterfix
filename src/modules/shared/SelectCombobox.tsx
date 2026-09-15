// ═══════════════════════════════════════════════════════
// SelectCombobox.tsx
// Searchable combobox for select / status fields（industry / category / status）
// Behavior:
//   1. Input 顯示 current value（match 到 option 顯示 label，否則顯示 raw value）
//   2. Focus / 打字 → 開 dropdown，filter options（case-insensitive substring on label）
//   3. Query 冇 exact match + 非空 → 顯示「＋ Create 『query』」option（custom value）
//   4. Click option → onChange(value) + 關 dropdown
//   5. 有 value 就常駐顯示清除（×）button（open dropdown 時都有）
//   6. Custom option（isCustom + id）→ 右邊細 ×（叫 onDeleteOption(id)，唔關 dropdown、唔 pick）
//   7. ＋Create click → 叫 onCreateCustom(label)（parent persist，成功先完成 pick）
//   8. Keyboard：Enter 揀 highlighted / 第一個，Escape 關閉
//   9. Click outside → 關閉
// ═══════════════════════════════════════════════════════
import { useState, useRef, useEffect, useMemo, useCallback, type ReactNode } from 'react'
import SvcIcon from '../../components/SvcIcon'

export interface ComboboxOption {
  value: string
  label: string
  /** custom option（user_field_options row）先有 id — 用嚟 DELETE */
  id?: string
  isCustom?: boolean
}

interface Props {
  value: string
  options: ComboboxOption[]
  onChange: (value: string) => void
  placeholder?: string
  /** floating label 內容（同 input 做 siblings → `+` selector 生效） */
  label?: ReactNode
  /** ＋Create click — parent persist（POST /field-options），成功先 call onChange */
  onCreateCustom?: (label: string) => void
  /** custom option 右邊 × click — parent delete（DELETE /field-options/{id}） */
  onDeleteOption?: (id: string) => void
}

export default function SelectCombobox({
  value, options, onChange, placeholder,
  label, onCreateCustom, onDeleteOption,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // current option match（label 或 value 等於 value）
  const currentOpt = useMemo(
    () => options.find(o => o.value === value || o.label === value),
    [options, value]
  )

  // 輸入框顯示：有 query 顯示 query；否則 match 到 option 顯示 label，否則 raw value
  const inputText = open ? query : (currentOpt?.label ?? value ?? '')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(o => o.label.toLowerCase().includes(q))
  }, [query, options])

  const hasExact = useMemo(
    () => filtered.some(o => o.label.toLowerCase() === query.trim().toLowerCase() && query.trim() !== ''),
    [filtered, query]
  )

  const showCreate = query.trim() !== '' && !hasExact

  // click outside → close
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // reset highlight + query when opened
  useEffect(() => {
    if (open) { setHighlight(0); setQuery('') }
  }, [open])

  // clear X — 常駐（有 value 就顯示，唔理 open 唔 open），click → 清 value + 唔開 dropdown
  const handleClear = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    onChange('')
    setQuery('')
    setOpen(false)
  }, [onChange])

  // pick option
  const pick = useCallback((v: string) => {
    onChange(v)
    setOpen(false)
    setQuery('')
  }, [onChange])

  // ＋Create click — parent persist（POST），成功後先 pick；POST fail 都照樣 pick（form 值唔可以丟）
  const handleCreate = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const labelVal = query.trim()
    if (!labelVal) return
    if (onCreateCustom) {
      onCreateCustom(labelVal) // parent 負責 POST + 之後 call onChange(labelVal)
    } else {
      pick(labelVal) // 冇 parent handler → 直接用 raw value（唔 persist）
    }
  }, [query, onCreateCustom, pick])

  // custom option 右邊 × — delete（唔關 dropdown、唔 pick）
  const handleDeleteOption = useCallback((e: React.MouseEvent, id: string) => {
    e.preventDefault()
    e.stopPropagation() // 防 pick
    onDeleteOption?.(id)
  }, [onDeleteOption])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setOpen(false); return }
    if (e.key === 'Enter') {
      e.preventDefault()
      const total = filtered.length + (showCreate ? 1 : 0)
      if (total === 0) return
      if (highlight >= filtered.length) {
        // highlight 落喺 create option
        handleCreate(e as unknown as React.MouseEvent)
      } else if (filtered[highlight]) {
        pick(filtered[highlight].value)
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      const total = filtered.length + (showCreate ? 1 : 0)
      setHighlight(h => (h + 1) % Math.max(total, 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const total = filtered.length + (showCreate ? 1 : 0)
      setHighlight(h => (h - 1 + Math.max(total, 1)) % Math.max(total, 1))
    }
  }

  return (
    <div className="floating-field select-combobox" ref={wrapRef}>
      <input
        ref={inputRef}
        className="input-field floating-input"
        placeholder={placeholder || " "}
        value={inputText}
        onFocus={() => setOpen(true)}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onKeyDown={handleKeyDown}
        style={{ paddingRight: value !== '' && value != null ? 30 : 12 }}
      />
      {value !== '' && value != null && (
        <button
          type="button"
          className="select-clear"
          aria-label="clear"
          onClick={handleClear}
        ><SvcIcon name="x" size={14} /></button>
      )}
      {label != null && <label className="floating-label">{label}</label>}
      {open && (
        <div className="select-dropdown" onMouseDown={e => e.preventDefault()}>
          {filtered.map((o, i) => (
            <div
              key={o.value}
              className={`select-item ${i === highlight ? 'active' : ''}`}
              onMouseEnter={() => setHighlight(i)}
              onMouseDown={e => e.preventDefault()}
              onClick={() => pick(o.value)}
            >
              <span className="select-item-label">{o.label}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                {o.value === value && <SvcIcon name="check" size={14} className="select-item-check" />}
                {o.isCustom && o.id && onDeleteOption && (
                  <button
                    type="button"
                    className="select-item-delete"
                    aria-label={`delete ${o.label}`}
                    onMouseDown={e => handleDeleteOption(e, o.id!)}
                  ><SvcIcon name="x" size={12} /></button>
                )}
              </span>
            </div>
          ))}
          {showCreate && (
            <button
              type="button"
              className={`select-item create ${highlight >= filtered.length ? 'active' : ''}`}
              onMouseEnter={() => setHighlight(filtered.length)}
              onMouseDown={e => e.preventDefault()}
              onClick={handleCreate}
            >
              <span className="select-item-label">{`＋ Create 「${query.trim()}」`}</span>
            </button>
          )}
          {filtered.length === 0 && !showCreate && (
            <div className="select-empty">{'No options'}</div>
          )}
        </div>
      )}
    </div>
  )
}

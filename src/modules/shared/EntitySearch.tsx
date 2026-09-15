// ═══════════════════════════════════════════
//  EntitySearch — Bur Search for relation fields
//  Reusable search-autocomplete for companies,
//  contacts, projects, etc.
//  ── Selected entity shows as removable tag ──
//  ── Dropdown uses position:fixed to avoid  ──
//  ── clipping in overflow:hidden parents    ──
// ═══════════════════════════════════════════

import { useState, useEffect, useRef, useCallback } from 'react'
import SvcIcon from '../../components/SvcIcon'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../lib/api'
import { useEscapeKey } from '../../lib/useEscapeKey'

interface EntitySearchProps {
  searchUrl: string
  value: string
  onChange: (id: string) => void
  placeholder?: string
  displayField?: string
  label?: string
  required?: boolean
  createLabel?: string
  createTitleField?: string
}

interface SearchItem {
  id: string
  name?: string
  title?: string
  email?: string
  [key: string]: unknown
}

export default function EntitySearch({
  searchUrl,
  value,
  onChange,
  placeholder = '',
  displayField = 'name',
  label,
  required,
  createLabel,
  createTitleField = 'name',
}: EntitySearchProps) {
  const { t } = useTranslation()
  const searchPlaceholder = placeholder || t('common.search')
  const changePlaceholder = t('common.search')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchItem[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedLabel, setSelectedLabel] = useState('')
  const [focused, setFocused] = useState(false)

  // ── Fixed-position dropdown coordinates ──
  const [dropPos, setDropPos] = useState<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })

  // ── Calculate position AFTER showDropdown becomes true ──
  useEffect(() => {
    if (showDropdown && wrapperRef.current) {
      const rect = wrapperRef.current.getBoundingClientRect()
      setDropPos({ top: rect.bottom + 4, left: rect.left, width: rect.width })
    }
  }, [showDropdown, results])

  // ── Create modal state ──
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState('')
  const [creating, setCreating] = useState(false)

  useEscapeKey(() => setShowCreate(false), showCreate)

  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const abortRef = useRef<AbortController>(null)
  const labelFetchedRef = useRef(false)

  // ── Fetch label when value is set ──
  useEffect(() => {
    if (value && !labelFetchedRef.current) {
      labelFetchedRef.current = true
      apiClient.get<SearchItem>(`${searchUrl}/${value}`)
        .then(data => {
          const lbl = String(data?.[displayField] ?? '') || data?.title || data?.email || data?.id || ''
          setSelectedLabel(lbl)
        })
        .catch(() => {})
    }
  }, [value, searchUrl, displayField])

  // ── Reset when value clears ──
  useEffect(() => {
    if (!value) {
      setSelectedLabel('')
      setQuery('')
      labelFetchedRef.current = false
    }
  }, [value])

  // ── Click outside to close dropdown ──
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // ── Recalc position on scroll (hide if far off) ──
  useEffect(() => {
    if (!showDropdown) return
    const handleScroll = () => {
      if (wrapperRef.current) {
        const rect = wrapperRef.current.getBoundingClientRect()
        setDropPos({ top: rect.bottom + 4, left: rect.left, width: rect.width })
      }
    }
    document.addEventListener('scroll', handleScroll, true)
    return () => document.removeEventListener('scroll', handleScroll, true)
  }, [showDropdown])

  // ── Debounced search ──
  const doSearch = useCallback((q: string) => {
    if (abortRef.current) abortRef.current.abort()
    if (q.length < 1) { setResults([]); setShowDropdown(false); return }

    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)

    // 2026-09-15 SAST：session 喺 httpOnly cookie（同源 fetch 自動帶）
    fetch(`${searchUrl}?search=${encodeURIComponent(q)}&limit=20`, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(r => r.json())
      .then(data => {
        const items: SearchItem[] = data?.items || data || []
        setResults(items)
        setShowDropdown(items.length > 0)
        if (items.length > 0) {
          // calcDropPos called via showDropdown useEffect
        }
        setLoading(false)
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setLoading(false)
      })
  }, [searchUrl])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value
    setQuery(q)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(q), 250)
  }

  const handleSelect = (item: SearchItem) => {
    const lbl = String(item[displayField] ?? '') || item.title || item.email || item.name || item.id
    setSelectedLabel(lbl)
    setQuery('')
    setResults([])
    setShowDropdown(false)
    onChange(item.id)
    labelFetchedRef.current = true
  }

  const handleClear = () => {
    setSelectedLabel('')
    setQuery('')
    setResults([])
    setShowDropdown(false)
    onChange('')
    labelFetchedRef.current = false
    inputRef.current?.focus()
  }

  const handleFocus = () => {
    setFocused(true)
    if (query.length >= 1) {
      doSearch(query)
    }
  }

  // ── Quick-create ──
  const openCreate = () => { setCreateName(''); setShowCreate(true) }

  const handleCreate = async () => {
    if (!createName.trim()) return
    setCreating(true)
    try {
      const created = await apiClient.post<SearchItem>(searchUrl, {
        [createTitleField]: createName.trim(),
      })
      const newId = created.id
      const newLabel = String(created[displayField] ?? '') || created.title || created.name || newId
      setSelectedLabel(newLabel)
      setQuery('')
      labelFetchedRef.current = true
      onChange(newId)
      setShowCreate(false)
      setCreateName('')
    } catch (e: any) {
      alert(e.detail || e.message || t('common.error'))
    } finally {
      setCreating(false)
    }
  }

  // ── Dropdown renderer (fixed position) ──
  const renderDropdown = () => {
    if (!showDropdown || results.length === 0) return null
    return (
      <div className="entity-search-dropdown" style={{
        position: 'fixed', top: dropPos.top, left: dropPos.left,
        width: dropPos.width, zIndex: 10000,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)', borderRadius: '8px',
        boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
        maxHeight: 200, overflowY: 'auto',
      }}>
        {results.map(item => {
          const name = String(item[displayField] ?? '') || item.title || item.email || item.name || item.id
          const subtitle = String(item.email ?? '') || String(item.industry ?? '') || (item.job_title ? `at ${item.job_title}` : '')
          return (
            <div key={item.id} className="entity-search-item"
              onClick={() => handleSelect(item)}
              style={{
                padding: '8px 12px', cursor: 'pointer',
                borderBottom: '1px solid var(--color-border-muted, #f0f0f0)',
                display: 'flex', flexDirection: 'column', gap: 1,
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-bg-hover, #f5f5f5)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
              <span style={{ fontWeight: 500, fontSize: 13, color: 'var(--color-text)' }}>{name}</span>
              {subtitle && <span style={{ fontSize: 11, color: 'var(--color-text-faint)' }}>{subtitle}</span>}
            </div>
          )
        })}
      </div>
    )
  }

  // ── Rendering ──

  // --- Selected state: show tag ---
  if (value && selectedLabel) {
    return (
      <div className="form-field pos-relative" ref={wrapperRef}>
        {label && <div className="field-label">{label}{required ? ' *' : ''}</div>}
        <div className="entity-search-tag" style={{
          display: 'flex', alignItems: 'center', gap: 6,
          flexWrap: 'wrap', width: '100%',
          border: '1px solid var(--color-border)',
          borderRadius: '8px',
          padding: '4px 6px',
          minHeight: 36,
          background: 'var(--color-surface)',
        }}>
          {/* The chip */}
          <span className="entity-chip" style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '4px 8px',
            borderRadius: '6px',
            background: 'var(--color-primary-highlight, #eef2ff)',
            color: 'var(--color-primary, #6366f1)',
            fontWeight: 500, fontSize: 13,
            maxWidth: '100%',
            lineHeight: 1.3,
          }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
              {selectedLabel}
            </span>
            <button type="button" onClick={handleClear}
              title={t('common.clear')}
              style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                border: 'none', background: 'transparent', cursor: 'pointer',
                padding: 0, flexShrink: 0, borderRadius: 4,
                color: 'var(--color-primary, #6366f1)', opacity: 0.7,
              }}>
              <SvcIcon name="x" className="w-3 h-3" />
            </button>
          </span>

          {/* Search input inline (for changing selection) */}
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleInputChange}
            onFocus={handleFocus}
            onBlur={() => setFocused(false)}
            placeholder={changePlaceholder}
            className="input-field"
            style={{
              border: 'none', boxShadow: 'none', padding: '4px 4px',
              flex: 1, minWidth: 80, background: 'transparent',
              fontSize: 13,
            }}
          />

          {/* + button */}
          {createLabel && (
            <button type="button" onClick={openCreate} title={`${t('common.create')} ${createLabel}`}
              style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                width: 22, height: 22, borderRadius: 6, border: 'none',
                background: 'var(--color-primary, #6366f1)', color: '#fff',
                cursor: 'pointer', flexShrink: 0,
                fontSize: 14, lineHeight: 1, padding: 0,
              }}>
              <SvcIcon name="plus" className="w-3 h-3" />
            </button>
          )}
        </div>

        {renderDropdown()}

        {/* Create modal */}
        {showCreate && <CreateModal />}
      </div>
    )
  }

  // --- Empty / search state ---
  return (
    <div className="form-field pos-relative" ref={wrapperRef}>
      {label && <div className="field-label">{label}{required ? ' *' : ''}</div>}
      <div className={`entity-search-wrap ${focused ? 'entity-search-focused' : ''}`}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          border: '1px solid var(--color-border)',
          borderRadius: '8px', padding: '0 8px',
          background: 'var(--color-surface)',
          transition: 'border-color 0.15s',
        }}>
        <SvcIcon name="search" className="w-3.5 h-3.5" style={{ color: 'var(--color-text-faint)', flexShrink: 0 }} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onFocus={handleFocus}
          onBlur={() => setFocused(false)}
          placeholder={searchPlaceholder}
          className="input-field"
          style={{ border: 'none', boxShadow: 'none', padding: '8px 6px', flex: 1, background: 'transparent' }}
        />
        {loading ? (
          <SvcIcon name="loader-2" className="w-3.5 h-3.5 animate-spin" style={{ color: 'var(--color-text-faint)', flexShrink: 0 }} />
        ) : query ? (
          <SvcIcon name="x" className="w-3.5 h-3.5" style={{ color: 'var(--color-text-faint)', cursor: 'pointer', flexShrink: 0 }}
            onClick={handleClear} />
        ) : null}
        {createLabel && (
          <button type="button" onClick={openCreate} title={`${t('common.create')} ${createLabel}`}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22, borderRadius: 6, border: 'none',
              background: 'var(--color-primary, #6366f1)', color: '#fff',
              cursor: 'pointer', flexShrink: 0,
              fontSize: 14, lineHeight: 1, padding: 0,
            }}>
            <SvcIcon name="plus" className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {renderDropdown()}
      {showCreate && <CreateModal />}
    </div>
  )

  // ─── Create Modal ───
  function CreateModal() {
    return (
      <div className="modal-overlay"
        onClick={e => { if (e.target === e.currentTarget) setShowCreate(false) }}>
        <div className="modal modal-sm">
          <div className="modal-head">
            <h2>{t('common.create')} {createLabel}</h2>
            <button onClick={() => setShowCreate(false)} className="modal-x">
              <SvcIcon name="x" className="icon-16" />
            </button>
          </div>
          <div className="modal-body p-20">
            <div className="form-field">
              <label className="field-label">{createLabel} *</label>
              <input type="text" value={createName}
                onChange={e => setCreateName(e.target.value)}
                className="input-field"
                placeholder={changePlaceholder}
                autoFocus
                onKeyDown={e => { if (e.key === 'Enter') handleCreate() }} />
            </div>
          </div>
          <div className="modal-foot">
            <button onClick={() => setShowCreate(false)} className="btn-secondary">{t('common.cancel')}</button>
            <button onClick={handleCreate} disabled={creating || !createName.trim()}
              className="btn-primary">
              {creating ? t('common.processing') : `${t('common.create')} ${createLabel}`}
            </button>
          </div>
        </div>
      </div>
    )
  }
}

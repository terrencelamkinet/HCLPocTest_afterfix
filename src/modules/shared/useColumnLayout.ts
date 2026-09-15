import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import type { FieldConfig } from '../module-types'

/**
 * useColumnLayout — per-module column width + order, persisted to localStorage.
 *
 * Shared by all GenericListPage modules (tasks/projects/touchpoints/...).
 * Mirrors the ContactsPage useColumnConfig pattern but is config-driven
 * (no hardcoded defaults) and debounced on save.
 *
 * Storage key: `glp-col-config-${configName}` e.g. `glp-col-config-task`
 * Stores { order: string[], widths: Record<string, number> }.
 * Does NOT persist visible/hidden state (that lives in visibleCols state).
 */

interface ColLayoutConfig {
  order: string[]
  widths: Record<string, number>
}

const MIN_W = 60
const MAX_W = 600
const DEFAULT_W = 150
const SAVE_DEBOUNCE_MS = 150

function defaultWidthFor(field: FieldConfig | undefined): number {
  if (!field) return DEFAULT_W
  switch (field.type) {
    case 'title': // name / title column
      return 200
    case 'phone':
    case 'email':
    case 'url':
      return 180
    case 'multi_select':
    case 'rich_text':
      return 200
    case 'checkbox':
      return 70
    case 'status':
    case 'select':
      return 130
    default:
      return 140
  }
}

function safeParse(raw: string | null): ColLayoutConfig | null {
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (p && Array.isArray(p.order) && p.widths && typeof p.widths === 'object') {
      return { order: p.order.filter((k: unknown) => typeof k === 'string'), widths: p.widths }
    }
    return null
  } catch {
    return null
  }
}

function buildKey(configName: string): string {
  return `glp-col-config-${configName}`
}

export default function useColumnLayout(configName: string, fields: FieldConfig[], visibleCols: string[]) {
  const KEY = buildKey(configName)

  // ── state: initialize from localStorage + visibleCols ──
  const [cfg, setCfg] = useState<ColLayoutConfig>(() => {
    const saved = safeParse(typeof localStorage !== 'undefined' ? localStorage.getItem(KEY) : null)
    // Only keep saved entries that still exist as fields; append new/visible fields in order.
    const known = new Set(fields.map(f => f.key))
    const order = ((saved?.order || []).filter(k => known.has(k) || visibleCols.includes(k)))
    for (const k of visibleCols) {
      if (!order.includes(k)) order.push(k)
    }
    // Drop entries for fields that no longer exist (config changed) — keep widths only for known order.
    const widths: Record<string, number> = {}
    for (const k of order) {
      const f = fields.find(x => x.key === k)
      const savedW = saved?.widths?.[k]
      const num = typeof savedW === 'number' && savedW >= MIN_W && savedW <= MAX_W ? savedW : defaultWidthFor(f)
      widths[k] = num
    }
    return { order, widths }
  })

  // ── debounced persist ──
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      try { localStorage.setItem(KEY, JSON.stringify(cfg)) } catch { /* ignore */ }
    }, SAVE_DEBOUNCE_MS)
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current) }
  }, [cfg, KEY])

  // Drag / resize refs
  const dragCol = useRef<string | null>(null)
  const resizeCol = useRef<string | null>(null)
  const resizeStart = useRef({ x: 0, w: 0 })

  const getWidth = useCallback((key: string) => cfg.widths[key] || defaultWidthFor(fields.find(f => f.key === key)), [cfg.widths, fields])

  // Reconcile the displayed order against the CURRENT visible columns every render:
  // keep saved order for known/visible cols, then append any newly-visible col at the end.
  const orderedCols = useMemo(() => {
    const order = [...cfg.order]
    for (const k of visibleCols) if (!order.includes(k)) order.push(k)
    return order.filter(k => visibleCols.includes(k))
  }, [cfg.order, visibleCols])

  const moveColumn = useCallback((from: number, to: number) => {
    setCfg(prev => {
      const order = [...prev.order]
      const [moved] = order.splice(from, 1)
      order.splice(to, 0, moved)
      return { ...prev, order }
    })
  }, [])

  // ── Desktop + touch resize ──
  const onResizeStart = useCallback((e: React.MouseEvent | React.TouchEvent, key: string) => {
    e.preventDefault()
    if ('stopPropagation' in e) e.stopPropagation()
    resizeCol.current = key
    const startX = 'touches' in e ? e.touches[0].clientX : (e as React.MouseEvent).clientX
    resizeStart.current = { x: startX, w: cfg.widths[key] || defaultWidthFor(fields.find(f => f.key === key)) }

    const onMove = (ev: MouseEvent | TouchEvent) => {
      if (!resizeCol.current) return
      const cx = 'touches' in ev ? ev.touches[0].clientX : (ev as MouseEvent).clientX
      const dx = cx - resizeStart.current.x
      const newW = Math.max(MIN_W, Math.min(MAX_W, resizeStart.current.w + dx))
      const k = resizeCol.current
      setCfg(prev => ({ ...prev, widths: { ...prev.widths, [k]: Math.round(newW) } }))
    }
    const cleanup = () => {
      resizeCol.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', cleanup)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', cleanup)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', cleanup)
    window.addEventListener('touchmove', onMove, { passive: true })
    window.addEventListener('touchend', cleanup)
  }, [cfg.widths, fields])

  // ── HTML5 drag reorder (desktop) ──
  const onDragStart = useCallback((e: React.DragEvent, key: string) => {
    dragCol.current = key
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', key) // required for Firefox DnD
    ;(e.currentTarget as HTMLElement).style.opacity = '.5'
  }, [])

  const onDragOver = useCallback((e: React.DragEvent, key: string) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (!dragCol.current || dragCol.current === key) return
    const from = cfg.order.indexOf(dragCol.current)
    const to = cfg.order.indexOf(key)
    if (from === -1 || to === -1 || from === to) return
    moveColumn(from, to)
    dragCol.current = key
  }, [cfg.order, moveColumn])

  const onDragEnd = useCallback(() => {
    dragCol.current = null
  }, [])

  const resetColumns = useCallback(() => {
    setCfg({
      order: [...visibleCols],
      widths: Object.fromEntries(visibleCols.map(k => [k, defaultWidthFor(fields.find(f => f.key === k))])),
    })
  }, [visibleCols, fields])

  return {
    orderedCols,
    getWidth,
    moveColumn,
    resetColumns,
    onResizeStart,
    onDragStart,
    onDragOver,
    onDragEnd,
  }
}

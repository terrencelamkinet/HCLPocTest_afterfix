import { useEffect, useRef, type ReactNode } from 'react'
import SvcIcon from '../SvcIcon'
import { nextFocusIndex, shouldTrapFocus } from '../../lib/focusTrap'

/**
 * Notes 用嘅 app-style bottom sheet（2026-09-13 mobile Notes P0-2 / P0-3）。
 *
 * 取代手機上嘅 native `<select>`（picker 係 OS chrome，會同 app 嘅 bottom 區域
 * 打架，亦唔可以配合 app 嘅 focus／scrim 管理）。同一時間只會有一個 sheet ——
 * 擁有者係 NotesWorkspacePage 嘅狀態機（src/lib/notesMobileState.ts），
 * 呢個 component 唔會自己決定幾時出現。
 *
 * 無障礙：role=dialog + aria-modal、focus 入 sheet、Tab 繞圈（唔會走甩去背景）、
 * Escape 關閉、關閉後 focus 還原去開啟嗰個元素。
 */

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

export interface Props {
  title: string
  onClose: () => void
  children: ReactNode
  /** probe / e2e 用 */
  testId?: string
}

export default function AppBottomSheet({ title, onClose, children, testId }: Props) {
  const sheetRef = useRef<HTMLDivElement | null>(null)
  const openerRef = useRef<HTMLElement | null>(null)

  /* focus 還原（spec P1）：記住開啟者，unmount 時還原 */
  useEffect(() => {
    const active = document.activeElement
    openerRef.current = active instanceof HTMLElement ? active : null
    return () => {
      const opener = openerRef.current
      if (opener && document.contains(opener)) opener.focus()
    }
  }, [])

  /* 初次 focus 入 sheet（第一個 focusable，冇就 focus 個 dialog 自己） */
  useEffect(() => {
    /* 2026-09-13：`[data-autofocus]` 優先 —— 表單 sheet 想 focus 輸入框，
       而唔係 head 嘅關閉掣（FOCUSABLE 第一個永遠係嗰粒 X）。 */
    const first =
      sheetRef.current?.querySelector<HTMLElement>('[data-autofocus]') ??
      sheetRef.current?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? sheetRef.current)?.focus()
  }, [])

  /* Escape 關閉 + Tab 繞圈（唔可以 Tab 到 sheet 後面嘅 global nav / list） */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      const sheet = sheetRef.current
      if (!sheet || !sheet.contains(document.activeElement)) return
      const nodes = Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE))
      const index = nodes.indexOf(document.activeElement as HTMLElement)
      if (!shouldTrapFocus(e.key, index, nodes.length, e.shiftKey)) return
      const next = nextFocusIndex(e.key, index, nodes.length, e.shiftKey)
      if (next === null) return
      e.preventDefault()
      nodes[next]?.focus()
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [onClose])

  return (
    <>
      <button className="nwbs-scrim" aria-label={title} onClick={onClose} tabIndex={-1} />
      <div
        className="nwbs-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={sheetRef}
        tabIndex={-1}
        data-testid={testId}
      >
        <div className="nwbs-head">
          <strong>{title}</strong>
          <button className="nw-icon-btn" onClick={onClose} aria-label={title}>
            <SvcIcon name="x" size={15} />
          </button>
        </div>
        <div className="nwbs-body">{children}</div>
      </div>
    </>
  )
}

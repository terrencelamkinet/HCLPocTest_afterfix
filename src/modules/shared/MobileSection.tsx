import { useState, useRef, useLayoutEffect, type ReactNode } from 'react'

interface Props {
  label: string
  total?: number
  onViewAll?: () => void
  children: ReactNode
}

/**
 * MobileSection — truncates children at ~10 items (~420px height) with gradient fade + "View all" overlay.
 *   label:    shown in the button text ("View all {total} {label} →")
 *   total:    item count (0 or omit → no count shown)
 *   onViewAll: called when "View all" is tapped (use to navigate or expand)
 *
 * Uses dynamic height detection via useLayoutEffect — only shows overlay when content overflows 420px.
 * Once expanded (clicked), children render in full with no overlay.
 */
export default function MobileSection({ label, total, onViewAll, children }: Props) {
  const [expanded, setExpanded] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const [overflows, setOverflows] = useState(false)

  useLayoutEffect(() => {
    if (contentRef.current) {
      setOverflows(contentRef.current.scrollHeight > 420)
    }
  }, [children])

  if (expanded) return <>{children}</>

  return (
    <div className="pos-relative">
      <div ref={contentRef} className="mobile-section-truncated">
        {children}
      </div>
      {overflows && (
        <div className="mobile-section-overlay" onClick={() => {
          setExpanded(true)
          onViewAll?.()
        }}>
          <button className="btn-ghost mobile-view-all">
            View all{total && total > 0 ? ` ${total} ${label}` : ''} →
          </button>
        </div>
      )}
    </div>
  )
}

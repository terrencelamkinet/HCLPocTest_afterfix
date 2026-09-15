import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import SvcIcon from '../components/SvcIcon'

interface SlideDrawerProps {
  open: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  width?: string // desktop width override, default '25vw'
  closeOnLeft?: boolean // put the close/exit button on the left with a left-pointing arrow
}

export default function SlideDrawer({ open, onClose, title, children, width, closeOnLeft }: SlideDrawerProps) {
  const ref = useRef<HTMLDivElement>(null)
  // Keep rendering during the close animation so it can slide out (with bounce)
  const [rendered, setRendered] = useState(open)
  const [closing, setClosing] = useState(false)

  useEffect(() => {
    if (open) {
      setRendered(true)
      setClosing(false)
    } else if (rendered) {
      setClosing(true)
      const t = setTimeout(() => {
        setRendered(false)
        setClosing(false)
      }, 360) // match slideOutRight duration
      return () => clearTimeout(t)
    }
  }, [open, rendered])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  if (!rendered) return null

  return createPortal(
    <div
      className={`slide-drawer-wrap ${open ? 'open' : ''} ${closing ? 'closing' : ''}`}
      onClick={onClose}
    >
      <div className="slide-drawer-scrim" onClick={onClose} />
      <div
        ref={ref}
        className="slide-drawer"
        style={{ '--drawer-width': width || '25vw' } as React.CSSProperties}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Mobile drag handle ── */}
        <div className="slide-drawer-handle" onClick={onClose}>
          <div className="slide-drawer-handle-bar" />
          <div className="slide-drawer-handle-bar" />
        </div>
        <div className={`slide-drawer-header ${closeOnLeft ? 'close-left' : ''}`}>
          {closeOnLeft ? (
            <button className="slide-drawer-close slide-drawer-close--left" onClick={onClose} aria-label="Go back">
              <SvcIcon name="chevron-left" className="icon-16" />
            </button>
          ) : (
            <button className="slide-drawer-close" onClick={onClose} aria-label="Close">
              <SvcIcon name="x" className="icon-16" />
            </button>
          )}
          <h3 className="slide-drawer-title">{title || ''}</h3>
        </div>
        <div className="slide-drawer-body">
          {children}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ═══════════════════════════════════════════
//  ActionPreviewModal — Prepare → Confirm → Execute
//  Full-screen modal overlay showing the exact payload
//  the AI will write, with Confirm/Cancel buttons.
//  v2 (2026-09-09): supports MULTIPLE prepared writes in one modal
//  (batch confirm — company → contact → touchpoint chain).
// ═══════════════════════════════════════════

import { useEffect, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../components/SvcIcon'

export interface PreviewData {
  tool_key: string
  params: Record<string, unknown>
  action_id?: string
}

interface ActionPreviewModalProps {
  isOpen: boolean
  onClose: () => void
  previews: PreviewData[]
  onConfirmAll?: (actionIds: string[]) => Promise<void>
  onReject?: (action_id: string) => Promise<void>
}

type ExecutionStatus = 'idle' | 'executing' | 'success' | 'error'

/** Pretty-print a param value for display */
function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') {
    try {
      const s = JSON.stringify(value, null, 1)
      return s.length > 300 ? s.slice(0, 300) + '…' : s
    } catch {
      return String(value)
    }
  }
  return String(value)
}

/** Human-readable tool label derived from tool_key */
function toolLabel(toolKey: string): string {
  return toolKey
    .replace(/_/g, ' ')
    .replace(/create |update /, '')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/ Draft$/, '')
}

/** Compact human summary of a prepared write */
function previewSummary(p: PreviewData): string {
  const params = p.params || {}
  const name = String(params.name || params.title || params.summary || '')
  return name.length > 80 ? name.slice(0, 80) + '…' : name
}

export default function ActionPreviewModal({
  isOpen,
  onClose,
  previews,
  onConfirmAll,
  onReject,
}: ActionPreviewModalProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<ExecutionStatus>('idle')
  const [feedback, setFeedback] = useState<string>('')
  const visible = (previews || []).filter(p => p)

  // ── Reset state when modal opens ──
  useEffect(() => {
    if (isOpen) {
      setStatus('idle')
      setFeedback('')
    }
  }, [isOpen])

  // ── Escape key ──
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, onClose, status])

  // ── Lock body scroll when open ──
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [isOpen])

  // ── Backdrop click ──
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget && status !== 'executing') {
        handleClose()
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status]
  )

  const handleClose = useCallback(() => {
    if (status === 'executing') return // prevent close while executing
    onClose()
  }, [status, onClose])

  // ── Confirm / Execute all ──
  const handleExecute = useCallback(async () => {
    const ids = visible.filter(p => p.action_id).map(p => p.action_id as string)
    if (ids.length === 0 || !onConfirmAll) return
    setStatus('executing')
    setFeedback('')
    try {
      await onConfirmAll(ids)
      setStatus('success')
      setFeedback(t('actionPreview.success'))
      // Auto-close after success
      setTimeout(() => {
        onClose()
      }, 1500)
    } catch (err: unknown) {
      setStatus('error')
      setFeedback(
        err instanceof Error ? err.message : t('actionPreview.error')
      )
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, onConfirmAll, onClose])

  // ── Reject / Cancel all ──
  const handleReject = useCallback(async () => {
    if (!onReject) {
      handleClose()
      return
    }
    for (const p of visible) {
      if (p.action_id) {
        try {
          await onReject(p.action_id)
        } catch {
          // silent — rejection is advisory
        }
      }
    }
    onClose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, onReject, handleClose, onClose])

  if (!isOpen || visible.length === 0) return null

  const multi = visible.length > 1

  return createPortal(
    <div className="modal-overlay" onClick={handleBackdropClick} style={{ zIndex: 1100 }}>
      <div
        className="modal !max-w-[540px]"
        onClick={e => e.stopPropagation()}
      >
        {/* ═══ Header ═══ */}
        <div className="modal-head">
          <h2 className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-primary inline-block" />
            {multi ? `${visible.length} ${t('actionPreview.changesToReview')}` : t('actionPreview.reviewTitle')}
          </h2>
          <button
            className="modal-x"
            onClick={handleClose}
            disabled={status === 'executing'}
            aria-label="Close"
          >
            <SvcIcon name="x" className="w-4 h-4" />
          </button>
        </div>

        {/* ═══ Body ═══ */}
        <div className="modal-body">
          {visible.map((p, idx) => {
            const paramEntries = Object.entries(p.params || {})
              .filter(([k]) => !['errors', 'validated', 'company_pending'].includes(k))
            return (
              <div key={p.action_id || idx} className={multi && idx > 0 ? 'mt-5' : ''}>
                {/* Tool name card */}
                <div
                  className="rounded-xl border p-4"
                  style={{
                    background: 'var(--color-surface-offset)',
                    borderColor: 'var(--color-border)',
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
                      {toolLabel(p.tool_key)}
                    </div>
                    {previewSummary(p) && (
                      <div className="text-sm text-right truncate max-w-[60%]" style={{ color: 'var(--color-text-muted)' }}>
                        {previewSummary(p)}
                      </div>
                    )}
                  </div>
                </div>

                {/* Parameters */}
                {paramEntries.length > 0 && (
                  <div className="grid gap-2.5 mt-3">
                    {paramEntries.map(([key, value]) => {
                      const formatted = formatParamValue(value)
                      const isLong = formatted.length > 80
                      return (
                        <div
                          key={key}
                          className="rounded-lg border px-4 py-2.5"
                          style={{
                            background: 'var(--color-surface)',
                            borderColor: 'var(--color-border)',
                          }}
                        >
                          <div
                            className="text-xs font-medium mb-0.5"
                            style={{ color: 'var(--color-text-muted)' }}
                          >
                            {key
                              .replace(/_/g, ' ')
                              .replace(/\b\w/g, c => c.toUpperCase())}
                          </div>
                          <div
                            className={`text-sm leading-relaxed ${
                              isLong ? 'max-h-28 overflow-y-auto whitespace-pre-wrap' : ''
                            }`}
                            style={{ color: 'var(--color-text)' }}
                          >
                            {formatted}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}

          {/* ── Feedback banner ── */}
          {(status === 'success' || status === 'error') && feedback && (
            <div
              className={`mt-4 flex items-center gap-2.5 rounded-lg px-4 py-3 text-sm font-medium animate-in ${
                status === 'success' ? 'text-success' : 'text-notification'
              }`}
              style={{
                background:
                  status === 'success'
                    ? 'var(--color-success-highlight)'
                    : 'var(--color-notification-highlight)',
              }}
            >
              {status === 'success' ? (
                <SvcIcon name="check-circle" className="w-4 h-4 shrink-0" />
              ) : (
                <SvcIcon name="alert-circle" className="w-4 h-4 shrink-0" />
              )}
              <span>{feedback}</span>
            </div>
          )}
        </div>

        {/* ═══ Footer ═══ */}
        <div className="modal-foot">
          <button
            className="btn-secondary"
            onClick={handleReject}
            disabled={status === 'executing'}
          >
            {multi ? t('actionPreview.rejectAll') : t('actionPreview.cancel')}
          </button>
          <button
            className="btn-primary"
            onClick={handleExecute}
            disabled={status === 'executing' || !visible.some(p => p.action_id)}
          >
            {status === 'executing' ? (
              <>
                <SvcIcon name="loader-2" className="w-4 h-4 animate-spin" />
                {t('actionPreview.executing')}
              </>
            ) : (
              <>
                {multi ? t('actionPreview.confirmAll') : t('actionPreview.confirm')}
                <SvcIcon name="arrow-right" className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

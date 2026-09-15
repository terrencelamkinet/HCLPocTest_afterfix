import { useState, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  input: string
  onInputChange: (val: string) => void
  onSend: () => void
  onAbort: () => void
  isStreaming: boolean
  isLoading: boolean
  loadingSession: boolean
}

export default function ChatInput({ input, onInputChange, onSend, onAbort, isStreaming, isLoading, loadingSession }: Props) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [isFocused, setIsFocused] = useState(false)

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    onInputChange(val)
    const ta = e.target
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [onInputChange])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }, [onSend])

  const isSendable = input.trim().length > 0 && !isLoading && !loadingSession

  return (
    <div style={{
      borderTop: '1px solid var(--color-divider)',
      padding: '10px 14px max(12px, env(safe-area-inset-bottom, 12px))',
      background: 'var(--color-surface-2)',
      position: 'relative',
    }}>
      {/* Context chip placeholder — will be populated when binding to CRM record */}
      <div className="composer__input-row" style={{
        display: 'flex', alignItems: 'flex-end', gap: 0,
        padding: '6px 6px 6px 10px',
        border: `1px solid ${isFocused ? 'var(--color-primary)' : 'var(--color-border)'}`,
        borderRadius: 10,
        background: 'var(--color-surface)',
        transition: 'border-color .15s, box-shadow .15s',
        boxShadow: isFocused ? '0 0 0 3px color-mix(in oklch, var(--color-primary) 15%, transparent)' : 'none',
      }}>
        {/* Attachment button */}
        <button
          aria-label="Attach file"
          title="Attach file"
          style={{
            width: 28, height: 28, border: 0, borderRadius: 6,
            background: 'transparent', color: 'var(--color-text-faint)',
            cursor: 'pointer', display: 'grid', placeItems: 'center',
            flexShrink: 0, opacity: 0.5,
            transition: 'color var(--transition-interactive)',
          }}
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--color-text-muted)' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--color-text-faint)' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>

        {/* Textarea */}
        <textarea
          ref={inputRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={t('chat.placeholder')}
          rows={1}
          disabled={isLoading || loadingSession}
          aria-label="Chat input"
          style={{
            flex: 1, border: 0, outline: 'none', resize: 'none',
            background: 'transparent', font: 'inherit', color: 'inherit',
            maxHeight: 160, fontSize: 16, lineHeight: 1.5,
            padding: '4px 2px', minWidth: 0,
            opacity: isLoading || loadingSession ? 0.5 : 1,
          }}
        />

        {/* Send / Stop button */}
        <span className="send-btn-hitarea" style={{ display: 'inline-flex', padding: 8, margin: -8, lineHeight: 0 }}>
          {isStreaming ? (
            <button onClick={onAbort}
              aria-label={t('chat.stop')}
              title={t('chat.stop')}
              style={{
                width: 30, height: 30, border: 0, borderRadius: 6,
                display: 'grid', placeItems: 'center',
                cursor: 'pointer', background: 'var(--color-notification)',
                color: '#fff', flexShrink: 0,
                transition: 'transform var(--transition-interactive)',
              }}
              onMouseDown={e => { e.currentTarget.style.transform = 'scale(0.9)' }}
              onMouseUp={e => { e.currentTarget.style.transform = 'scale(1)' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2" />
              </svg>
            </button>
          ) : (
            <button onClick={onSend}
              disabled={!isSendable}
              aria-label={t('chat.send')}
              title={t('chat.send')}
              style={{
                width: 30, height: 30, border: 0, borderRadius: 6,
                display: 'grid', placeItems: 'center',
                cursor: isSendable ? 'pointer' : 'default',
                background: isSendable ? 'var(--color-primary)' : 'var(--color-surface-offset-2)',
                color: isSendable ? '#fff' : 'var(--color-text-faint)',
                flexShrink: 0,
                transition: 'background var(--transition-interactive), transform var(--transition-interactive)',
              }}
              onMouseDown={e => { if (isSendable) e.currentTarget.style.transform = 'scale(0.9)' }}
              onMouseUp={e => { if (isSendable) e.currentTarget.style.transform = 'scale(1)' }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </span>
      </div>

      {/* Footer: keyboard hints + quota + agent */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        color: 'var(--color-text-faint)', fontSize: 11.5,
        marginTop: 5, padding: '0 4px',
      }}>
        <span>
          <kbd style={{ fontFamily: 'inherit', fontSize: 10, padding: '1px 4px', background: 'var(--color-surface-offset)', border: '1px solid var(--color-border)', borderRadius: 3 }}>⏎</kbd>
          &nbsp;send&nbsp;
          <kbd style={{ fontFamily: 'inherit', fontSize: 10, padding: '1px 4px', background: 'var(--color-surface-offset)', border: '1px solid var(--color-border)', borderRadius: 3 }}>⇧</kbd>
          <kbd style={{ fontFamily: 'inherit', fontSize: 10, padding: '1px 4px', background: 'var(--color-surface-offset)', border: '1px solid var(--color-border)', borderRadius: 3 }}>⏎</kbd>
          &nbsp;new line
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontSize: 10, padding: '2px 6px', borderRadius: 4,
            background: 'color-mix(in oklch, var(--color-primary) 10%, var(--color-surface-offset))',
            color: 'var(--color-primary)', fontWeight: 500,
          }}>
            Personal CRM Assistant
          </span>
        </span>
      </div>
    </div>
  )
}

import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../lib/api'

interface Props {
  onExpand?: () => void
  className?: string
}

export default function WidgetAskAI({ onExpand, className }: Props) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async () => {
    const q = query.trim()
    if (!q || loading) return
    setLoading(true)
    setError(null)
    setResponse(null)
    try {
      const res = await apiClient.post<{ result: any }>(
        '/api/v1/ai/tools/get_dashboard_summary/execute',
        { query: q, period: '30d' },
      )
      const result = res?.result
      if (typeof result === 'string') {
        setResponse(result)
      } else if (result) {
        setResponse(JSON.stringify(result, null, 2))
      } else {
        setResponse(t('common.noData'))
      }
    } catch (e: any) {
      setError(e?.detail || e?.message || t('common.error'))
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setQuery('')
    setResponse(null)
    setError(null)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div
      className={className ?? ''}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        height: '100%',
        minHeight: 0,
      }}
    >
      {/* Input row */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('chat.placeholder')}
          disabled={loading}
          style={{
            flex: 1,
            padding: '8px 12px',
            fontSize: 16, // iOS 16px min to prevent auto-zoom
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
            color: 'var(--color-text)',
            outline: 'none',
            minWidth: 0,
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={loading || !query.trim()}
          aria-label="Send"
          style={{
            width: 32,
            height: 32,
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: 'none',
            cursor: loading || !query.trim() ? 'default' : 'pointer',
            background: loading || !query.trim()
              ? 'var(--color-surface-offset)'
              : 'var(--color-primary)',
            color: loading || !query.trim()
              ? 'var(--color-text-faint)'
              : '#fff',
            flexShrink: 0,
            transition: 'background var(--transition-interactive)',
          }}
        >
          {loading ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ animation: 'spin 0.8s linear infinite' }}>
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          )}
        </button>
      </div>

      {/* Response area */}
      {(response || error) && (
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            borderRadius: 'var(--radius-md)',
            background: error
              ? 'color-mix(in oklch, var(--color-notification) 8%, var(--color-surface))'
              : 'var(--color-surface-offset)',
            border: `1px solid ${
              error
                ? 'color-mix(in oklch, var(--color-notification) 20%, var(--color-border))'
                : 'var(--color-border)'
            }`,
            padding: '10px 12px',
            fontSize: 12.5,
            lineHeight: 1.5,
            color: error ? 'var(--color-notification)' : 'var(--color-text)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {response || error}
        </div>
      )}

      {/* Actions row */}
      <div style={{ display: 'flex', gap: 6, flexShrink: 0, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {(response || error) && (
            <button
              onClick={handleClear}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 10px',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                color: 'var(--color-text-muted)',
                fontSize: 11.5,
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'background var(--transition-interactive)',
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
              {t('common.clear')}
            </button>
          )}
        </div>
        {onExpand && (
          <button
            onClick={onExpand}
            title={t('greeting.openFullChat')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 10px',
              borderRadius: 'var(--radius-md)',
              border: 'none',
              background: 'color-mix(in oklch, var(--color-purple) 12%, var(--color-surface))',
              color: 'var(--color-purple)',
              fontSize: 11.5,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'background var(--transition-interactive)',
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            {t('greeting.openFullChat')}
          </button>
        )}
      </div>

      {/* Inline keyframes for spinner */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

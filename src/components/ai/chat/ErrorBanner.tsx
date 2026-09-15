import SvcIcon from '../../../components/SvcIcon'
import { useTranslation } from 'react-i18next'

export interface StreamError {
  type: 'network' | 'auth' | 'timeout' | 'server' | 'streaming'
  message: string
  retryable: boolean
}

interface Props {
  error: StreamError
  onDismiss: () => void
  onRetry: () => void
}

const iconMap: Record<string, string> = {
  network: '📡', auth: '🔒', timeout: '⏱️', server: '⚠️', streaming: '💬',
}

export default function ErrorBanner({ error, onDismiss, onRetry }: Props) {
  const { t } = useTranslation()

  const colorMap: Record<string, string> = {
    network: '--color-notification', auth: '--color-warning',
    timeout: '--color-purple', server: '--color-notification', streaming: '--color-warning',
  }
  const c = `var(${colorMap[error.type] || '--color-notification'})`

  return (
    <div style={{
      padding: '10px 14px', fontSize: 12.5,
      display: 'flex', alignItems: 'center', gap: 8,
      background: `color-mix(in oklch, ${c} 8%, var(--color-surface))`,
      borderTop: `1px solid color-mix(in oklch, ${c} 20%, var(--color-border))`,
      animation: 'fadeUp 200ms var(--ease-out) both',
    }}>
      <span>{iconMap[error.type] || '⚠️'}</span>
      <span style={{ flex: 1, color: c }}>{error.message}</span>
      {error.retryable && (
        <button onClick={onRetry}
          style={{
            border: `1px solid ${c}`, background: 'transparent', color: c,
            borderRadius: 999, padding: '3px 12px', fontSize: 11.5,
            cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
            transition: 'background var(--transition-interactive)',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = `color-mix(in oklch, ${c} 12%, transparent)` }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
        >
          {t('common.retry')}
        </button>
      )}
      <button onClick={onDismiss}
        style={{ border: 'none', background: 'none', cursor: 'pointer', color: c, padding: 4, display: 'grid', placeItems: 'center', borderRadius: 4 }}
        aria-label={t('common.close')}
      >
        <SvcIcon name="x" size={13} />
      </button>
    </div>
  )
}

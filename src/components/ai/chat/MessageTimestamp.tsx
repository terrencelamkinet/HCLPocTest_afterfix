function formatTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

function formatDateLabel(ts: number): string {
  const today = new Date()
  const d = new Date(ts)
  if (d.toDateString() === today.toDateString()) return 'Today'
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return `${d.getMonth() + 1}/${d.getDate()}`
}

interface Props {
  timestamp: number
  prevTimestamp?: number
}

export default function MessageTimestamp({ timestamp, prevTimestamp }: Props) {
  const showDivider = !prevTimestamp || formatDateLabel(timestamp) !== formatDateLabel(prevTimestamp)
  if (!showDivider) return null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      color: 'var(--color-text-faint)', fontSize: 'var(--text-xs, 12px)',
      padding: '0 4px', marginBottom: 16,
    }}>
      <div style={{ flex: 1, height: 1, background: 'var(--color-divider)' }} />
      <span>{formatDateLabel(timestamp)} · {formatTime(timestamp)}</span>
      <div style={{ flex: 1, height: 1, background: 'var(--color-divider)' }} />
    </div>
  )
}

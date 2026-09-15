import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../../components/SvcIcon'

interface Props {
  isStreaming: boolean
}

const loadingMessages = [
  '正在分析你的 CRM 資料…',
  '正在計算 Pipeline 風險…',
  '正在查詢相關記錄…',
  '正在生成回應…',
]

export default function LoadingIndicator({ isStreaming }: Props) {
  const { t } = useTranslation();
  const [showSlow, setShowSlow] = useState(false)
  const [msgIndex, setMsgIndex] = useState(0)

  useEffect(() => {
    if (isStreaming) { setShowSlow(false); return }
    const t1 = setTimeout(() => setShowSlow(true), 8000)
    const t2 = setInterval(() => setMsgIndex(i => (i + 1) % loadingMessages.length), 3000)
    return () => { clearTimeout(t1); clearInterval(t2) }
  }, [isStreaming])

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '4px 0' }}>
      <div style={{
        width: 28, height: 28, borderRadius: '50%',
        background: 'linear-gradient(135deg, var(--color-primary), #5c9df0)',
        color: '#fff', display: 'grid', placeItems: 'center',
        fontSize: 12, flexShrink: 0, marginTop: 2,
      }}>
        <SvcIcon name="sparkles" size={12} />
      </div>
      <div>
        {isStreaming ? (
          <span className="streaming-caret" style={{
            display: 'inline-block', width: 2, height: 16,
            background: 'var(--color-primary)',
            verticalAlign: 'text-bottom',
            animation: 'streaming-blink 0.8s infinite',
          }} />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div className="typing-dots" style={{ display: 'inline-flex', gap: 5 }}>
              {[0, 1, 2].map(i => (
                <span key={i}
                  style={{
                    width: 7, height: 7, borderRadius: '50%',
                    background: 'var(--color-text-muted)',
                    display: 'inline-block',
                    animation: 'thinking-dot 1.2s ease-in-out infinite',
                    animationDelay: `${i * 0.2}s`,
                  }}
                />
              ))}
            </div>
            <span style={{ fontSize: 12, color: 'var(--color-text-faint)' }}>
              {loadingMessages[msgIndex]}
            </span>
            {showSlow && (
              <span style={{ fontSize: 11.5, color: 'var(--color-text-muted)', marginTop: 2 }}>{t('chat.analysisTakesTime', { defaultValue: '這個分析需要多一點時間…' })}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

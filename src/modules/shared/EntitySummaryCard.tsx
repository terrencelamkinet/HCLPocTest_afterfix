import { useTranslation } from 'react-i18next';

/* SPEC detail-pages-polish T1: AI portal 共用 Entity Summary 卡
   （ChatboxPanel + AiSearchPanel 一齊用 — 簡潔版：冇時間戳、摘要 clamp、
     tags inline、可收埋） */
export interface AIInsightTag { label: string; kind: string }

export default function EntitySummaryCard({
  name, summary, tags, loading, onDismiss,
}: {
  name: string
  summary?: string
  tags?: AIInsightTag[]
  loading?: boolean
  onDismiss?: () => void
}) {
  const { t } = useTranslation();
  return (
    <div className="es-card">
      <div className="es-card-head">
        <span className="es-card-icon">✨</span>
        <span className="es-card-title">
          {t('chat.entitySummary', { defaultValue: 'AI 摘要' })} · {name}
        </span>
        {onDismiss && (
          <button type="button" className="es-card-x" onClick={onDismiss} aria-label="收起">
            ✕
          </button>
        )}
      </div>
      {loading ? (
        <div className="es-card-thinking"><span className="nx-ai-dot" /><span className="nx-ai-dot" /><span className="nx-ai-dot" /></div>
      ) : summary ? (
        <div className="es-card-body">{summary}</div>
      ) : (
        <div className="es-card-empty">{t('chat.noSummary', { defaultValue: '暫時未有摘要 — 可以直接問我' })}</div>
      )}
      {!loading && tags && tags.length > 0 && (
        <div className="es-card-tags">
          {tags.map((tg, i) => (
            <span className={`es-tag ${tg.kind}`} key={i}>
              {tg.kind === 'opportunity' ? '🎯' : tg.kind === 'risk' ? '⚠️' : ''} {tg.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

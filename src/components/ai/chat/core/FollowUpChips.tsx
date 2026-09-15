import SvcIcon from '../../../../components/SvcIcon'
import { useTranslation } from 'react-i18next';

/* ═══════════════════════════════════════════════════════════
   FollowUpChips — Perplexity-style "related questions" strip
   shown beneath every AI answer, encouraging deeper multi-turn
   exploration without retyping[cite:750][cite:761].
   ═══════════════════════════════════════════════════════════ */

export default function FollowUpChips({ suggestions, onSelect }: {
  suggestions: string[]; onSelect: (question: string) => void
}) {
  const { t } = useTranslation();
  if (!suggestions.length) return null
  return (
    <div className="nca-followups">
      <span className="nca-followups-label"><SvcIcon name="sparkles" size={11} />{t('chat.youMightAsk', { defaultValue: '你可能想問' })}</span>
      <div className="nca-followups-chips">
        {suggestions.map((q, i) => (
          <button key={i} className="nca-followup-chip" onClick={() => onSelect(q)}>{q}</button>
        ))}
      </div>
    </div>
  )
}

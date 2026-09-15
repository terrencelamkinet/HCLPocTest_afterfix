import { BIBLE_BOOKS, BIBLE_CHAPTERS } from '../hooks/useSecretarySettings';
import { useTranslation } from 'react-i18next';

/**
 * BookChapterSelect — 聖經書卷 + 章數 cascading select（v6.66 UX）
 *
 * 選咗書卷之後，章數 dropdown 動態產生 1–N（N = 該卷真實章數），
 * 對齊 YouVersion／Bible.com 嘅「先選書卷、先揀章」互動邏輯。
 * endBook 用 allowEndOfBook=true 時多一個「書卷尾（0）」選項（0 = 讀到書卷尾）。
 */
interface Props {
  book: string;
  chapter: number;
  onBookChange: (book: string) => void;
  onChapterChange: (chapter: number) => void;
  allowEndOfBook?: boolean;
}

export default function BookChapterSelect({
  book, chapter, onBookChange, onChapterChange, allowEndOfBook = false,
}: Props) {
  const { t } = useTranslation();
  const total = BIBLE_CHAPTERS[book] ?? 1;
  const ch = Number.isFinite(chapter) ? Math.min(Math.max(1, Math.floor(chapter)), total) : 1;

  return (
    <div className="asec-cascade">
      <div className="asec-cascade-row">
        <select
          className="asec-editor-select"
          value={book}
          onChange={e => onBookChange(e.target.value)}
          aria-label={t('settings.bibleBook', { defaultValue: '書卷' })}
        >
          {BIBLE_BOOKS.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <select
          className="asec-editor-select"
          value={ch}
          onChange={e => onChapterChange(Number(e.target.value))}
          aria-label={t('settings.bibleChapter', { defaultValue: '章數' })}
        >
          {allowEndOfBook && <option value={0}>{t('settings.bibleEndOfBook', { defaultValue: '書卷尾' })}</option>}
          {Array.from({ length: total }, (_, i) => i + 1).map(n => (
            <option key={n} value={n}>第 {n} 章</option>
          ))}
        </select>
      </div>
      <p className="asec-cascade-hint">
        {book} 共 {total} 章{allowEndOfBook ? ' ·「書卷尾」= 讀到卷尾' : ''}
      </p>
    </div>
  );
}

import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';
import { apiClient } from '../lib/api';
import { useTranslation } from 'react-i18next';

/**
 * Fullscreen search page (v6.75) — 由 AI & Search panel 嘅 fullscreen 按鈕進入。
 * 真正搜尋頁：大 input + 範圍 filter chips + 全螢幕結果清單。
 */

interface SearchResult { id: string; type: string; title: string; subtitle?: string; icon: string; }

const TYPE_EMOJI: Record<string, string> = {
  contact: '👤', company: '🏢', task: '✅',
  project: '📁', touchpoint: '🔄', note: '📝', event: '📅',
};

const FILTERS = [
  { key: '', label: '全部' },
  { key: 'contact', label: '聯絡人' },
  { key: 'company', label: '公司' },
  { key: 'task', label: '任務' },
  { key: 'project', label: '專案' },
  { key: 'touchpoint', label: '互動' },
  { key: 'note', label: '筆記' },
];

const ROUTE_MAP: Record<string, string> = {
  contact: 'contacts', company: 'companies', task: 'tasks',
  project: 'projects', touchpoint: 'touchpoints', note: 'notes',
};

export default function SearchPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [filter, setFilter] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    if (q.length < 2) { setResults([]); setSearching(false); return; }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const typesParam = filter ? `&types=${encodeURIComponent(filter)}` : '';
        const data = await apiClient.get<{ results: any[]; total?: number }>(
          `/api/v1/crm/search?q=${encodeURIComponent(q)}&limit=50${typesParam}`
        );
        setResults((data?.results || []).filter((r: any) => r.type !== 'deal').map((r: any) => ({
          /* 未命名 note 嘅 label 係空字串 → 出「未命名筆記」，唔好一行空白（2026-09-13） */
          id: String(r.id), type: r.type,
          title: r.label || (r.type === 'note' ? t('notes.untitled', { defaultValue: '未命名筆記' }) : ''),
          subtitle: r.sub,
          icon: TYPE_EMOJI[r.type] || '📄',
        })));
      } catch { setResults([]); }
      setSearching(false);
    }, 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, filter]);

  const goResult = (r: SearchResult) => {
    const base = ROUTE_MAP[r.type];
    if (base) navigate(`/${base}/${r.id}`);
  };

  return (
    <div className="sp-page">
      <header className="sp-head">
        <button type="button" className="sp-back" onClick={() => navigate(-1)} aria-label={t('common.back', { defaultValue: '返回' })}>
          <SvcIcon name="arrow-left" />
        </button>
        <div className="sp-input-wrap">
          <SvcIcon name="search" className="sp-input-icon" />
          <input
            ref={inputRef}
            className="sp-input"
            placeholder={t('search.placeholder', { defaultValue: '搜尋聯絡人、公司、商機、任務、專案…' })}
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {query && (
            <button type="button" className="sp-clear" onClick={() => setQuery('')} aria-label={t('common.clear', { defaultValue: '清除' })}>
              <SvcIcon name="x" />
            </button>
          )}
        </div>
      </header>

      <div className="sp-filters">
        {FILTERS.map(f => (
          <button
            key={f.key || 'all'}
            type="button"
            className={`sp-filter-chip ${filter === f.key ? 'active' : ''}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="sp-body">
        {!query.trim() && (
          <div className="sp-hint">
            <div className="sp-hint-icon">🔍</div>
            <p>{t('search.minChars', { defaultValue: '輸入至少 2 個字開始搜尋' })}</p>
            <p className="sp-hint-sub">{t('search.scopeHint', { defaultValue: '可以揀範圍：聯絡人、公司、商機、任務、專案、互動、筆記' })}</p>
          </div>
        )}

        {searching && results.length === 0 && <div className="sp-empty">{t('search.searching', { defaultValue: '搜尋中…' })}</div>}

        {!searching && query.trim().length >= 2 && results.length === 0 && (
          <div className="sp-empty">{t('ai.noResults', { defaultValue: '冇搜尋到相關結果' })}</div>
        )}

        {results.map(r => (
          <button key={r.type + r.id} type="button" className="sp-result-row" onClick={() => goResult(r)}>
            <span className="sp-result-icon">{r.icon}</span>
            <span className="sp-result-text">
              <strong>{r.title}</strong>
              {r.subtitle && <small>{r.subtitle}</small>}
            </span>
            <span className="sp-result-type">{r.type}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

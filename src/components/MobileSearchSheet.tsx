import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useEscapeKey } from '../lib/useEscapeKey';
import SvcIcon from '../components/SvcIcon';
import { Activity, Building2, CheckSquare, FileText, FolderKanban, TrendingUp, Users } from 'lucide-react'
import { apiClient } from '../lib/api';

interface SearchResult {
  id: string;
  type: string;
  label: string;
  sub: string;
  url: string;
}

const TYPE_ICONS: Record<string, any> = {
  contact: Users,
  company: Building2,
  deal: TrendingUp,
  task: CheckSquare,
  project: FolderKanban,
  touchpoint: Activity,
  note: FileText,
};

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Mobile search sheet — design04 「底部彈出 Modal 頁」pattern:
 * bottom sheet rises over lower 60% of screen, search bar pinned at the
 * very bottom, results scroll above it. Debounced 200ms global CRM search.
 */
export default function MobileSearchSheet({ open, onClose }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [render, setRender] = useState(false);
  const [closing, setClosing] = useState(false);

  useEscapeKey(onClose, open);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const closingRef = useRef(false);

  // Open/close with slide animation
  useEffect(() => {
    if (open) {
      setRender(true);
      setClosing(false);
      closingRef.current = false;
      setTimeout(() => inputRef.current?.focus(), 260);
    } else if (render && !closingRef.current) {
      closingRef.current = true;
      setClosing(true);
      setTimeout(() => { setRender(false); setClosing(false); closingRef.current = false; }, 240);
    }
  }, [open, render]);

  // Body scroll lock
  useEffect(() => {
    if (render) document.body.style.overflow = 'hidden';
    else document.body.style.overflow = '';
    return () => { document.body.style.overflow = ''; };
  }, [render]);

  // iOS keyboard: keep sheet above keyboard
  useEffect(() => {
    if (!render) return;
    const sheet = document.getElementById('ms-sheet');
    if (!sheet) return;
    const adjust = () => {
      const vv = window.visualViewport;
      if (!vv) return;
      const kh = window.innerHeight - vv.height;
      sheet.style.bottom = kh > 80 ? kh + 'px' : '0px';
    };
    window.visualViewport?.addEventListener('resize', adjust);
    return () => window.visualViewport?.removeEventListener('resize', adjust);
  }, [render]);

  // Debounced global search
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) { setResults([]); setLoading(false); return; }
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await apiClient.get<{ results: SearchResult[] }>(
          `/api/v1/crm/search?q=${encodeURIComponent(q)}&limit=10`
        );
        setResults((data?.results || []).filter((r: SearchResult) => r.type !== 'deal'));
      } catch { setResults([]); }
      setLoading(false);
    }, 200);
    return () => clearTimeout(timer);
  }, [query, open]);

  if (!render) return null;

  const close = () => {
    if (closingRef.current) return;
    onClose();
  };

  const go = (url: string) => {
    close();
    navigate(url);
  };

  return (
    <>
      <div className={`ms-scrim${closing ? ' ms-scrim--closing' : ''}`} onClick={close} />
      <div className={`ms-sheet${closing ? ' ms-sheet--closing' : ''}`} id="ms-sheet">
        {/* Drag handle */}
        <div className="ms-handle" />

        {/* Results area — scrolls above the pinned search bar */}
        <div className="ms-results">
          {!query.trim() && (
            <div className="ms-hint">
              <SvcIcon name="search" size={22} />
              <p>{t('header.searchPlaceholder')}</p>
            </div>
          )}
          {query.trim() && loading && results.length === 0 && (
            <div className="ms-loading">{t('common.loading', '載入中…')}</div>
          )}
          {query.trim() && !loading && results.length === 0 && (
            <div className="ms-empty">{t('header.searchNoResults')}</div>
          )}
          {results.map((r) => {
            const Icon = TYPE_ICONS[r.type] || FileText;
            return (
              <button key={r.type + r.id} className="ms-item" onClick={() => go(r.url)}>
                <span className={`ms-item-icon ms-item-icon--${r.type}`}>
                  <Icon size={16} />
                </span>
                <span className="ms-item-body">
                  <span className="ms-item-label">{r.label}</span>
                  {r.sub && <span className="ms-item-sub">{r.sub}</span>}
                </span>
                <span className="ms-item-type">{r.type}</span>
              </button>
            );
          })}
        </div>

        {/* Search bar — pinned at the very bottom */}
        <div className="ms-searchbar">
          <SvcIcon name="search" size={17} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('header.searchPlaceholder')}
            autoFocus
          />
          {query && (
            <button className="ms-clear" onClick={() => { setQuery(''); inputRef.current?.focus(); }} aria-label="Clear">
              <SvcIcon name="x" size={15} />
            </button>
          )}
        </div>
      </div>
    </>
  );
}

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '../lib/api';
import { useTranslation } from 'react-i18next';

/**
 * AddressAutocomplete — 地址輸入 + 自動完成（v6.67）
 *
 * - Debounce 350ms → GET /api/v1/geo/autocomplete（backend proxy，key 保護）
 * - Dropdown 顯示 5 個建議，click 或 Enter 揀選
 * - 揀選後 call onSelect({label, lat, lng}) — 可以將座標存埋落 settings
 */
export interface GeoSuggestion {
  label: string;
  lat: number;
  lng: number;
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSelect?: (s: GeoSuggestion) => void;
  placeholder?: string;
  lang?: string;
}

export default function AddressAutocomplete({ value, onChange, onSelect, placeholder, lang = 'zh-Hant' }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<GeoSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  // Debounce autocomplete
  useEffect(() => {
    const q = value.trim();
    if (q.length < 2) { setItems([]); setOpen(false); return; }
    setLoading(true);
    const mySeq = ++seq.current;
    const t = setTimeout(async () => {
      try {
        const res = await apiClient.get<{ suggestions: GeoSuggestion[] }>(
          `/api/v1/ai/geo/autocomplete?q=${encodeURIComponent(q)}&lang=${lang}&limit=5`
        );
        if (seq.current !== mySeq) return;
        setItems(res?.suggestions ?? []);
        setErr(false);
        setOpen(true);
      } catch {
        if (seq.current !== mySeq) return;
        setErr(true);
        setItems([]);
        setOpen(false);
      } finally {
        if (seq.current === mySeq) setLoading(false);
      }
    }, 350);
    return () => { clearTimeout(t); };
  }, [value, lang]);

  // Click outside → close
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const pick = (s: GeoSuggestion) => {
    onChange(s.label);
    onSelect?.(s);
    setOpen(false);
  };

  return (
    <div className="asec-addr" ref={boxRef}>
      <input
        type="text"
        className="asec-editor-input"
        value={value}
        placeholder={placeholder}
        onChange={e => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => { if (items.length) setOpen(true); }}
        onKeyDown={e => {
          if (e.key === 'Enter' && items.length) {
            e.preventDefault();
            pick(items[0]);
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
      />
      {loading && <span className="asec-addr-loading" />}
      {open && items.length > 0 && (
        <ul className="asec-addr-list" role="listbox">
          {items.map((s, i) => (
            <li
              key={i}
              role="option"
              className="asec-addr-item"
              onMouseDown={e => e.preventDefault()}
              onClick={() => pick(s)}
            >
              <span className="asec-addr-pin">📍</span>
              <span className="asec-addr-label">{s.label}</span>
            </li>
          ))}
        </ul>
      )}
      {err && <p className="asec-addr-err">{t('common.addressSearchUnavailable', { defaultValue: '地址搜尋暫時不可用，可以直接輸入地址' })}</p>}
    </div>
  );
}

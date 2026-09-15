import { useMemo, useState } from 'react';
import SvcIcon from '../components/SvcIcon';

/**
 * SVC Icons 檢閱頁 (/newicon) — 臨時頁面，顯示全部 137 個 SVC SVG icons 做網格檢閱。
 * 純 static，唔需要任何 backend call。用 import.meta.glob 動態載入 icons（唔 hardcode 檔名）。
 */

const ICON_PREFIX = '../assets/svc-icons/';
const ICON_SUFFIX = '-blue.svg';

const iconModules = import.meta.glob('../assets/svc-icons/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>;

interface IconEntry {
  url: string;
  name: string;
}

function buildIconEntries(): IconEntry[] {
  return Object.entries(iconModules).map(([key, url]) => {
    let name = key;
    if (name.startsWith(ICON_PREFIX)) name = name.slice(ICON_PREFIX.length);
    if (name.endsWith(ICON_SUFFIX)) name = name.slice(0, -ICON_SUFFIX.length);
    return { url, name };
  });
}

export default function SvcIconsPage() {
  const [query, setQuery] = useState('');

  const entries = useMemo(buildIconEntries, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(q));
  }, [entries, query]);

  return (
    <div className="p-8">
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <h1 className="text-2xl font-bold text-slate-900">SVC Icons ({entries.length})</h1>
        <div className="relative">
          <SvcIcon name="search" className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter icons…"
            className="pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        {query && (
          <span className="text-sm text-slate-500">
            {filtered.length} / {entries.length}
          </span>
        )}
      </div>

      <div
        className="grid gap-4"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))' }}
      >
        {filtered.map((icon) => (
          <div
            key={icon.name}
            className="bg-white rounded-lg border border-slate-200 p-4 flex flex-col items-center justify-center gap-2 min-h-[96px]"
            title={icon.name}
          >
            <img src={icon.url} alt={icon.name} width={28} height={28} className="w-7 h-7" />
            <span className="text-xs text-slate-600 w-full text-center truncate">
              {icon.name}
            </span>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <p className="text-slate-500 mt-8 text-center">No icons match “{query}”.</p>
      )}
    </div>
  );
}

import SvcIcon from '../components/SvcIcon';
import { Mail, Phone, ScanLine, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom';
import { useApi, ErrorBox } from '../lib/useApi';
import { useSearch } from '../lib/useApi';

interface Touchpoint {
  id: string;
  type: string;
  title: string;
  description: string | null;
  contact?: { id: string; name: string } | null;
  company?: { id: string; name: string } | null;
  created_at: string;
}

interface TouchpointListResponse {
  items: Touchpoint[];
  total: number;
}

const typeConfig: Record<string, { icon: any; color: string }> = {
  call: { icon: Phone, color: 'text-primary bg-primary-highlight' },
  meeting: { icon: Users, color: 'text-emerald-600 bg-emerald-100' },
  email: { icon: Mail, color: 'text-purple-600 bg-purple-100' },
  namecard: { icon: ScanLine, color: 'text-amber-600 bg-amber-100' },
};

export default function TouchpointsPage() {
  const navigate = useNavigate();
  const { query, setQuery, debounced } = useSearch();
  const { data, loading, error, refresh } = useApi<TouchpointListResponse>(
    `/api/v1/crm/touchpoints?limit=50${debounced ? `&search=${encodeURIComponent(debounced)}` : ''}`
  );

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  function timeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  }

  function getConfig(type: string) {
    return typeConfig[type] || { icon: Mail, color: 'text-slate-600 bg-slate-100' };
  }

  return (
    <div className="p-6">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">Touchpoints</span>
      </div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Touchpoints</h1>
        <p className="text-sm text-slate-500 mt-1">Activity timeline · {total} entries</p>
      </div>

      <div className="mb-4">
        <div className="flex items-center gap-2 max-w-sm px-3 py-1.5 bg-white rounded-lg border border-slate-200">
          <input
            type="text"
            placeholder="Search touchpoints..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="bg-transparent border-none outline-none text-sm w-full"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-6">
        {loading ? (
          <div className="space-y-4 animate-pulse">
            {[1,2,3].map(i => <div key={i} className="h-16 bg-slate-100 rounded-lg" />)}
          </div>
        ) : error ? (
          <ErrorBox message={error} onRetry={refresh} />
        ) : items.length === 0 ? (
          <div className="text-center text-sm text-slate-400 py-8">No touchpoints found</div>
        ) : (
          <div className="relative pl-8 space-y-0">
            <div className="absolute left-[15px] top-3 bottom-3 w-0.5 bg-slate-200" />
            {items.map((item) => {
              const cfg = getConfig(item.type);
              const Icon = cfg.icon;
              return (
                <div key={item.id} className="relative pb-6 last:pb-0">
                  <div className="absolute -left-8 top-0.5">
                    <div className={`w-[30px] h-[30px] rounded-lg ${cfg.color} flex items-center justify-center`}>
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                  </div>
                  <div className="pl-4">
                    <p className="text-sm font-medium text-slate-900">{item.title}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{item.description || '—'}</p>
                    <div className="flex items-center gap-3 mt-1 text-xs text-slate-400">
                      {item.company && <span>🏢 {item.company.name}</span>}
                      {item.contact && <span>👤 {item.contact?.name}</span>}
                      <span className="ml-auto">{timeAgo(item.created_at)}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

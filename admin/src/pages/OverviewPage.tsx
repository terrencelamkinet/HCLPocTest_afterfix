import { Card, ErrBox, Loading, useFetch } from '../ui'
import { fmtNum as formatNum } from '../api'

interface Overview {
  tenants_total: number; users_total: number; tenants_active_30d: number
  today: { calls: number; cost_usd: number; errors: number }
  week: { calls: number }
  month: { calls: number; cost_usd: number }
  plans: { free: number; pro: number; enterprise: number }
}

const PLAN_META: { key: 'free' | 'pro' | 'enterprise'; label: string; color: string }[] = [
  { key: 'free', label: 'Free', color: '#8b94a7' },
  { key: 'pro', label: 'Pro', color: 'var(--primary)' },
  { key: 'enterprise', label: 'Enterprise', color: '#7c3aed' },
]

export function OverviewPage({ onNav }: { onNav: (p: string) => void }) {
  const { data, err, loading, reload } = useFetch<Overview>('/api/v1/admin/overview')
  if (loading) return <Loading />
  if (err || !data) return <ErrBox msg={err || 'no data'} onRetry={reload} />
  const errRate = data.today.calls ? (data.today.errors / data.today.calls * 100) : 0
  return (
    <>
      <div className="grid-cards">
        <Card label="Tenants" value={data.tenants_total} sub={`${data.tenants_active_30d} active (30d)`} onClick={() => onNav('tenants')} />
        <Card label="Users" value={data.users_total} sub="verified" onClick={() => onNav('users')} />
        <Card label="今日 API Calls" value={formatNum(data.today.calls)} sub={`${data.today.errors} errors`} subCls={data.today.errors ? 'bad' : ''} onClick={() => onNav('usage')} />
        <Card label="今月成本 (USD)" value={'$' + data.month.cost_usd.toFixed(4)} sub={`${formatNum(data.month.calls)} calls`} onClick={() => onNav('usage')} />
        <Card label="今日成本 (USD)" value={'$' + data.today.cost_usd.toFixed(4)} sub="usage_events" onClick={() => onNav('reports')} />
        <Card label="今日錯誤率" value={errRate.toFixed(2) + '%'} subCls={errRate > 2 ? 'bad' : ''} sub="result_status" />
      </div>
      <div className="panel">
        <h2>方案分佈 / Plans</h2>
        <div className="grid-cards" style={{ marginBottom: 0 }}>
          {PLAN_META.map(p => (
            <Card key={p.key} label={p.label} value={data.plans?.[p.key] ?? 0}
              sub={`${data.tenants_total ? Math.round((data.plans?.[p.key] ?? 0) / data.tenants_total * 100) : 0}% of tenants`}
              onClick={() => onNav('tenants')} />
          ))}
        </div>
        <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginTop: 12 }}>
          {PLAN_META.map(p => {
            const n = data.plans?.[p.key] ?? 0
            const pct = data.tenants_total ? (n / data.tenants_total * 100) : 0
            return pct > 0 ? <div key={p.key} style={{ width: pct + '%', background: p.color }} /> : null
          })}
        </div>
        <div className="note" style={{ marginTop: 6 }}>數據源：module_settings.settings.plan（未設定預設 Free）</div>
      </div>
      <div className="panel">
        <h2>最近活躍</h2>
        <div className="note">用戶/租戶最近使用 — 前往 <a style={{ color: 'var(--primary)', cursor: 'pointer' }} onClick={() => onNav('tenants')}>Tenants 頁</a>查看詳細資料。</div>
      </div>
    </>
  )
}

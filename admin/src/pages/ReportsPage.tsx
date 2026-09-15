import { useState } from 'react'
import { api } from '../api'
import { BarChart, ErrBox, Loading, useFetch } from '../ui'

interface Overview {
  tenants_total: number; users_total: number; tenants_active_30d: number
  today: { calls: number; cost_usd: number; errors: number }
  month: { calls: number; cost_usd: number }
}

type Repo = { id: string; name: string; cat: string; catLabel: string; icon: string; desc: string; src: string; fetch: () => Promise<any>; render: (d: any) => React.ReactNode }

export function ReportsPage({ onNav, toast }: { onNav: (p: string) => void; toast: (m: string, t?: string) => void }) {
  const { data: ov, err, loading, reload } = useFetch<Overview>('/api/v1/admin/overview', [], 10000)
  const { data: topT } = useFetch<any[]>('/api/v1/admin/usage/top-tenants?days=30&metric=cost', [], 30000)
  const { data: trend } = useFetch<any[]>('/api/v1/admin/usage/trend?days=30&granularity=day', [], 30000)
  const { data: providers } = useFetch<any[]>('/api/v1/admin/reports/cost-by-provider?days=30', [], 60000)

  const [sel, setSel] = useState<Repo | null>(null)
  const [filter, setFilter] = useState('all')
  const [pvData, setPvData] = useState<any>(null)
  const [pvLoading, setPvLoading] = useState(false)

  const reports: Repo[] = [
    { id: 'tenants', name: '租戶總覽報表', cat: 'tenant', catLabel: '租戶', icon: '🏢', desc: '全部租戶清單、方案、狀態一覽', src: 'GET /admin/tenants', fetch: () => api('/api/v1/admin/tenants?page_size=100'), render: (d: any) => <MiniTable rows={(d?.items || []).map((t: any) => [t.name, t.is_active ? 'active' : 'inactive', String(t.subdomain)])} heads={['Tenant', 'Status', 'Subdomain']} /> },
    { id: 'tenant-growth', name: '租戶成長趨勢', cat: 'tenant', catLabel: '租戶', icon: '📈', desc: '新增租戶數（按月）', src: 'GET /admin/reports/tenant-growth', fetch: () => api('/api/v1/admin/reports/tenant-growth?days=365'), render: (d: any) => <BarChart points={(d || []).map((x: any) => ({ label: x.month, v: x.new_tenants }))} /> },
    { id: 'usage-trend', name: 'AI 用量趨勢', cat: 'usage', catLabel: '用量', icon: '🤖', desc: 'Calls/成本每日趨勢', src: 'GET /admin/usage/trend', fetch: () => api('/api/v1/admin/usage/trend?days=30&granularity=day'), render: (d: any) => <BarChart points={(d || []).map((x: any) => ({ label: String(x.day).slice(5), v: x.calls }))} height={120} /> },
    { id: 'top-tenants', name: 'Top 10 租戶用量', cat: 'usage', catLabel: '用量', icon: '🔥', desc: '按成本排序的租戶', src: 'GET /admin/usage/top-tenants', fetch: () => api('/api/v1/admin/usage/top-tenants?days=30&metric=cost'), render: (d: any) => <MiniTable rows={(d || []).map((x: any) => [x.tenant, String(x.calls), '$' + x.cost_usd])} heads={['Tenant', 'Calls', 'Cost']} /> },
    { id: 'top-users', name: 'Top 10 用戶用量', cat: 'usage', catLabel: '用量', icon: '👑', desc: '按成本排序嘅用戶', src: 'GET /admin/usage/top-users', fetch: () => api('/api/v1/admin/usage/top-users?days=30'), render: (d: any) => <MiniTable rows={(d || []).map((x: any) => [x.email, String(x.calls), '$' + x.cost_usd])} heads={['Email', 'Calls', 'Cost']} /> },
    { id: 'error-rate', name: '錯誤率報表', cat: 'usage', catLabel: '用量', icon: '❌', desc: '每日成功率/錯誤率', src: 'GET /admin/reports/error-rate', fetch: () => api('/api/v1/admin/reports/error-rate?days=30'), render: (d: any) => <BarChart points={(d || []).map((x: any) => ({ label: String(x.day).slice(5), v: x.error_rate * 10 }))} height={120} /> },
    { id: 'cost-provider', name: 'Provider 成本分解', cat: 'finance', catLabel: '財務', icon: '🧾', desc: '各 Provider 花費', src: 'GET /admin/reports/cost-by-provider', fetch: () => api('/api/v1/admin/reports/cost-by-provider?days=30'), render: (d: any) => <MiniTable rows={(d || []).map((x: any) => [x.provider, String(x.calls), '$' + x.cost_usd])} heads={['Provider', 'Calls', 'Cost']} /> },
    { id: 'db-size', name: '資料庫規模報表', cat: 'system', catLabel: '系統', icon: '🗄️', desc: '主要表 row count', src: 'GET /admin/reports/db-size', fetch: () => api('/api/v1/admin/reports/db-size'), render: (d: any) => <MiniTable rows={(d || []).map((x: any) => [x.table, x.rows == null ? 'n/a' : String(x.rows)])} heads={['Table', 'Rows']} /> },
  ]
  const cats = ['all', 'tenant', 'finance', 'usage', 'system']
  const catNames: Record<string, string> = { all: '全部', tenant: '租戶', finance: '財務/成本', usage: '用量/AI', system: '系統/基建' }

  const openPreview = async (r: Repo) => {
    setSel(r); setPvData(null); setPvLoading(true)
    try { setPvData(await r.fetch()) } catch (e: any) { setPvData({ err: String(e?.message || e) }) } finally { setPvLoading(false) }
  }

  const errRatePct = ov?.today.calls ? (ov.today.errors / ov.today.calls * 100) : 0

  return (
    <>
      <div className="grid-cards" id="liveCards">
        <div className="card"><div className="label">即時 API Calls（今日）</div><div className="value tick">{ov?.today.calls ?? '—'}</div><div className="sub">過去 24 小時</div></div>
        <div className="card"><div className="label">活躍租戶</div><div className="value tick">{ov?.tenants_active_30d ?? '—'}</div><div className="sub">30 日內有用量 / {ov?.tenants_total ?? '—'} 總數</div></div>
        <div className="card"><div className="label">今日成本 (USD)</div><div className="value tick">${ov ? ov.today.cost_usd.toFixed(4) : '—'}</div><div className="sub">usage_events</div></div>
        <div className="card"><div className="label">平均用量（30d calls）</div><div className="value tick">{trend && trend.length ? Math.round(trend.reduce((a: number, t: any) => a + t.calls, 0) / trend.length) : '—'}</div><div className="sub">每日平均</div></div>
        <div className="card"><div className="label">錯誤率（今日）</div><div className="value tick">{ov ? errRatePct.toFixed(2) + '%' : '—'}</div><div className={`sub ${errRatePct > 2 ? 'bad' : ''}`}>{ov?.today.errors ?? 0} errors</div></div>
        <div className="card"><div className="label">Top Provider 成本</div><div className="value tick">{providers && providers.length ? '$' + providers[0].cost_usd : '—'}</div><div className="sub">{providers?.[0]?.provider || '—'}（30d）</div></div>
      </div>

      {err && <ErrBox msg={err} onRetry={reload} />}
      {loading && !ov && <Loading />}

      <div className="section-title">
        <h2>報表庫（v1 — 真數據 {reports.length} 款）<span className="livebadge" style={{ marginLeft: 8 }}><span className="ldot" />LIVE</span></h2>
        <div className="filterbar" id="filterbar">
          {cats.map(c => (
            <div key={c} className={`chip ${filter === c ? 'active' : ''}`} onClick={() => setFilter(c)}>{catNames[c]}</div>
          ))}
        </div>
      </div>
      <div className="report-grid">
        {reports.filter(r => filter === 'all' || r.cat === filter).map(r => (
          <div key={r.id} className="rcard" onClick={() => openPreview(r)}>
            <span className={`cat ${r.cat}`}>{r.catLabel}</span>
            <div className="ricon">{r.icon}</div>
            <h3>{r.name}</h3><p>{r.desc}</p>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="flex-between">
          <h2>🔥 Top Tenants by Cost（30d）</h2>
          <span className="note" style={{ cursor: 'pointer', color: 'var(--primary)' }} onClick={() => onNav('usage')}>去 AI Usage 頁 →</span>
        </div>
        {topT && topT.length ? (
          <table><thead><tr><th>#</th><th>Tenant</th><th>Calls</th><th>Cost (USD)</th><th>Users</th></tr></thead>
            <tbody>
              {topT.slice(0, 5).map((t: any, i: number) => (
                <tr key={i}><td>{i + 1}</td><td><b>{t.tenant}</b></td><td>{t.calls}</td><td>${t.cost_usd}</td><td>{t.active_users}</td></tr>
              ))}
            </tbody></table>
        ) : <div className="note">暫無資料</div>}
      </div>

      {sel && (
        <>
          <div className="overlay show" onClick={() => setSel(null)} />
          <div className="previewPanel show">
            <div className="pv-head">
              <div><h2 id="pvTitle">{sel.icon} {sel.name}</h2><div className="meta">{sel.src}</div></div>
              <button className="drawer-close" onClick={() => setSel(null)}>✕</button>
            </div>
            <div className="pv-body">
              <div className="pv-toolbar">
                <button className="btn ghost sm" onClick={() => openPreview(sel)}>⟳ 重新整理</button>
                <button className="btn sm" onClick={() => toast('CSV 匯出（後台 v1 用 API 直接查詢 — export endpoint 喺主站）')}>⬇ CSV</button>
              </div>
              <div className="note" style={{ marginBottom: 10 }}>資料來源：{sel.src}</div>
              {pvLoading ? <Loading label="正在載入即時數據..." /> :
                pvData?.err ? <ErrBox msg={pvData.err} /> : sel.render(pvData)}
            </div>
          </div>
        </>
      )}
    </>
  )
}

function MiniTable({ rows, heads }: { rows: (string | number)[][]; heads: string[] }) {
  return (
    <table><thead><tr>{heads.map(h => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}
        {rows.length === 0 && <tr><td colSpan={heads.length} className="note" style={{ textAlign: 'center', padding: 20 }}>暫無資料</td></tr>}
      </tbody></table>
  )
}

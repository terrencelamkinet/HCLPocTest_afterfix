import { useState } from 'react'
import { ErrBox, Loading, useFetch, BarChart, formatDT } from '../ui'
import { fmtMoney, fmtNum } from '../api'

type Tab = 'trend' | 'tenant' | 'user' | 'quota'

export function UsagePage(_props: any) {
  const [tab, setTab] = useState<Tab>('trend')
  const { data: trend, err: e1, loading: l1, reload: r1 } = useFetch<any[]>('/api/v1/admin/usage/trend?days=30&granularity=day')
  const { data: topT, err: e2, loading: l2 } = useFetch<any[]>('/api/v1/admin/usage/top-tenants?days=30&metric=cost')
  const { data: topU, err: e3 } = useFetch<any[]>('/api/v1/admin/usage/top-users?days=30')
  const { data: quota } = useFetch<any>('/api/v1/admin/quota/usage')

  const tabs: { k: Tab; label: string }[] = [
    { k: 'trend', label: '趨勢' }, { k: 'tenant', label: 'Top Tenants' },
    { k: 'user', label: 'Top Users' }, { k: 'quota', label: 'Quota 榜' },
  ]
  const trendPts = (trend || []).map((t: any) => ({ label: String(t.day).slice(5), v: t.calls }))

  return (
    <>
      <div className="tabs">
        {tabs.map(t => (
          <button key={t.k} className={tab === t.k ? 'active' : ''} onClick={() => setTab(t.k)}>{t.label}</button>
        ))}
      </div>
      {tab === 'trend' && (
        <>
          <div className="panel">
            <h2>用量趨勢（30 天 — calls）</h2>
            {l1 ? <Loading /> : e1 ? <ErrBox msg={e1} onRetry={r1} /> : <BarChart points={trendPts} height={170} />}
            {trend && trend.length > 0 && (
              <table style={{ marginTop: 12 }}>
                <thead><tr><th>日期</th><th>Calls</th><th>成本 (USD)</th><th>Errors</th></tr></thead>
                <tbody>
                  {[...trend].reverse().slice(0, 14).map((t: any, i: number) => (
                    <tr key={i}><td>{String(t.day).slice(0, 10)}</td><td>{fmtNum(t.calls)}</td><td>{fmtMoney(t.cost_usd)}</td><td>{t.errors}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="two-col">
            <div className="panel"><h2>用量摘要</h2>
              {trend && trend.length > 0 ? (() => {
                const total = trend.reduce((a: number, t: any) => a + t.calls, 0)
                const cost = trend.reduce((a: number, t: any) => a + t.cost_usd, 0)
                const errs = trend.reduce((a: number, t: any) => a + t.errors, 0)
                return (
                  <table><tbody>
                    <tr><td>總 Calls</td><td><b>{fmtNum(total)}</b></td></tr>
                    <tr><td>總成本</td><td><b>{fmtMoney(cost)}</b></td></tr>
                    <tr><td>總 Errors</td><td><b>{fmtNum(errs)}</b>（{total ? (errs / total * 100).toFixed(2) : 0}%）</td></tr>
                  </tbody></table>
                )
              })() : <div className="note">30 日內暫無用量資料</div>}
            </div>
            <div className="panel"><h2>每日錯誤率</h2>
              {trend && trend.length > 0
                ? <BarChart points={trend.map((t: any) => ({ label: String(t.day).slice(5), v: t.calls ? Math.round(t.errors / t.calls * 1000) / 10 : 0 }))} height={130} />
                : <div className="note">暫無資料</div>}
            </div>
          </div>
        </>
      )}
      {tab === 'tenant' && (
        <div className="panel"><h2>Top Tenants by Cost (30d)</h2>
          {l2 ? <Loading /> : e2 ? <ErrBox msg={e2} /> : (
            <table><thead><tr><th>Tenant</th><th>Calls</th><th>Cost</th><th>Users</th><th>Last Active</th></tr></thead>
              <tbody>
                {(topT || []).map((t: any, i: number) => (
                  <tr key={i}><td><b>{t.tenant}</b></td><td>{fmtNum(t.calls)}</td><td>{fmtMoney(t.cost_usd)}</td><td>{t.active_users}</td><td>{formatDT(t.last_active)}</td></tr>
                ))}
                {(topT || []).length === 0 && <tr><td colSpan={5} className="note" style={{ textAlign: 'center', padding: 20 }}>暫無資料</td></tr>}
              </tbody></table>
          )}
        </div>
      )}
      {tab === 'user' && (
        <div className="panel"><h2>Top Users by Cost (30d)</h2>
          {e3 ? <ErrBox msg={e3} /> : (
            <table><thead><tr><th>Email</th><th>Tenant</th><th>Calls</th><th>Cost</th></tr></thead>
              <tbody>
                {(topU || []).map((t: any, i: number) => (
                  <tr key={i}><td>{t.email}</td><td>{t.tenant}</td><td>{fmtNum(t.calls)}</td><td>{fmtMoney(t.cost_usd)}</td></tr>
                ))}
                {(topU || []).length === 0 && <tr><td colSpan={4} className="note" style={{ textAlign: 'center', padding: 20 }}>暫無資料</td></tr>}
              </tbody></table>
          )}
        </div>
      )}
      {tab === 'quota' && (
        <div className="panel"><h2>Quota 使用率</h2>
          {quota?.items?.length ? (
            <table><thead><tr><th>Tenant</th><th>Email</th><th>Period</th><th>Used/Limit</th><th>%</th></tr></thead>
              <tbody>
                {quota.items.map((q: any, i: number) => (
                  <tr key={i}>
                    <td>{q.tenant_name || '—'}</td><td>{q.email || '—'}</td><td>{quota.period}</td>
                    <td>{fmtNum(q.used)}/{fmtNum(q.limit)}</td>
                    <td><div className="bar-track" style={{ width: 120, display: 'inline-block', verticalAlign: 'middle' }}><div className="bar-fill" style={{ width: `${Math.min(q.pct, 100)}%` }} /></div> {q.pct}%</td>
                  </tr>
                ))}
              </tbody></table>
          ) : <div className="note">暫無配額資料（用戶尚未啟用配額）</div>}
        </div>
      )}
    </>
  )
}

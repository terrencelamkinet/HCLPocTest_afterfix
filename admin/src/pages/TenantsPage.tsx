import { useState } from 'react'
import { ErrBox, Loading, useFetch, formatDate } from '../ui'
import { fmtNum, fmtMoney, api } from '../api'

interface Tenant { id: string; name: string; subdomain: string; is_active: boolean; created_at: string; plan?: string; owner_email?: string; owner_name?: string; members?: number; calls_30d?: number; cost_usd?: number; last_active?: string }
const PLANS = ['free', 'pro', 'enterprise'] as const
interface TenantList { items: Tenant[]; total: number; page: number }

export function TenantsPage(_props: any) {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [saving, setSaving] = useState('')
  const { data, err, loading, reload } = useFetch<TenantList>(`/api/v1/admin/tenants?page=${page}&page_size=20${search ? `&search=${encodeURIComponent(search)}` : ''}`, [page, search])
  const { data: usage } = useFetch<any[]>('/api/v1/admin/usage/top-tenants?days=30&limit=500')

  if (loading && !data) return <Loading />
  if (err) return <ErrBox msg={err} onRetry={reload} />
  const items = data?.items || []
  const costMap = new Map<string, any>((usage || []).map((u: any) => [u.tenant, u]))
  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / 20))

  return (
    <div className="panel">
      <div className="flex-between" style={{ marginBottom: 14 }}>
        <input placeholder="搜尋 tenant / subdomain / email" style={{ width: 240 }} value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }} />
        <span className="note">方案：Free / Pro / Enterprise 可直接於列表切換</span>
        <span className="note">共 {data?.total ?? 0} 個租戶</span>
      </div>
      <table>
        <thead><tr><th>Name</th><th>Owner</th><th>Plan</th><th>Status</th><th>Members</th><th>Calls (30d)</th><th>Cost (30d)</th><th>Last Active</th><th>Created</th></tr></thead>
        <tbody>
          {items.map((t: Tenant) => {
            const u = costMap.get(t.name)
            return (
              <tr key={t.id}>
                <td><b>{t.name}</b><div className="note">{t.subdomain}.penguincrm.io</div></td>
                <td>{t.owner_name ? <b style={{ fontSize: 12 }}>{t.owner_name}</b> : null}<div className="note" style={{ fontSize: 10.5 }}>{t.owner_email || '—'}</div></td>
                <td>
                  <select value={t.plan || 'free'} disabled={saving === t.id}
                    onChange={async e => {
                      const plan = e.target.value
                      setSaving(t.id)
                      try {
                        await api(`/api/v1/admin/tenants/${t.id}`, { method: 'PATCH', body: JSON.stringify({ plan }) })
                        reload()
                      } catch (ex: any) { alert('更新方案失敗：' + (ex?.message || ex)) } finally { setSaving('') }
                    }}
                    style={{ fontSize: 11.5, padding: '2px 6px', borderRadius: 6 }}>
                    {PLANS.map(pl => <option key={pl} value={pl}>{pl === 'free' ? 'Free' : pl === 'pro' ? 'Pro' : 'Enterprise'}</option>)}
                  </select>
                </td>
                <td><span className={`badge ${t.is_active ? 'ok' : 'down'}`}>{t.is_active ? 'active' : 'inactive'}</span></td>
                <td>{fmtNum(t.members ?? 0)}</td>
                <td>{fmtNum(u?.calls ?? t.calls_30d ?? 0)}</td>
                <td>{fmtMoney(u?.cost_usd ?? t.cost_usd ?? 0)}</td>
                <td>{formatDate(u?.last_active ?? t.last_active)}</td>
                <td>{formatDate(t.created_at)}</td>
              </tr>
            )
          })}
          {items.length === 0 && <tr><td colSpan={9} className="note" style={{ textAlign: 'center', padding: 20 }}>暫無租戶</td></tr>}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="flex-between" style={{ marginTop: 12 }}>
          <span className="note">第 {page}/{totalPages} 頁</span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn ghost sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>‹ 上一頁</button>
            <button className="btn ghost sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>下一頁 ›</button>
          </div>
        </div>
      )}
    </div>
  )
}

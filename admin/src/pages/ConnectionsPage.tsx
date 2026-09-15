import { ErrBox, Loading, useFetch, formatDT } from '../ui'

export function ConnectionsPage(_props: any) {
  const { data, err, loading, reload } = useFetch<any>('/api/v1/admin/connections', [], 15000)
  if (loading && !data) return <Loading />
  if (err) return <ErrBox msg={err} onRetry={reload} />
  const items = (data?.providers || []) as any[]
  return (
    <div className="panel">
      <div className="flex-between">
        <h2>Global Provider 健康（15s 自動更新）<span className={`livebadge`} style={{ marginLeft: 8 }}><span className="ldot" style={{ background: data?.overall === 'ok' ? 'var(--green)' : 'var(--orange)' }} />{data?.overall || '—'}</span></h2>
        <button className="btn ghost sm" onClick={reload}>⟳ 重新檢測</button>
      </div>
      {items.length === 0 ? <div className="note">暫無連線資料</div> : (
        <table>
          <thead><tr><th>Provider</th><th>Kind</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {items.map((c: any, i: number) => (
              <tr key={i}>
                <td><span className={`dot ${c.status === 'ok' ? 'ok' : 'down'}`} />{c.name}</td>
                <td>{c.kind}</td>
                <td><span className={`badge ${c.status === 'ok' ? 'ok' : 'down'}`}>{c.status}</span></td>
                <td>
                  {c.balance_cny != null ? `餘額 ¥${c.balance_cny}（今日 ¥${c.today_spend_cny}/${c.daily_limit_cny}）` : ''}
                  {c.config || ''}{c.latency_ms ? `${c.latency_ms}ms` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="note" style={{ marginTop: 8 }}>檢查時間：{formatDT(data?.checked_at)} — 主站深層監控（agent/SSH）P3 加入（SPEC Q4C）</div>
    </div>
  )
}

import { ErrBox, Loading, useFetch } from '../ui'

function Bar({ label, pct, warn }: { label: string; pct: number; warn?: boolean }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="flex-between"><span>{label}</span><b>{pct}%</b></div>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(pct, 100)}%`, background: warn ? '#e8912a' : undefined }} /></div>
    </div>
  )
}

export function SystemPage(_props: any) {
  const { data, err, loading, reload } = useFetch<any>('/api/v1/admin/system', [], 20000)
  if (loading && !data) return <Loading />
  if (err) return <ErrBox msg={err} onRetry={reload} />
  if (data?.error) return <ErrBox msg={data.error} onRetry={reload} />
  const boot = data.uptime_s ? new Date(data.uptime_s * 1000).toLocaleString('zh-HK') : null
  return (
    <div className="two-col">
      <div className="panel">
        <h2>資源使用率（20s 自動更新 — Admin server）</h2>
        <Bar label={`CPU（${data.cpu?.cores ?? '?'} cores）`} pct={data.cpu?.percent ?? 0} />
        <Bar label={`RAM（${data.ram?.used_gb ?? 0} / ${data.ram?.total_gb ?? 0} GB）`} pct={data.ram?.percent ?? 0} warn={(data.ram?.percent ?? 0) > 80} />
        <Bar label={`Disk（${data.disk?.used_gb ?? 0} / ${data.disk?.total_gb ?? 0} GB）`} pct={data.disk?.percent ?? 0} warn={(data.disk?.percent ?? 0) > 85} />
        <div className="note">Load avg: {(data.cpu?.load_avg || []).map((x: number) => x.toFixed(2)).join(' / ')} · 開機時間: {boot || '—'}</div>
        <div className="note" style={{ marginTop: 6 }}>主站深層監控（agent/SSH）P3 加入 — SPEC Q4C</div>
      </div>
      <div className="panel"><h2>Top Processes</h2>
        {(data.top_processes || []).length === 0 ? <div className="note">暫無資料</div> : (
          <table><thead><tr><th>Process</th><th>PID</th><th>CPU%</th><th>MEM%</th></tr></thead>
            <tbody>
              {(data.top_processes || []).map((p: any, i: number) => (
                <tr key={i}><td>{p.name}</td><td>{p.pid}</td><td>{p.cpu?.toFixed?.(1) ?? p.cpu}</td><td>{p.mem_pct?.toFixed?.(1) ?? p.mem_pct}</td></tr>
              ))}
            </tbody></table>
        )}
      </div>
    </div>
  )
}

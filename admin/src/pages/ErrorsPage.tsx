import { useState } from 'react'
import { Card, ErrBox, Loading, useFetch } from '../ui'

const TH: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 13 }

function Tbl({ heads, rows }: { heads: string[]; rows: (string | number)[][] }) {
  return (
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>{heads.map((h, i) => <th key={i} style={TH}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j} style={TD}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface ErrRow {
  occurred_at: string; method: string; path: string; status_code: number
  error_type: string; message: string; tenant_id: string | null
}
interface AggRow {
  hour: string; path: string; error_type: string; status_code: number; hits: number
}
interface ErrReport {
  window_hours: number; total: number; by_hour_path: AggRow[]; recent: ErrRow[]
}

const WINDOWS: { h: number; label: string }[] = [
  { h: 1, label: '1 小時' }, { h: 24, label: '24 小時' }, { h: 168, label: '7 日' },
]

export function ErrorsPage(_props: { toast: (m: string, t?: string) => void }) {
  const [hours, setHours] = useState(24)
  const { data, err, loading, reload } = useFetch<ErrReport>(
    `/api/v1/admin/reports/errors?hours=${hours}`, [hours], 30000,
  )

  const agg = data?.by_hour_path || []
  const recent = data?.recent || []
  const total = data?.total ?? 0
  const winLabel = WINDOWS.find(w => w.h === hours)?.label ?? ''

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14, marginBottom: 18 }}>
        <Card
          label={`錯誤總數 · ${winLabel}`}
          value={loading && !data ? '…' : total}
          sub="未處理 exception + 5xx（唔計 4xx）"
        />
        <Card label="受影響路徑" value={new Set(agg.map(a => a.path)).size} sub="hour × path × type 聚合" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {WINDOWS.map(w => (
            <button
              key={w.h}
              className={hours === w.h ? 'btn primary' : 'btn'}
              onClick={() => setHours(w.h)}
            >{w.label}</button>
          ))}
        </div>
      </div>

      {err ? <ErrBox msg={String(err)} onRetry={reload} /> : null}
      {loading && !data ? <Loading /> : null}

      {data && total === 0 ? (
        <Card label="✅ 窗口內冇錯誤" value="0" sub="所有未處理 exception 同 5xx 都會喺呢度出現" />
      ) : null}

      {agg.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <h3 style={{ margin: '4px 0 10px' }}>按時間 × 路徑 × 類型</h3>
          <Tbl
            heads={['時間（小時）', '路徑', '類型', 'HTTP', '次數']}
            rows={agg.map(a => [
              String(a.hour).replace('T', ' ').slice(0, 16), a.path, a.error_type,
              String(a.status_code), String(a.hits),
            ])}
          />
        </div>
      ) : null}

      {recent.length > 0 ? (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ margin: '4px 0 10px' }}>最近 20 筆</h3>
          <Tbl
            heads={['時間', '方法', '路徑', 'HTTP', '類型', '訊息', 'Tenant']}
            rows={recent.map(r => [
              String(r.occurred_at).replace('T', ' ').slice(0, 19),
              r.method, r.path, String(r.status_code), r.error_type,
              r.message?.slice(0, 120) ?? '', r.tenant_id ? String(r.tenant_id).slice(0, 8) : '—',
            ])}
          />
        </div>
      ) : null}

      <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 16 }}>
        記錄唔包含 request body / headers（避免 secrets 落入 log）；message 同 traceback 各截斷 4000 字。
      </p>
    </div>
  )
}

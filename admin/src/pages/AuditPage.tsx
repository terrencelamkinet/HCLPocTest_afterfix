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

interface AuditRow {
  occurred_at: string; event_type: string; tenant_id: string | null
  user_id: string | null; session_id: string | null; detail: unknown
}
interface AuditReport {
  window_hours: number; total: number
  by_event_type: { event_type: string; hits: number; tenants: number }[]
  by_day: { day: string; hits: number }[]
  recent: AuditRow[]
}

const WINDOWS: { h: number; label: string }[] = [
  { h: 24, label: '24 小時' }, { h: 168, label: '7 日' }, { h: 720, label: '30 日' },
]

export function AuditPage(_props: { toast: (m: string, t?: string) => void }) {
  const [hours, setHours] = useState(168)
  const [evFilter, setEvFilter] = useState('')
  const qs = `/api/v1/admin/reports/audit?hours=${hours}${evFilter ? `&event_type=${encodeURIComponent(evFilter)}` : ''}`
  const { data, err, loading, reload } = useFetch<AuditReport>(qs, [hours, evFilter], 60000)

  const types = data?.by_event_type || []
  const recent = data?.recent || []
  const winLabel = WINDOWS.find(w => w.h === hours)?.label ?? ''

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14, marginBottom: 18 }}>
        <Card label={`審計事件 · ${winLabel}`} value={loading && !data ? '…' : (data?.total ?? 0)} sub="AI 動作 / 檢索 / 系統事件" />
        <Card label="事件類型" value={types.length} sub="按類型分佈" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {WINDOWS.map(w => (
            <button key={w.h} className={hours === w.h ? 'btn primary' : 'btn'} onClick={() => setHours(w.h)}>{w.label}</button>
          ))}
        </div>
      </div>

      {err ? <ErrBox msg={String(err)} onRetry={reload} /> : null}
      {loading && !data ? <Loading /> : null}

      {types.length > 0 ? (
        <>
          <h3 style={{ margin: '4px 0 10px' }}>
            事件類型分佈
            {evFilter ? (
              <button className="btn" style={{ marginLeft: 10, padding: '4px 10px' }} onClick={() => setEvFilter('')}>
                ✕ 清除篩選：{evFilter}
              </button>
            ) : null}
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
            {types.map(t => (
              <button
                key={t.event_type}
                className={evFilter === t.event_type ? 'btn primary' : 'btn'}
                style={{ padding: '6px 12px' }}
                onClick={() => setEvFilter(evFilter === t.event_type ? '' : t.event_type)}
                title={`${t.tenants} 個 tenant`}
              >{t.event_type} · {t.hits}</button>
            ))}
          </div>
        </>
      ) : null}

      {data && data.total === 0 ? (
        <Card label="窗口內冇審計記錄" value="0" sub="AI 動作 / 檢索事件出現時會喺呢度" />
      ) : null}

      {recent.length > 0 ? (
        <>
          <h3 style={{ margin: '4px 0 10px' }}>最近 50 筆</h3>
          <Tbl
            heads={['時間', '事件', 'Tenant', 'User', 'Session', 'Detail']}
            rows={recent.map(r => [
              String(r.occurred_at).replace('T', ' ').slice(0, 19),
              r.event_type,
              r.tenant_id ? String(r.tenant_id).slice(0, 8) : '—',
              r.user_id ? String(r.user_id).slice(0, 8) : '—',
              r.session_id ? String(r.session_id).slice(0, 8) : '—',
              r.detail ? JSON.stringify(r.detail).slice(0, 160) : '',
            ])}
          />
        </>
      ) : null}

      <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 16 }}>
        審計唔記原文：檢索事件只存 query SHA-256 + 命中 doc/chunk id（見 app/ai/rag/audit.py）。
      </p>
    </div>
  )
}

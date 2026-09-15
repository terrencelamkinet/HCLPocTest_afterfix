import { useState } from 'react'
import { Card, ErrBox, Loading, useFetch } from '../ui'

const TH: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }
const TD: React.CSSProperties = { padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 13 }

const GREEN = '#16a34a'
const RED = '#dc2626'
const GREY = 'var(--muted)'

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

interface ProbeStat {
  total: number; ok: number; pct: number | null
  avg_latency_ms: number | null
  latest_ok: boolean | null; latest_at: string | null; latest_error: string | null
  down: boolean
}
interface Incident {
  probe_name: string; started_at: string; ended_at: string
  duration_min: number; failed_probes: number; resolved: boolean
}
interface UptimeReport {
  window_hours: number
  probes: Record<string, ProbeStat>
  incidents: Incident[]
  generated_at: string
}

const WINDOWS: { h: number; label: string }[] = [
  { h: 1, label: '1 小時' }, { h: 24, label: '24 小時' }, { h: 168, label: '7 日' },
]

const LABELS: Record<string, string> = {
  main_api: '主 API（PenguinCRM）',
  admin_api: 'Admin API',
  admin_web: 'Admin Console',
}

function fmt(ts: string | null): string {
  return ts ? String(ts).replace('T', ' ').slice(0, 19) : '—'
}

export function StatusPage(_props: { toast: (m: string, t?: string) => void }) {
  const [hours, setHours] = useState(24)
  const { data, err, loading, reload } = useFetch<UptimeReport>(
    `/api/v1/admin/reports/uptime?hours=${hours}`, [hours], 60000)

  const entries = Object.entries(data?.probes || {})
  const down = entries.filter(([, s]) => s.down)
  const incidents = data?.incidents || []
  const openIncidents = incidents.filter(i => !i.resolved)

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 18, alignItems: 'center' }}>
        {WINDOWS.map(w => (
          <button key={w.h} className={hours === w.h ? 'btn primary' : 'btn'} onClick={() => setHours(w.h)}>{w.label}</button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: GREY }}>
          最後更新：{fmt(data?.generated_at ?? null)}
        </span>
      </div>

      {err ? <ErrBox msg={String(err)} onRetry={reload} /> : null}
      {loading && !data ? <Loading /> : null}

      {data ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginBottom: 18 }}>
            {entries.map(([name, s]) => (
              <div key={name} className="card" style={{ borderLeft: `4px solid ${s.latest_ok === false ? RED : s.latest_ok === true ? GREEN : GREY}` }}>
                <div style={{ fontSize: 12, color: GREY }}>{LABELS[name] || name}</div>
                <div style={{ fontSize: 22, fontWeight: 600, margin: '4px 0 2px', color: s.latest_ok === false ? RED : GREEN }}>
                  {s.latest_ok === false ? '● 故障中' : s.latest_ok === true ? '● 正常' : '● 冇數據'}
                </div>
                <div style={{ fontSize: 13 }}>
                  Uptime：<b>{s.pct === null ? '—' : `${s.pct}%`}</b>
                  <span style={{ color: GREY }}>（{s.ok}/{s.total}）</span>
                </div>
                <div style={{ fontSize: 13 }}>平均延遲：<b>{s.avg_latency_ms === null ? '—' : `${s.avg_latency_ms} ms`}</b></div>
                <div style={{ fontSize: 12, color: GREY, marginTop: 2 }}>最後探測：{fmt(s.latest_at)}</div>
                {s.latest_error ? <div style={{ fontSize: 12, color: RED, marginTop: 2 }}>{s.latest_error}</div> : null}
              </div>
            ))}
          </div>

          <div style={{ marginBottom: 8, fontSize: 14 }}>
            {down.length === 0
              ? <span style={{ color: GREEN }}>✅ 全部服務正常</span>
              : <span style={{ color: RED }}>🔴 {down.length} 個服務故障中</span>}
            {openIncidents.length > 0 ? <span style={{ color: RED }}>　· 未解決 incident：{openIncidents.length}</span> : null}
          </div>

          <h3 style={{ margin: '12px 0 10px' }}>Incidents（窗口內）</h3>
          {incidents.length === 0 ? (
            <Card label="窗口內冇 incident" value="0" sub="服務一直正常" />
          ) : (
            <Tbl
              heads={['服務', '開始', '結束', '持續（分鐘）', '失敗次數', '狀態']}
              rows={incidents.map(i => [
                LABELS[i.probe_name] || i.probe_name,
                fmt(i.started_at),
                fmt(i.ended_at),
                i.duration_min,
                i.failed_probes,
                i.resolved ? '已恢復' : '未解決',
              ])}
            />
          )}

          <p style={{ color: GREY, fontSize: 12, marginTop: 16 }}>
            定義：連續 ≥2 次探測失敗 = 一個 incident（單次 blip 唔算，避免誤報）。探測每 2 分鐘一次。
          </p>
        </>
      ) : null}
    </div>
  )
}

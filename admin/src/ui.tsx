import { useEffect, useState } from 'react'
import { api, ApiError } from './api'

export function useFetch<T>(path: string, deps: unknown[] = [], pollMs = 0): { data: T | null; err: string; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const reload = () => setTick(t => t + 1)
  useEffect(() => {
    let alive = true
    setLoading(true)
    api<T>(path).then(d => { if (alive) { setData(d); setErr('') } })
      .catch(e => { if (alive) setErr(e instanceof ApiError ? e.message : String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path, tick, ...deps])
  useEffect(() => {
    if (!pollMs) return
    const iv = setInterval(reload, pollMs)
    return () => clearInterval(iv)
  }, [pollMs])
  return { data, err, loading, reload }
}

export function Loading({ label = '載入中...' }: { label?: string }) {
  return <div className="pv-loading"><div className="spin" />{label}</div>
}

export function ErrBox({ msg, onRetry }: { msg: string; onRetry?: () => void }) {
  return <div className="err-box">⚠️ {msg}{onRetry && <button className="btn ghost sm" style={{ marginLeft: 10 }} onClick={onRetry}>重試</button>}</div>
}

export function Card({ label, value, sub, subCls, onClick }: { label: string; value: React.ReactNode; sub?: string; subCls?: string; onClick?: () => void }) {
  return (
    <div className="card" onClick={onClick}>
      <div className="label">{label}</div>
      <div className="value">{value ?? '—'}</div>
      {sub && <div className={`sub ${subCls || ''}`}>{sub}</div>}
    </div>
  )
}

export function BarChart({ points, height = 130 }: { points: { label: string; v: number }[]; height?: number }) {
  const max = Math.max(...points.map(p => p.v), 1)
  return (
    <div className="chart-mock" style={{ height }}>
      {points.map((p, i) => (
        <div key={i} className="chart-col" title={`${p.label}: ${p.v.toLocaleString()}`}>
          <div className="bar" style={{ height: `${Math.max((p.v / max) * 100, 2)}%` }} />
        </div>
      ))}
    </div>
  )
}

export function formatDT(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-HK', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export function formatDate(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleDateString('zh-HK', { year: 'numeric', month: 'short', day: 'numeric' })
}

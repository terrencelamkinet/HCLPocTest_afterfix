import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errText } from '../lib/api'
import SvcIcon from '../components/SvcIcon'

interface Renewal {
  id: string
  name: string
  company_id: string | null
  amount: number | null
  currency: string
  renewal_date: string
  notice_days: number
  owner_id: string | null
  status: string
  days_left: number
  due: boolean
  overdue: boolean
}

const MUTED = 'var(--muted)'
const BORDER = 'var(--border)'

function badge(r: Renewal, t: (k: string) => string) {
  if (r.status === 'renewed') return { txt: t('renewals.statusRenewed'), bg: '#e8f5e9', fg: '#16a34a' }
  if (r.status === 'cancelled') return { txt: t('renewals.statusCancelled'), bg: '#f3f4f6', fg: MUTED }
  if (r.overdue) return { txt: `${t('renewals.overdue')} ${Math.abs(r.days_left)} ${t('renewals.days')}`, bg: '#fee2e2', fg: '#dc2626' }
  if (r.due) return { txt: `${r.days_left} ${t('renewals.days')}`, bg: '#fef3c7', fg: '#b45309' }
  return { txt: `${r.days_left} ${t('renewals.days')}`, bg: '#eff6ff', fg: 'var(--color-blue)' }
}

export default function RenewalsPage() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Renewal[]>([])
  const [dueCount, setDueCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [showClosed, setShowClosed] = useState(false)
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  // 新增表單
  const [name, setName] = useState('')
  const [date, setDate] = useState('')
  const [notice, setNotice] = useState('30')
  const [amount, setAmount] = useState('')

  const load = useCallback(async () => {
    setErr(null)
    try {
      const d = await api<{ renewals: Renewal[]; due_count: number }>(
        `/api/v1/crm/renewals?include_closed=${showClosed ? 'true' : 'false'}`,
      )
      setRows(d.renewals || [])
      setDueCount(d.due_count || 0)
    } catch (e) {
      setErr(errText(e) || t('renewals.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [showClosed, t])

  useEffect(() => { load() }, [load])

  async function submit() {
    if (!name.trim() || !date) return
    setBusy(true)
    setErr(null)
    try {
      await api('/api/v1/crm/renewals', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          renewal_date: date,
          notice_days: parseInt(notice, 10) || 30,
          amount: amount ? parseFloat(amount) : null,
        }),
      })
      setName(''); setDate(''); setAmount(''); setNotice('30'); setAdding(false)
      await load()
    } catch (e) {
      setErr(errText(e) || t('renewals.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  async function mark(id: string, status: string) {
    setBusy(true)
    setErr(null)
    try {
      await api(`/api/v1/crm/renewals/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
      await load()
    } catch (e) {
      setErr(errText(e) || t('renewals.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  const input: React.CSSProperties = {
    padding: '8px 10px', border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 14,
    background: 'var(--surface, #fff)', color: 'inherit', minWidth: 0,
  }

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <SvcIcon name="alarm-clock" size={22} />
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{t('renewals.title')}</h1>
        {dueCount > 0 && (
          <span style={{ background: '#fee2e2', color: '#dc2626', borderRadius: 999, padding: '2px 10px', fontSize: 13 }}>
            {dueCount} {t('renewals.dueCount')}
          </span>
        )}
        <button
          className="btn primary"
          style={{ marginLeft: 'auto' }}
          onClick={() => setAdding(v => !v)}
        >
          {adding ? t('common.cancel') : t('renewals.add')}
        </button>
      </div>
      <p style={{ color: MUTED, fontSize: 13, marginTop: 0, marginBottom: 18 }}>{t('renewals.subtitle')}</p>

      {err && (
        <div style={{ background: '#fee2e2', color: '#dc2626', padding: '10px 12px', borderRadius: 8, marginBottom: 12, fontSize: 13 }}>
          {err}
        </div>
      )}

      {adding && (
        <div style={{ border: `1px solid ${BORDER}`, borderRadius: 10, padding: 14, marginBottom: 16, display: 'grid', gap: 10, gridTemplateColumns: '2fr 1fr 1fr 1fr auto' }}>
          <input style={input} placeholder={t('renewals.fName')} value={name} onChange={e => setName(e.target.value)} />
          <input style={input} type="date" value={date} onChange={e => setDate(e.target.value)} />
          <input style={input} type="number" placeholder={t('renewals.fNotice')} value={notice} onChange={e => setNotice(e.target.value)} />
          <input style={input} type="number" placeholder={t('renewals.fAmount')} value={amount} onChange={e => setAmount(e.target.value)} />
          <button className="btn primary" disabled={busy || !name.trim() || !date} onClick={submit}>
            {busy ? '…' : t('common.save')}
          </button>
        </div>
      )}

      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: MUTED, marginBottom: 10 }}>
        <input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} />
        {t('renewals.showClosed')}
      </label>

      {loading ? (
        <div style={{ color: MUTED, padding: 20 }}>{t('renewals.loadingText')}</div>
      ) : rows.length === 0 ? (
        <div style={{ border: `1px dashed ${BORDER}`, borderRadius: 10, padding: 28, textAlign: 'center', color: MUTED }}>
          {t('renewals.empty')}
        </div>
      ) : (
        <div style={{ border: `1px solid ${BORDER}`, borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['name', 'renewal_date', 'amount', 'notice', 'actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '9px 12px', fontSize: 12, color: MUTED, borderBottom: `1px solid ${BORDER}`, whiteSpace: 'nowrap' }}>
                    {t(`renewals.th_${h}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const b = badge(r, t)
                return (
                  <tr key={r.id}>
                    <td style={{ padding: '10px 12px', borderBottom: `1px solid ${BORDER}`, fontSize: 14 }}>
                      {r.name}
                      <span style={{ marginLeft: 8, background: b.bg, color: b.fg, borderRadius: 999, padding: '2px 9px', fontSize: 12 }}>
                        {b.txt}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', borderBottom: `1px solid ${BORDER}`, fontSize: 13 }}>{r.renewal_date}</td>
                    <td style={{ padding: '10px 12px', borderBottom: `1px solid ${BORDER}`, fontSize: 13 }}>
                      {r.amount === null ? '—' : `${r.amount.toLocaleString()} ${r.currency}`}
                    </td>
                    <td style={{ padding: '10px 12px', borderBottom: `1px solid ${BORDER}`, fontSize: 13 }}>{r.notice_days} {t('renewals.days')}</td>
                    <td style={{ padding: '10px 12px', borderBottom: `1px solid ${BORDER}`, fontSize: 13, whiteSpace: 'nowrap' }}>
                      {r.status === 'active' ? (
                        <>
                          <button className="btn" disabled={busy} onClick={() => mark(r.id, 'renewed')}>{t('renewals.markRenewed')}</button>
                          <button className="btn" disabled={busy} style={{ marginLeft: 6 }} onClick={() => mark(r.id, 'cancelled')}>{t('renewals.cancel')}</button>
                        </>
                      ) : (
                        <button className="btn" disabled={busy} onClick={() => mark(r.id, 'active')}>{t('renewals.reopen')}</button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

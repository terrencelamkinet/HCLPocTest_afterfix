import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'

interface Entry { key_path: string; module: string; en: string; zh_tw: string; zh_cn: string | null; description: string | null; page_route: string | null; updated_at?: string; updated_by?: string | null }
interface ModuleInfo { module: string; keys: number; with_route: number; last_updated: string | null }

const SITE = 'https://penguincrm.io'

function EditableCell({ value, onSave, mono, wide }: { value: string; onSave: (v: string) => void; mono?: boolean; wide?: boolean }) {
  const [text, setText] = useState(value)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  useEffect(() => setText(value), [value])
  const commit = useCallback(async () => {
    if (text === value) return
    setState('saving')
    try {
      await onSave(text)
      setState('saved')
      setTimeout(() => setState('idle'), 1200)
    } catch { setState('error'); setTimeout(() => setState('idle'), 2000) }
  }, [text, value, onSave])
  return (
    <div className={`cell-wrap ${wide ? 'wide' : ''} ${mono ? 'mono' : ''}`}>
      <input value={text} onChange={e => setText(e.target.value)} onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        className="cell-input"
        onFocus={e => { e.target.style.borderColor = 'var(--primary)'; e.target.style.background = '#fff' }}
        onBlurCapture={e => { e.target.style.borderColor = 'transparent'; e.target.style.background = 'transparent' }} />
      {state === 'saving' && <span className="note" style={{ fontSize: 10 }}>…</span>}
      {state === 'saved' && <span style={{ color: 'var(--green)', fontSize: 10 }}>✓</span>}
      {state === 'error' && <span style={{ color: 'var(--red)', fontSize: 10 }}>✗</span>}
    </div>
  )
}

export function I18nPage(_props: { toast?: (m: string, t?: string) => void }) {
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [active, setActive] = useState('')
  const [rows, setRows] = useState<Entry[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const loadModules = useCallback(async () => {
    try { setModules(await api('/api/v1/i18n/modules')) } catch (e: any) { setErr(String(e?.message || e)) }
  }, [])
  useEffect(() => { loadModules() }, [loadModules])

  const loadRows = useCallback(async (module: string, q: string) => {
    setLoading(true); setErr('')
    try {
      const params = new URLSearchParams({ page_size: '500' })
      if (module) params.set('module', module)
      if (q) params.set('search', q)
      const d = await api<{ items: Entry[] }>(`/api/v1/i18n/entries?${params}`)
      setRows(d.items || [])
    } catch (e: any) { setErr(String(e?.message || e)); setRows([]) } finally { setLoading(false) }
  }, [])
  useEffect(() => {
    const t = setTimeout(() => loadRows(active, search), 300)
    return () => clearTimeout(t)
  }, [active, search, loadRows])

  const totalKeys = useMemo(() => modules.reduce((a, m) => a + m.keys, 0), [modules])

  const save = useCallback(async (kp: string, field: 'en' | 'zh_tw' | 'zh_cn' | 'description' | 'page_route', v: string) => {
    const enc = kp.split('/').map(encodeURIComponent).join('/')
    await api(`/api/v1/i18n/entries/${enc}`, { method: 'PATCH', body: JSON.stringify({ [field]: v }) })
  }, [])

  return (
    <div className="i18n-wrap">
      {/* Module tree */}
      <div className="panel i18n-modules">
        <h2 style={{ fontSize: 13, marginBottom: 8 }}>Modules（{totalKeys} keys）</h2>
        <input placeholder="🔍 搜尋 key / 文字" value={search} onChange={e => { setSearch(e.target.value); setActive('') }}
          style={{ width: '100%', marginBottom: 8, fontSize: 12 }} />
        <div className="i18n-modlist" style={{ maxHeight: '62vh', overflowY: 'auto' }}>
          {modules.map(m => (
            <div key={m.module} onClick={() => { setActive(m.module); setSearch('') }}
              className={`i18n-mod ${active === m.module ? 'active' : ''}`}>
              <span>{m.module}</span><span style={{ opacity: 0.7, fontSize: 11 }}>{m.keys}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Entries table */}
      <div className="panel i18n-table">
        <div className="flex-between" style={{ marginBottom: 8 }}>
          <h2 style={{ fontSize: 13 }}>
            {active ? `Module: ${active}` : search ? `搜尋結果（${rows.length}）` : '全部 keys'}
            <span className="note" style={{ marginLeft: 8 }}>直接編輯 + 自動儲存 — 主站即時生效</span>
          </h2>
        </div>
        {err && <div className="err-box" style={{ fontSize: 12 }}>{err}</div>}
        {loading && <div className="note">載入中…</div>}
        {!loading && (
          <div className="i18n-scroll">
            <table>
              <thead><tr>
                <th className="cell-key">Key</th>
                <th className="c-en">EN (Basic)</th>
                <th className="c-tw">繁中</th>
                <th className="c-cn">簡中</th>
                <th className="col-desc">Description（頁面/位置）</th>
                <th className="col-url">Page URL</th>
              </tr></thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.key_path} style={{ verticalAlign: 'top' }}>
                    <td className="cell-key" title={r.updated_by ? `updated by ${r.updated_by}` : undefined}>
                      {r.key_path}
                    </td>
                    <td className="c-en"><EditableCell value={r.en} onSave={v => save(r.key_path, 'en', v)} /></td>
                    <td className="c-tw"><EditableCell value={r.zh_tw} onSave={v => save(r.key_path, 'zh_tw', v)} /></td>
                    <td className="c-cn"><EditableCell value={r.zh_cn || ''} onSave={v => save(r.key_path, 'zh_cn', v)} /></td>
                    <td className="col-desc"><EditableCell value={r.description || ''} onSave={v => save(r.key_path, 'description', v)} wide /></td>
                    <td className="col-url">
                      {r.page_route ? (
                        <a href={SITE + r.page_route} target="_blank" rel="noreferrer"
                          style={{ fontSize: 11.5, color: 'var(--primary)', textDecoration: 'none' }}
                          title="主站開啟該頁">↗ {r.page_route}</a>
                      ) : <span className="note" style={{ fontSize: 11 }}>—</span>}
                    </td>
                  </tr>
                ))}
                {!loading && rows.length === 0 && (
                  <tr><td colSpan={6} className="note" style={{ textAlign: 'center', padding: 24 }}>暫無資料</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

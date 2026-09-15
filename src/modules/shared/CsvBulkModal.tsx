import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'
import { apiClient } from '../../lib/api'
import type { FieldConfig } from '../module-types'
import { buildCsv, buildDemoRows, csvColumn, csvFields, downloadCsv, parseCsv, scanRows, type RowIssue } from './csv'

interface Props {
  config: { name: string; label: string; apiPath: string; fields: FieldConfig[] }
  open: boolean
  onClose: () => void
  onImported: () => void
}

type Stage = 'idle' | 'scanned' | 'uploading' | 'done'

/**
 * 大量新增／下載（CSV）— 2026-09-12（用戶 #4）
 *   下載：整個 CSV（所有欄位）；另有 Demo CSV（5 條模擬記錄，填滿所有欄位）
 *   上載：先 scan 驗證（唔會寫入），有問題即刻列出行／欄位，客戶改好再上載
 */
export default function CsvBulkModal({ config, open, onClose, onImported }: Props) {
  const { t } = useTranslation()
  const [stage, setStage] = useState<Stage>('idle')
  const [issues, setIssues] = useState<RowIssue[]>([])
  const [unknownCols, setUnknownCols] = useState<string[]>([])
  const [fileName, setFileName] = useState('')
  const [mapped, setMapped] = useState<Record<string, any>[]>([])
  const [preview, setPreview] = useState<string[][]>([])
  const [progress, setProgress] = useState({ done: 0, total: 0, ok: 0, failed: 0 })
  const [uploadErrors, setUploadErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const fields = csvFields(config.fields)
  const reset = () => { setStage('idle'); setIssues([]); setUnknownCols([]); setMapped([]); setPreview([]); setFileName(''); setUploadErrors([]); setProgress({ done: 0, total: 0, ok: 0, failed: 0 }) }
  const close = () => { reset(); onClose() }

  const demoFileName = `${config.name}-demo-5-rows.csv`
  const allFileName = `${config.name}-all-fields-${new Date().toISOString().slice(0, 10)}.csv`

  const downloadDemo = async () => {
    setBusy(true)
    try {
      const rows = await buildDemoRows(config.fields, apiClient)
      downloadCsv(demoFileName, buildCsv(config.fields, rows))
    } finally { setBusy(false) }
  }

  const downloadAll = async () => {
    setBusy(true)
    try {
      const d = await apiClient.get<any>(`${config.apiPath}?limit=2000`)
      const rows = (d?.items || []).map((r: any) => {
        const flat: Record<string, any> = {}
        for (const f of fields) {
          const col = csvColumn(f)
          const raw = r[col] ?? r[f.key]
          flat[col] = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw.name || raw.title || raw.id || '') : raw
        }
        return flat
      })
      downloadCsv(allFileName, buildCsv(config.fields, rows))
    } catch (e: any) {
      setUploadErrors([t('csv.downloadFailed', { defaultValue: '下載失敗：' }) + (e?.detail || e?.message || '')])
    } finally { setBusy(false) }
  }

  const onFile = async (file: File) => {
    setBusy(true)
    try {
      const text = await file.text()
      const { headers, rows } = parseCsv(text)
      if (!headers.length) { setFileName(file.name); setStage('scanned'); setIssues([{ row: 0, column: '-', message: t('csv.emptyFile', { defaultValue: '檔案冇內容或冇表頭行' }) }]); return }
      const res = scanRows(config.fields, headers, rows)
      setFileName(file.name)
      setIssues(res.issues)
      setUnknownCols(res.unknownColumns)
      setMapped(res.mapped)
      setPreview(rows.slice(0, 5).map(r => r.slice(0, 6)))
      setStage('scanned')
      setUploadErrors([])
    } catch (e: any) {
      setIssues([{ row: 0, column: '-', message: String(e?.message || e) }])
      setStage('scanned')
    } finally { setBusy(false) }
  }

  const doUpload = async () => {
    setStage('uploading')
    setProgress({ done: 0, total: mapped.length, ok: 0, failed: 0 })
    const errs: string[] = []
    let ok = 0, failed = 0
    for (let i = 0; i < mapped.length; i++) {
      const body: Record<string, any> = {}
      for (const [k, v] of Object.entries(mapped[i])) if (v !== null && v !== '') body[k] = v
      try {
        await apiClient.post(config.apiPath, body)
        ok++
      } catch (e: any) {
        failed++
        const msg = typeof e?.detail === 'string' ? e.detail : Array.isArray(e?.detail) ? e.detail.map((d: any) => d.msg).join('; ') : (e?.message || '')
        errs.push(`${t('csv.row', { defaultValue: '第' })} ${i + 1}: ${msg}`)
      }
      setProgress({ done: i + 1, total: mapped.length, ok, failed })
    }
    setUploadErrors(errs)
    setStage('done')
    if (ok > 0) onImported()
  }

  if (!open) return null
  const blocked = issues.length > 0
  const cLabel = (col: string) => {
    const f = config.fields.find(x => csvColumn(x) === col)
    return f?.label || col
  }

  return (
    <div className="nx-modal-overlay is-open" onClick={e => { if (e.target === e.currentTarget) close() }}>
      <div className="nx-modal csv-modal" role="dialog" aria-modal="true" aria-label={t('csv.title', { defaultValue: '大量新增 / 下載' }) as string}>
        <div className="nx-modal-head">
          <h2>{t('csv.title', { defaultValue: '大量新增 / 下載' })} · {config.label}</h2>
          <button className="glp-icon-btn" onClick={close} aria-label={t('common.close', { defaultValue: '關閉' }) as string}>
            <SvcIcon name="x" size={16} />
          </button>
        </div>

        <div className="nx-modal-body csv-body">
          {/* 步驟 1 */}
          <section className="csv-step">
            <div className="csv-step-title">{t('csv.step1', { defaultValue: '① 下載範例（建議先睇格式）' })}</div>
            <p className="csv-hint">
              {t('csv.demoHint', { defaultValue: 'Demo CSV 有 5 條模擬記錄，每條都填滿所有欄位，可以改完直接上載。' })}
            </p>
            <div className="csv-btn-row">
              <button className="nx-btn nx-btn-secondary" onClick={downloadDemo} disabled={busy}>
                <SvcIcon name="download" size={15} /> {t('csv.downloadDemo', { defaultValue: '下載 Demo CSV（5 條）' })}
              </button>
              <button className="nx-btn nx-btn-secondary" onClick={downloadAll} disabled={busy}>
                <SvcIcon name="download" size={15} /> {t('csv.downloadAll', { defaultValue: '下載全部記錄 CSV' })}
              </button>
            </div>
          </section>

          {/* 步驟 2 */}
          <section className="csv-step">
            <div className="csv-step-title">{t('csv.step2', { defaultValue: '② 上載 CSV（會先檢查，唔會即刻寫入）' })}</div>
            <label className="csv-file">
              <input type="file" accept=".csv,text/csv" onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
              <SvcIcon name="upload" size={15} /> {fileName || t('csv.chooseFile', { defaultValue: '選擇 CSV 檔案' })}
            </label>

            {stage !== 'idle' && (
              <div className={`csv-result ${blocked ? 'bad' : 'good'}`}>
                {blocked ? (
                  <>
                    <strong>{t('csv.foundIssues', { defaultValue: '發現 {{n}} 個問題，請修正後再上載（未寫入任何資料）', n: issues.length })}</strong>
                    <ul className="csv-issues">
                      {issues.slice(0, 30).map((x, i) => (
                        <li key={i}>
                          {x.row > 0 && <span className="csv-row-tag">{t('csv.row', { defaultValue: '第' })} {x.row} {t('csv.line', { defaultValue: '行' })}</span>}
                          <span className="csv-col-tag">{cLabel(x.column)}</span> {x.message}
                        </li>
                      ))}
                      {issues.length > 30 && <li>…{t('csv.moreIssues', { defaultValue: '仲有 {{n}} 個問題', n: issues.length - 30 })}</li>}
                    </ul>
                  </>
                ) : (
                  <strong>{t('csv.allGood', { defaultValue: '✓ {{n}} 行格式正確，可以上載', n: mapped.length })}</strong>
                )}
                {unknownCols.length > 0 && (
                  <p className="csv-hint">
                    {t('csv.unknownCols', { defaultValue: '以下欄位唔屬於呢個模組，會略過：' })} {unknownCols.join(', ')}
                  </p>
                )}
                {!blocked && preview.length > 0 && (
                  <div className="csv-preview">
                    <table>
                      <tbody>
                        {preview.map((r, i) => (
                          <tr key={i}>{r.map((c, j) => <td key={j}>{c.slice(0, 18)}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* 步驟 3 */}
          {stage !== 'idle' && !blocked && (
            <section className="csv-step">
              <div className="csv-step-title">{t('csv.step3', { defaultValue: '③ 確認上載' })}</div>
              {stage === 'uploading' && (
                <p className="csv-hint">{t('csv.uploading', { defaultValue: '上載中… {{done}} / {{total}}', done: progress.done, total: progress.total })}</p>
              )}
              {stage === 'done' && (
                <>
                  <p className={progress.failed ? 'csv-result bad' : 'csv-result good'}>
                    {t('csv.doneSummary', { defaultValue: '完成：成功 {{ok}} 筆，失敗 {{failed}} 筆', ok: progress.ok, failed: progress.failed })}
                  </p>
                  {uploadErrors.length > 0 && (
                    <ul className="csv-issues">
                      {uploadErrors.slice(0, 20).map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  )}
                </>
              )}
              {stage === 'scanned' && (
                <button className="nx-btn nx-btn-primary" onClick={doUpload}>
                  <SvcIcon name="upload" size={15} /> {t('csv.confirmUpload', { defaultValue: '確認上載 {{n}} 筆', n: mapped.length })}
                </button>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

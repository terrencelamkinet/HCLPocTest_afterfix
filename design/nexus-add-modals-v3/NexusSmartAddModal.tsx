// ═══════════════════════════════════════════════════════
// NexusSmartAddModal.tsx
// 統一 Add Modal — 適用 Company / Contact / Task / Project / Touchpoint
// 完全依照 NEXUS-Design-Guide-2026-Parametric.md 參數實作
// ═══════════════════════════════════════════════════════
import { useState, useRef, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Sparkles, ScanLine, X, Loader2, Camera, Upload, AlertTriangle, Users2 } from 'lucide-react'
import { FieldsRenderer } from './FieldsRenderer'
import { buildPayload, defaultForm, apiErrorToString } from './field-utils'
import apiClient from '../../lib/api'
import type { ModuleConfig } from '../module-types'

interface AIFillResult { fields: Record<string, { value: any; confidence: number }> }
interface DuplicateMatch { id: string; name: string; similarity: number }

interface Props {
  config: ModuleConfig
  open: boolean
  onClose: () => void
  onCreated: () => void
  extraData?: Record<string, any>
}

// 只有 Contact module 顯示名片掃描；其餘 module 只有通用 AI 一鍵填寫
const NAME_CARD_ENABLED = new Set(['contact'])
// AI 填完 Company/Contact 名稱後，做 duplicate detection 嘅 module
const DUP_CHECK_ENABLED = new Set(['contact', 'company'])

export default function NexusSmartAddModal({ config, open, onClose, onCreated, extraData }: Props) {
  const { t } = useTranslation()
  const [form, setForm] = useState<Record<string, any>>(defaultForm(config.fields))
  const [aiFilledKeys, setAiFilledKeys] = useState<Record<string, number>>({})
  const [saving, setSaving] = useState(false)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [aiState, setAiState] = useState<'idle' | 'thinking' | 'done' | 'error'>('idle')
  const [dupMatch, setDupMatch] = useState<DuplicateMatch | null>(null)
  const [visible, setVisible] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) requestAnimationFrame(() => setVisible(true))
    else setVisible(false)
  }, [open])

  const showNameCardScan = NAME_CARD_ENABLED.has(config.name)
  const showDupCheck = DUP_CHECK_ENABLED.has(config.name)

  const handleChange = useCallback((key: string, value: any) => {
    setForm(f => ({ ...f, [key]: value }))
    setAiFilledKeys(prev => {
      if (!(key in prev)) return prev
      const next = { ...prev }; delete next[key]; return next
    })
  }, [])

  const checkDuplicate = async (nameValue: string) => {
    if (!showDupCheck || !nameValue) return
    try {
      const res = await apiClient.get<{ matches: DuplicateMatch[] }>(
        `${config.apiPath}/duplicate-check`, { params: { name: nameValue } }
      )
      if (res.matches?.length && res.matches[0].similarity > 0.75) setDupMatch(res.matches[0])
    } catch { /* silent — non-blocking */ }
  }

  const applyAIResult = (result: AIFillResult) => {
    const newForm = { ...form }
    const newConf = { ...aiFilledKeys }
    for (const [key, { value, confidence }] of Object.entries(result.fields)) {
      if (!config.fields.some(f => f.key === key) || value == null || value === '') continue
      newForm[key] = value; newConf[key] = confidence
    }
    setForm(newForm); setAiFilledKeys(newConf); setAiState('done')
    const nameField = config.fields.find(f => f.type === 'title')
    if (nameField && newForm[nameField.key]) checkDuplicate(newForm[nameField.key])
  }

  const handleAIParseText = async () => {
    if (!pasteText.trim()) return
    setAiState('thinking')
    try {
      const res = await apiClient.post<AIFillResult>('/api/v1/ai/smart-fill', {
        module: config.name, raw_text: pasteText,
        existing_fields: config.fields.map(f => ({ key: f.key, label: f.label, type: f.type })),
      })
      applyAIResult(res); setPasteOpen(false); setPasteText('')
    } catch (e: any) { setAiState('error'); alert(apiErrorToString(e)) }
  }

  const handleNameCardUpload = async (file: File) => {
    setAiState('thinking')
    try {
      const fd = new FormData(); fd.append('image', file); fd.append('module', config.name)
      const res = await apiClient.postForm<AIFillResult>('/api/v1/ai/scan-name-card', fd)
      applyAIResult(res)
    } catch (e: any) { setAiState('error'); alert(apiErrorToString(e)) }
  }

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleNameCardUpload(file)
  }

  const handleCreate = async () => {
    const nameField = config.fields.find(f => f.type === 'title')
    if (nameField && !form[nameField.key]?.toString().trim()) return
    const missing = config.fields.filter(f => f.required && !form[f.key]?.toString().trim())
    if (missing.length) { alert(missing.map(f => f.label).join(', ')); return }
    setSaving(true)
    try {
      await apiClient.post(config.apiPath, buildPayload(form, config.fields))
      onCreated(); handleClose()
    } catch (e: any) { alert(apiErrorToString(e)) } finally { setSaving(false) }
  }

  const handleClose = () => { setVisible(false); setTimeout(onClose, 180) }

  if (!open) return null
  const isThinking = aiState === 'thinking'
  const editableFields = config.fields.filter(f =>
    f.editable !== false &&
    !['rollup', 'formula', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by', 'unique_id'].includes(f.type) &&
    f.key !== 'created_at' && f.key !== 'updated_at'
  )

  return (
    <div className={`nx-modal-overlay ${visible ? 'is-open' : ''}`} onClick={(e) => { if (e.target === e.currentTarget) handleClose() }}>
      <div className="nx-modal" role="dialog" aria-modal="true" aria-labelledby="nx-modal-title">
        <div className="nx-modal-drag-handle" />
        <div className="nx-modal-head">
          <h2 id="nx-modal-title">{t(`pages.${config.name}.new`)}</h2>
          <button onClick={handleClose} className="nx-modal-x" aria-label={t('common.close')}><X size={18} /></button>
        </div>

        <div className="nx-modal-body">
          {showNameCardScan && (
            <div className={`nx-namecard-zone ${isThinking ? 'scanning' : ''}`} onClick={() => fileInputRef.current?.click()}>
              <input ref={fileInputRef} type="file" accept="image/*" capture="environment" className="sr-only" onChange={onFileSelected} />
              <div className="nx-namecard-icon">{isThinking ? <Loader2 size={18} className="nx-spin" /> : <ScanLine size={18} />}</div>
              <div>
                <div className="nx-namecard-title">{t('ai.scanNameCard')}</div>
                <div className="nx-namecard-sub">{isThinking ? t('ai.scanningInProgress') : t('ai.scanNameCardHint')}</div>
              </div>
              <div className="nx-namecard-cta"><Camera size={14} /><Upload size={14} /></div>
            </div>
          )}

          <div className="nx-ai-bar">
            <div className="nx-ai-bar-row">
              <div className="nx-ai-icon"><Sparkles size={15} /></div>
              <div className="nx-ai-text">
                <div className="nx-ai-title">{t('ai.oneClickFill')}</div>
                <div className="nx-ai-desc">{t('ai.oneClickFillHint')}</div>
              </div>
              {!pasteOpen && <button className="nx-ai-chip" onClick={() => setPasteOpen(true)}>{t('ai.pasteText')}</button>}
            </div>
          </div>

          {pasteOpen && (
            <div className="nx-paste-box">
              <textarea rows={4} autoFocus value={pasteText} onChange={(e) => setPasteText(e.target.value)}
                placeholder={t('ai.pasteTextPlaceholder')} className="nx-field" style={{ width: '100%' }} />
              <div className="nx-paste-actions">
                <button className="nx-btn-mini" onClick={() => { setPasteOpen(false); setPasteText('') }}>{t('common.cancel')}</button>
                <button className="nx-btn-mini primary" disabled={!pasteText.trim() || isThinking} onClick={handleAIParseText}>
                  {isThinking ? <Loader2 size={12} className="nx-spin" /> : <Sparkles size={12} />} {t('ai.analyzeAndFill')}
                </button>
              </div>
            </div>
          )}

          {isThinking && (
            <div className="nx-ai-thinking">
              <span className="nx-dot" /><span className="nx-dot" /><span className="nx-dot" />
              <span>{t('ai.thinkingMessage')}</span>
            </div>
          )}

          {dupMatch && (
            <div className="nx-dup-alert">
              <Users2 size={16} />
              <span style={{ flex: 1 }}>{t('ai.duplicateFound', { name: dupMatch.name, pct: Math.round(dupMatch.similarity * 100) })}</span>
              <button className="nx-btn nx-btn-secondary">{t('ai.viewRecord')}</button>
              <button className="nx-btn-mini" onClick={() => setDupMatch(null)}>{t('common.dismiss')}</button>
            </div>
          )}

          <div className={`nx-grid-2col ${isThinking ? 'nx-form-disabled' : ''}`}>
            {editableFields.map(f => (
              <div key={f.key} className={`nx-field ${f.gridColumn === 'full' ? 'full' : ''}`}>
                <FieldsRenderer field={f} form={form} onChange={handleChange} editOpen={true} relationData={extraData} />
                {f.key in aiFilledKeys && <AIConfidenceBadge confidence={aiFilledKeys[f.key]} />}
              </div>
            ))}
          </div>
        </div>

        <div className="nx-modal-foot">
          <button onClick={handleClose} className="nx-btn nx-btn-secondary">{t('common.cancel')}</button>
          <button onClick={handleCreate} disabled={saving || isThinking} className="nx-btn nx-btn-primary">
            {saving ? <Loader2 size={14} className="nx-spin" /> : null} {saving ? t('common.processing') : t('common.create')}
          </button>
        </div>
      </div>
    </div>
  )
}

function AIConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100)
  const low = pct < 70
  return (
    <span className={`nx-ai-badge ${low ? 'low' : ''}`} title={low ? '準確度較低，建議人手覆核' : 'AI 自動填寫'}>
      {low ? <AlertTriangle size={10} /> : <Sparkles size={10} />} {pct}%
    </span>
  )
}

// ═══════════════════════════════════════════════════════
// NexusSmartAddModal.tsx
// 統一 Add Modal — 適用 Company / Contact / Task / Project / Touchpoint
// 完全依照 NEXUS-Design-Guide-2026-Parametric.md 參數實作
// ═══════════════════════════════════════════════════════
import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'
import { FieldsRenderer } from './FieldsRenderer'
import { buildPayload, defaultForm, apiErrorToString } from './field-utils'
import { apiClient } from '../../lib/api'
import type { AddModalConfig } from './add-modal-configs'
import CameraScanSheet from '../../components/mobile/CameraScanSheet'

interface AIFillResult { fields: Record<string, { value: any; confidence: number }>; relations?: Record<string, { id: string; name: string; confidence: number; reason: string }> }
interface DuplicateMatch { id: string; name: string; similarity: number }
interface Suggestion { field: string; id: string; name: string; confidence: number; reason: string }

interface Props {
  config: AddModalConfig
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
  const [suggestions, setSuggestions] = useState<Record<string, Suggestion>>({})
  const [extraOptions, setExtraOptions] = useState<Record<string, { value: string; label: string; id?: string; isCustom?: boolean }[]>>({})
  const [visible, setVisible] = useState(false)
  /* 2026-09-11: multi-relation pickers（touchpoint 嘅 Contact / Company）係 client-side
     過濾一個預載清單。List page 會經 extraData 傳入，但 mobile quick-add（MobileNavHost）
     冇傳 → picker 得 0 個 option，完全搜尋唔到（用戶：「用戶還是不能搜尋」＋「Mobile 整個新增有問題」）。
     所以 modal 自己補 fetch config 需要、而 caller 冇提供嘅 relation resource。 */
  const [selfRelation, setSelfRelation] = useState<Record<string, { id: string; name: string }[]>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const suggestTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  /* Namecard scan v2（2026-09-07）: CameraScanSheet（live camera + 自動對位 + 微調 crop）— fill mode */
  const [cameraOpen, setCameraOpen] = useState(false)
  /* image mode: 上載圖片 → Lens crop flow（uploadImage 有值 → sheet 唔開 camera 直接用圖） */
  const [uploadImage, setUploadImage] = useState<string | null>(null)

  useEffect(() => {
    return () => { if (suggestTimerRef.current) clearTimeout(suggestTimerRef.current) }
  }, [])

  useEffect(() => {
    if (open) requestAnimationFrame(() => setVisible(true))
    else { setVisible(false); setSuggestions({}) }
  }, [open])

  // v3: fetch tenant-scoped select/status custom options（industry/category/status）
  // Fetch fail → 靜默 fallback（照用 config options，唔好 block modal）
  useEffect(() => {
    if (!open) return
    let cancelled = false
    const selectFields = config.fields.filter(f => f.type === 'select' || f.type === 'status')
    if (selectFields.length === 0) return
    ;(async () => {
      const accumulated: Record<string, { value: string; label: string; id?: string; isCustom?: boolean }[]> = {}
      for (const f of selectFields) {
        try {
          const res = await apiClient.get<{
            options: { value: string; label: string }[]
            userOptions?: { id: string; value: string; label: string }[]
          }>('/api/v1/crm/field-options', { params: { module: config.name, field: f.key } })
          if (cancelled) return
          const opts = (res.options || []).map(o => ({ value: o.value, label: o.label }))
          const userOpts = (res.userOptions || []).map(o => ({ value: o.value, label: o.label, id: o.id, isCustom: true }))
          if (opts.length || userOpts.length) accumulated[f.key] = [...opts, ...userOpts]
        } catch { /* silent — non-blocking */ }
      }
      if (!cancelled && Object.keys(accumulated).length) setExtraOptions(accumulated)
    })()
    return () => { cancelled = true }
  }, [open, config.name, config.fields])

  // 2026-09-11: 補 fetch caller 冇提供嘅 relation resource（見 selfRelation 註解）。
  // backend crm.py list endpoints 係 limit/offset — page_size 會被靜默忽略，唔可以用。
  useEffect(() => {
    if (!open) return
    const urls: Record<string, string> = {
      contacts: '/api/v1/crm/contacts?limit=1000',
      companies: '/api/v1/crm/companies?limit=1000',
      projects: '/api/v1/crm/projects?limit=1000',
    }
    const needed = new Set<string>()
    for (const f of config.fields) {
      const r = f.relation?.resource
      if (r && urls[r] && !(extraData?.[r]?.length)) needed.add(r)
    }
    if (!needed.size) return
    let cancelled = false
    ;(async () => {
      const acc: Record<string, { id: string; name: string }[]> = {}
      for (const r of needed) {
        try {
          const res = await apiClient.get<{ items: { id: string; name?: string; title?: string }[] }>(urls[r])
          acc[r] = (res?.items || []).map(x => ({ id: String(x.id), name: String(x.name || x.title || x.id) }))
        } catch { /* silent — non-blocking */ }
      }
      if (!cancelled && Object.keys(acc).length) setSelfRelation(acc)
    })()
    return () => { cancelled = true }
  }, [open, config.name, config.fields, extraData])

  // caller 提供嘅（非空）清單優先；否則用 modal 自己 fetch 嘅
  const relationData = useMemo(() => {
    const out: Record<string, { id: string; name: string }[]> = { ...selfRelation }
    for (const [k, v] of Object.entries(extraData || {})) {
      if (Array.isArray(v) && v.length) out[k] = v
    }
    return out
  }, [selfRelation, extraData])

  const showNameCardScan = NAME_CARD_ENABLED.has(config.name)
  const showDupCheck = DUP_CHECK_ENABLED.has(config.name)

  const handleChange = useCallback((key: string, value: any) => {
    setForm(f => ({ ...f, [key]: value }))
    setAiFilledKeys(prev => {
      if (!(key in prev)) return prev
      const next = { ...prev }; delete next[key]; return next
    })
  }, [])

  // v5: ＋Create custom option — POST persist，成功先寫入 form value + 更新 dropdown
  const handleCreateCustom = useCallback((fieldKey: string, label: string) => {
    if (!label.trim()) return
    // POST fail 都照樣寫入 form value（form 值唔可以丟），但 console warn
    setForm(f => ({ ...f, [fieldKey]: label.trim() }))
    setAiFilledKeys(prev => {
      if (!(fieldKey in prev)) return prev
      const next = { ...prev }; delete next[fieldKey]; return next
    })
    apiClient.post<{ id: string; value: string; label: string }>('/api/v1/crm/field-options', {
      module: config.name, field: fieldKey, value: label.trim(),
    }).then(res => {
      // 成功 → 將新 custom option 加入 dropdown（等下次 GET 都會返）
      setExtraOptions(prev => {
        const cur = prev[fieldKey] || []
        if (cur.some(o => o.value === res.value)) return prev
        return { ...prev, [fieldKey]: [...cur, { value: res.value, label: res.label, id: res.id, isCustom: true }] }
      })
    }).catch(() => { /* warn only — value already written above */ })
  }, [config.name])

  // v5: custom option 右邊 × — DELETE persist 成功後從 dropdown 移除
  const handleDeleteOption = useCallback((fieldKey: string, id: string) => {
    apiClient.delete(`/api/v1/crm/field-options/${id}`).then(() => {
      setExtraOptions(prev => {
        const cur = prev[fieldKey] || []
        return { ...prev, [fieldKey]: cur.filter(o => o.id !== id) }
      })
    }).catch(() => { /* silent — non-critical */ })
  }, [])

  const fetchSuggestions = useCallback(async (title: string) => {
    if (!title.trim()) { setSuggestions({}); return }
    try {
      const res = await apiClient.post<{ suggestions: Suggestion[] }>('/api/v1/ai/suggest-related', {
        module: config.name, title,
      })
      const next: Record<string, Suggestion> = {}
      for (const s of res.suggestions || []) {
        if (s && s.field && config.fields.some(f => f.key === s.field)) next[s.field] = s
      }
      setSuggestions(next)
    } catch { /* silent — non-blocking */ }
  }, [config.name, config.fields])

  const triggerSuggest = useCallback((title: string) => {
    if (suggestTimerRef.current) clearTimeout(suggestTimerRef.current)
    if (!title.trim()) { setSuggestions({}); return }
    suggestTimerRef.current = setTimeout(() => fetchSuggestions(title), 800)
  }, [fetchSuggestions])

  // Trigger AI suggestion on the title field (debounced)
  const handleFieldChange = useCallback((key: string, value: any) => {
    handleChange(key, value)
    const titleField = config.fields.find(f => f.type === 'title')
    if (titleField && key === titleField.key) triggerSuggest(value?.toString?.() ?? value ?? '')
  }, [handleChange, config.fields, triggerSuggest])

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
    // Relations：link 現有 records（id），照 suggest-related 嘅 pattern 設定 value + confidence badge
    // Relation field key（backend 用 company_id/contact_id）對返 config 嘅實際 field key：
    //   1) apiKey || key 直接 match
    //   2) 否則如果 field 係 companies/contacts relation（key='company'/'contact'），
    //      用 resource-based column name（company_id / contact_id）match
    for (const [key, rel] of Object.entries(result.relations || {})) {
      if (!rel?.id || rel.confidence == null || rel.confidence < 0.5) continue
      const field = config.fields.find(f => {
        const target = f.apiKey || f.key
        if (target === key) return true
        const res = f.relation?.resource
        if ((res === 'companies' && key === 'company_id' && f.key === 'company') ||
            (res === 'contacts' && key === 'contact_id' && f.key === 'contact')) return true
        return false
      })
      if (!field) continue
      newForm[field.key] = rel.id
      newConf[field.key] = rel.confidence
    }
    setForm(newForm); setAiFilledKeys(newConf); setAiState('done')
    const nameField = config.fields.find(f => f.type === 'title')
    if (nameField && newForm[nameField.key]) {
      checkDuplicate(newForm[nameField.key])
      triggerSuggest(newForm[nameField.key])
    }
  }

  const handleAIParseText = async () => {
    if (!pasteText.trim()) return
    setAiState('thinking')
    try {
      const res = await apiClient.post<AIFillResult>('/api/v1/ai/smart-fill', {
        module: config.name, raw_text: pasteText,
        existing_fields: config.fields.map(f => ({
          key: f.key, label: f.label, type: f.type,
          ...(f.options?.length ? { options: f.options.map(o => o.value ?? o) } : {}),
        })),
      })
      applyAIResult(res); setPasteOpen(false); setPasteText('')
    } catch (e: any) { setAiState('error'); alert(apiErrorToString(e)) }
  }

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // 2026-09-07: 上載圖片 → 都行 Lens 式 crop flow（CameraScanSheet image mode — adjust 四角 → 確認 → OCR）
    const reader = new FileReader()
    reader.onload = () => {
      setUploadImage(reader.result as string)
      setCameraOpen(true)
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  const handleCreate = async () => {
    const nameField = config.fields.find(f => f.type === 'title')
    if (nameField && !form[nameField.key]?.toString().trim()) return
    const missing = config.fields.filter(f => f.required && !form[f.key]?.toString().trim())
    if (missing.length) { alert(missing.map(f => f.label).join(', ')); return }
    setSaving(true)
    try {
      const payload = buildPayload(form, config.fields)
      // Omit empty optional fields so backend defaults (e.g. task priority/status) apply —
      // explicit null bypasses Pydantic field defaults → 422 string_type
      for (const f of config.fields) {
        if (!f.required && (payload[f.key] === null || payload[f.key] === '')) delete payload[f.key]
      }
      await apiClient.post(config.apiPath, payload)
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
          <button onClick={handleClose} className="nx-modal-x" aria-label={t('common.close')}><SvcIcon name="x" size={18} /></button>
        </div>

        <div className="nx-modal-body">
          {showNameCardScan && (
            <div className={`nx-namecard-zone ${isThinking ? 'scanning' : ''}`} onClick={() => setCameraOpen(true)}>
              <div className="nx-namecard-icon">{isThinking ? <SvcIcon name="loader-2" size={18} className="nx-spin" /> : <SvcIcon name="camera" size={18} />}</div>
              <div>
                <div className="nx-namecard-title">{t('ai.scanNameCard')}</div>
                <div className="nx-namecard-sub">{isThinking ? t('ai.scanningInProgress') : '影名片 — 自動對位 + 可微調四角'}</div>
              </div>
              <div className="nx-namecard-cta"><SvcIcon name="camera" size={14} /></div>
              <input ref={fileInputRef} type="file" accept="image/*" className="sr-only" onChange={onFileSelected} />
            </div>
          )}
          {showNameCardScan && !isThinking && (
            <button type="button" className="nx-upload-link" onClick={() => fileInputRef.current?.click()}
              style={{ background: 'none', border: 'none', color: 'var(--color-primary)', fontSize: 12, cursor: 'pointer', padding: '2px 0 10px', display: 'block', margin: '0 auto' }}>
              <SvcIcon name="upload" size={12} /> 或上載名片圖片
            </button>
          )}

          <div className="nx-ai-bar">
            <div className="nx-ai-bar-row">
              <div className="nx-ai-icon"><SvcIcon name="sparkles" size={15} /></div>
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
                placeholder={config.name === 'contact' ? t('ai.pasteTextPlaceholderContact', { defaultValue: t('ai.pasteTextPlaceholder') }) : t('ai.pasteTextPlaceholder')}
                aria-label={config.name === 'contact' ? t('ai.pasteTextPlaceholderContact', { defaultValue: t('ai.pasteTextPlaceholder') }) : t('ai.pasteTextPlaceholder')}
                className="nx-field" style={{ width: '100%' }} />
              <div className="nx-paste-actions">
                <button className="nx-btn-mini" onClick={() => { setPasteOpen(false); setPasteText('') }}>{t('common.cancel')}</button>
                <button className="nx-btn-mini primary" disabled={!pasteText.trim() || isThinking} onClick={handleAIParseText}>
                  {isThinking ? <SvcIcon name="loader-2" size={12} className="nx-spin" /> : <SvcIcon name="sparkles" size={12} />} {t('ai.analyzeAndFill')}
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
              <SvcIcon name="users-2" size={16} />
              <span style={{ flex: 1 }}>{t('ai.duplicateFound', { name: dupMatch.name, pct: Math.round(dupMatch.similarity * 100) })}</span>
              <button className="nx-btn nx-btn-secondary">{t('ai.viewRecord')}</button>
              <button className="nx-btn-mini" onClick={() => setDupMatch(null)}>{t('common.dismiss')}</button>
            </div>
          )}

          <div className={`nx-grid-2col ${isThinking ? 'nx-form-disabled' : ''}`}>
            {editableFields.map(f => (
              <div key={f.key} className={`nx-field ${f.gridColumn === 'full' ? 'full' : ''}`}>
                {suggestions[f.key] && (
                  <div className="nx-suggest">
                    <SvcIcon name="sparkles" size={12} />
                    <span>{t('ai.suggestPrefix')} <strong>{suggestions[f.key].name}</strong> — {suggestions[f.key].reason}</span>
                    <button
                      className="nx-btn-mini"
                      onClick={() => {
                        handleChange(f.key, suggestions[f.key].id)
                        setAiFilledKeys(prev => ({ ...prev, [f.key]: suggestions[f.key].confidence }))
                        setSuggestions(prev => { const n = { ...prev }; delete n[f.key]; return n })
                      }}
                    >{t('ai.applySuggestion')}</button>
                  </div>
                )}
                <FieldsRenderer field={f} form={form} onChange={handleFieldChange} editOpen={true} relationData={relationData} extraOptions={extraOptions} onCreateCustom={handleCreateCustom} onDeleteOption={handleDeleteOption} />
                {f.key in aiFilledKeys && <AIConfidenceBadge confidence={aiFilledKeys[f.key]} />}
              </div>
            ))}
          </div>
        </div>

        <div className="nx-modal-foot">
          <button onClick={handleClose} className="nx-btn nx-btn-secondary">{t('common.cancel')}</button>
          <button onClick={handleCreate} disabled={saving || isThinking} className="nx-btn nx-btn-primary">
            {saving ? <SvcIcon name="loader-2" size={14} className="nx-spin" /> : null} {saving ? t('common.processing') : t('common.create')}
          </button>
        </div>
      </div>
      {showNameCardScan && (
        <CameraScanSheet
          open={cameraOpen}
          mode="fill"
          fillModule={config.name}
          initialImage={uploadImage}
          onClose={() => { setCameraOpen(false); setUploadImage(null) }}
          onSaved={() => { setCameraOpen(false); setUploadImage(null) }}
          onFilled={(data: any) => { setCameraOpen(false); setUploadImage(null); applyAIResult(data as AIFillResult) }}
        />
      )}
    </div>
  )
}

function AIConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100)
  const low = pct < 70
  return (
    <span className={`nx-ai-badge ${low ? 'low' : ''}`} title={low ? '準確度較低，建議人手覆核' : 'AI 自動填寫'}>
      {low ? <SvcIcon name="alert-triangle" size={10} /> : <SvcIcon name="sparkles" size={10} />} {pct}%
    </span>
  )
}

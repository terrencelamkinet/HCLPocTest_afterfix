import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../components/SvcIcon'
import { apiClient } from '../lib/api'
import { safeExternalUrl } from '../lib/safeUrl'
import { EntitySearch } from './EntitySearch'
import type { NameCardRecord, LinkedContact } from './module-types'

/* ═══════════════════════════════════════════════════════════
   NameCardDetailModal — Original vs Cropped image compare,
   editable fields, tag management, contact linking, and
   destructive/duplicate actions.
   ═══════════════════════════════════════════════════════════ */

interface Props {
  card: NameCardRecord
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
}

export function NameCardDetailModal({ card, onClose, onSaved, onDeleted }: Props) {
  const { t } = useTranslation()
  const pd = card.parsed_data || {}
  const [imageMode, setImageMode] = useState<'original' | 'cropped'>('cropped')
  const [form, setForm] = useState({
    name: pd.name || card.name || '',
    title: pd.title || card.title || '',
    email: pd.email || card.email || '',
    phone: pd.phone || card.phone || '',
    company: pd.company || card.company || '',
  })
  const [tags, setTags] = useState<string[]>(card.tags || [])
  const [tagInput, setTagInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [linkedContact, setLinkedContact] = useState<LinkedContact | null>((card.contact as LinkedContact | null) || null)
  const [showLinkSearch, setShowLinkSearch] = useState(false)
  const linkedContactId: string = linkedContact ? linkedContact.id : ''
  /* WORKFLOW-2026-09: pending resolve state */
  const [resolving, setResolving] = useState(false)
  const isPending = (card as any).status === 'review' || (card as any).status === 'pending'
  const candRaw = (card as any).review_candidates?.[0] || card.duplicate_candidate || null
  const candName = candRaw?.name || (candRaw?.contact_id ? '現有聯絡人' : '') || '現有聯絡人'

  /* 2026-09-13 Terrence（v4 README a11y 要求）：舊版 modal 完全冇 a11y 接駁
     （grep 全檔：role= / aria-* / Escape / useEffect 全部 0 個）⇒ 補：
     Escape 關閉、開時 focus 入對話框、關時 focus 還原、鎖背景捲動。 */
  const dialogRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const prevActive = document.activeElement as HTMLElement | null
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      prevActive?.focus?.()
    }
  }, [onClose])

  const handleResolve = async (action: 'merge' | 'separate') => {
    if (action === 'merge' && !candRaw?.contact_id) {
      alert(t('nameCard.noMergeTarget', { defaultValue: '冇合併目標 — 先揀一個現有聯絡人' }))
      return
    }
    setResolving(true)
    try {
      await apiClient.post(`/api/v1/crm/name-cards/${card.id}/resolve`, { action })
      onSaved()
    } catch (e: any) {
      alert(e?.detail || e?.message || '處理失敗')
    } finally {
      setResolving(false)
    }
  }

  const handleAddTag = () => {
    const val = tagInput.trim()
    if (val && !tags.includes(val)) setTags(tg => [...tg, val])
    setTagInput('')
  }
  const removeTag = (tg: string) => setTags(tags.filter(x => x !== tg))

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiClient.patch(`/api/v1/crm/name-cards/${card.id}`, {
        ...form, tags, contact_id: linkedContact?.id || null,
      })
      onSaved()
    } catch (e: any) {
      alert(e.detail || e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleRecrop = async () => {
    await apiClient.post(`/api/v1/crm/name-cards/${card.id}/recrop`, {})
  }

  const handleDelete = async () => {
    if (!confirm(t('nameCard.confirmDelete', { defaultValue: '刪除呢張名片？' }))) return
    await apiClient.delete(`/api/v1/crm/name-cards/${card.id}`)
    onDeleted()
  }

  const handleDuplicate = async () => {
    await apiClient.post(`/api/v1/crm/name-cards/${card.id}/duplicate`, {})
    onSaved()
  }

  const handleCopyContact = () => {
    const text = `${form.name}\n${form.title}\n${form.company}\n${form.email}\n${form.phone}`
    navigator.clipboard.writeText(text)
  }

  return (
    <div className="nx-modal-overlay is-open" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="nx-modal nc-detail-modal is-open" role="dialog" aria-modal="true"
        aria-labelledby="nc-detail-title" tabIndex={-1} ref={dialogRef}>
        <div className="nx-modal-header">
          <div className="nx-modal-title" id="nc-detail-title">{t('nameCard.detailTitle', { defaultValue: '名片詳情' })}</div>
          <button type="button" className="nx-modal-x" aria-label={t('common.close', { defaultValue: '關閉' })}
            onClick={onClose}><SvcIcon name="x" size={16} /></button>
        </div>

        <div className="nc-detail-modal-body">
          {/* ═══ Left: Original vs Cropped image ═══ */}
          <div className="nc-detail-images">
            <div className="nc-image-tabs">
              <div className={`nc-image-tab ${imageMode === 'original' ? 'active' : ''}`} onClick={() => setImageMode('original')}>
                {t('nameCard.original', { defaultValue: '原圖' })}
              </div>
              <div className={`nc-image-tab ${imageMode === 'cropped' ? 'active' : ''}`} onClick={() => setImageMode('cropped')}>
                {t('nameCard.cropped', { defaultValue: '已裁剪' })}
              </div>
            </div>
            <div className="nc-image-frame">
              {(imageMode === 'original' ? card.image_url : card.cropped_image_url) ? (
                <img src={imageMode === 'original' ? card.image_url : card.cropped_image_url} alt="" />
              ) : (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>
                  {t('nameCard.imagePreview', { defaultValue: '名片圖片預覽' })}
                </div>
              )}
            </div>
            <div className="nc-image-actions">
              <button className="nx-btn nx-btn-secondary" style={{ flex: 1 }} onClick={handleRecrop}
                title={t('nameCard.recrop', { defaultValue: '重新裁剪' })}
                aria-label={t('nameCard.recrop', { defaultValue: '重新裁剪' })}>
                <SvcIcon name="rotate-cw" size={13} /> <span className="nc-btn-label">{t('nameCard.recrop', { defaultValue: '重新裁剪' })}</span>
              </button>
              <button className="nx-btn nx-btn-secondary" style={{ flex: 1 }}
                onClick={() => {
                  // 2026-09-15 SAST：image_url 由 API 回傳 → scheme allowlist + noopener
                  const u = safeExternalUrl(card.image_url);
                  if (u) window.open(u, '_blank', 'noopener,noreferrer');
                }}
                title={t('nameCard.downloadOriginal', { defaultValue: '下載原圖' })}
                aria-label={t('nameCard.downloadOriginal', { defaultValue: '下載原圖' })}>
                <SvcIcon name="download" size={13} /> <span className="nc-btn-label">{t('nameCard.downloadOriginal', { defaultValue: '下載原圖' })}</span>
              </button>
            </div>

            {/* ═══ Contact linking box ═══ */}
            <div className="nc-link-contact-box">
              {linkedContact ? (
                <div className="nc-link-contact-linked">
                  <div className="nc-link-avatar">{(linkedContact.name || '?').slice(0, 1)}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700 }}>
                      {t('nameCard.linkedTo', { defaultValue: '已連結' })}：{linkedContact.name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
                      {linkedContact.company_name} · {linkedContact.job_title}
                    </div>
                  </div>
                  <button className="nx-btn nx-btn-secondary" style={{ height: 28, fontSize: 11 }}
                    onClick={() => setLinkedContact(null)}
                    title={t('common.unlink', { defaultValue: '取消連結' })}
                    aria-label={t('common.unlink', { defaultValue: '取消連結' })}>
                    <SvcIcon name="link-2-off" size={12} /> <span className="nc-btn-label">{t('common.unlink', { defaultValue: '取消連結' })}</span>
                  </button>
                </div>
              ) : showLinkSearch ? (
                <EntitySearch
                  searchUrl="/api/v1/crm/contacts?search="
                  value={linkedContactId}
                  placeholder={t('nameCard.searchContact', { defaultValue: '搜尋現有聯絡人…' })}
                  onChange={(cid: string) => {
                    // rebuild a minimal linked-concat object for display + save
                    setLinkedContact({ id: cid, name: '已選聯絡人', company_name: '', job_title: '' })
                    setShowLinkSearch(false)
                  }}
                />
              ) : (
                <button className="nx-btn nx-btn-secondary" style={{ width: '100%' }} onClick={() => setShowLinkSearch(true)}
                  title={t('nameCard.linkContact', { defaultValue: '連結聯絡人' })}
                  aria-label={t('nameCard.linkContact', { defaultValue: '連結聯絡人' })}>
                  <SvcIcon name="search" size={13} /> <span className="nc-btn-label">{t('nameCard.linkContact', { defaultValue: '連結聯絡人' })}</span>
                </button>
              )}
            </div>
          </div>

          {/* ═══ Right: Editable fields + tags + AI confidence ═══ */}
          <div className="nc-detail-fields">
            <div className="nc-detail-field-row">
              <div className="nx-field">
                <label>{t('fields.name', { defaultValue: '姓名' })}</label>
                <input className="input-field" value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div className="nx-field">
                <label>{t('fields.jobTitle', { defaultValue: '職位' })}</label>
                <input className="input-field" value={form.title} onChange={(e) => setForm(f => ({ ...f, title: e.target.value }))} />
              </div>
            </div>
            <div className="nc-detail-field-row">
              <div className="nx-field">
                <label>{t('fields.email', { defaultValue: 'Email' })}</label>
                <input className="input-field" value={form.email} onChange={(e) => setForm(f => ({ ...f, email: e.target.value }))} />
              </div>
              <div className="nx-field">
                <label>{t('fields.phone', { defaultValue: '電話' })}</label>
                <input className="input-field" value={form.phone} onChange={(e) => setForm(f => ({ ...f, phone: e.target.value }))} />
              </div>
            </div>
            <div className="nc-detail-field-row">
              <div className="nx-field" style={{ flex: 1 }}>
                <label>{t('fields.company', { defaultValue: '公司' })}</label>
                <input className="input-field" value={form.company} onChange={(e) => setForm(f => ({ ...f, company: e.target.value }))} />
              </div>
            </div>

            {/* ═══ Tags ═══ */}
            <div style={{ marginTop: 16 }}>
              <label style={{ fontSize: 12, color: 'var(--color-text-secondary)', fontWeight: 600 }}>
                {t('nameCard.tags', { defaultValue: '分類 Tag' })}
              </label>
              <div className="nc-detail-tags-edit">
                {tags.map(tg => (
                  <span className="nc-tag-editable" key={tg}>
                    🏷 {tg} <button type="button" className="nc-tag-remove"
                      aria-label={`${t('common.remove', { defaultValue: '移除' })} ${tg}`}
                      onClick={() => removeTag(tg)}>✕</button>
                  </span>
                ))}
                <input
                  className="nc-tag-add-input"
                  placeholder={t('common.addTag', { defaultValue: '+ 新增' })}
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleAddTag() }}
                  onBlur={handleAddTag}
                />
              </div>
            </div>

            {/* ═══ AI confidence indicator ═══ */}
            {card.field_confidence && (
              <div style={{
                marginTop: 16, padding: 12, borderRadius: 10,
                background: 'rgba(124,92,252,.06)', border: '1px solid rgba(124,92,252,.2)',
                fontSize: 12, color: 'var(--color-text-primary)',
              }}>
                {card.duplicate_candidate?.reason ? ` — ${card.duplicate_candidate.reason}` : ''}
              </div>
            )}

            {/* 2026-09-13 Terrence（v4 MD suggestion T5）：重複卡唔再淨係一句 reason —
                逐個欄位同「現有聯絡人」並排對照，唔同嘅欄位高亮，一眼決定要唔要併入。
                欄位同 backend review_candidates 嘅 shape 一一對應（crm.py:2209）。 */}
            {isPending && candRaw && (() => {
              const FIELDS: { key: 'name' | 'company' | 'title' | 'phone' | 'email'; labelKey: string; zh: string }[] = [
                { key: 'name', labelKey: 'nameCard.fName', zh: '姓名' },
                { key: 'company', labelKey: 'nameCard.fCompany', zh: '公司' },
                { key: 'title', labelKey: 'nameCard.fTitle', zh: '職位' },
                { key: 'phone', labelKey: 'nameCard.fPhone', zh: '電話' },
                { key: 'email', labelKey: 'nameCard.fEmail', zh: 'Email' },
              ]
              const norm = (v: any) => String(v ?? '').trim().toLowerCase().replace(/\s+/g, '')
              return (
                <div className="nc-cmp">
                  <div className="nc-cmp-row nc-cmp-head">
                    <span className="nc-cmp-label" />
                    <span className="nc-cmp-val">{t('nameCard.cmpNewCard', { defaultValue: '呢張新卡' })}</span>
                    <span className="nc-cmp-val">
                      {t('nameCard.cmpExisting', { defaultValue: '現有聯絡人' })}：{candName}
                      {candRaw.confidence ? `（${Math.round(Number(candRaw.confidence) * 100)}%）` : ''}
                    </span>
                  </div>
                  {FIELDS.map(f => {
                    const newV = String((form as any)[f.key] ?? '')
                    const oldV = String((candRaw as any)[f.key] ?? '')
                    const diff = norm(newV) !== norm(oldV)
                    return (
                      <div className={`nc-cmp-row ${diff ? 'is-diff' : ''}`} key={f.key}>
                        <span className="nc-cmp-label">{t(f.labelKey, { defaultValue: f.zh })}</span>
                        <span className="nc-cmp-val">{newV || '—'}</span>
                        <span className="nc-cmp-val">{oldV || '—'}</span>
                      </div>
                    )
                  })}
                  {candRaw.reason && <div className="nc-cmp-reason">🤖 {candRaw.reason}</div>}
                </div>
              )
            })()}

            {/* WORKFLOW-2026-09: Pending area resolve — 併入現有 / 開新（換公司 versioning） */}
            {isPending && (
              <div className="nc-resolve-bar">
                <div className="nc-resolve-title">
                  📥 {t('nameCard.pendingResolveTitle', { defaultValue: 'Pending 卡 — 同現有聯絡人重複，決定：' })}
                </div>
                <div className="nc-resolve-actions">
                  <button type="button" className="nx-btn nx-btn-secondary" style={{ flex: 1 }}
                    onClick={() => handleResolve('merge')} disabled={resolving}>
                    <SvcIcon name="merge" size={13} />
                    {t('nameCard.mergeInto', { defaultValue: '併入' })} {candName}
                  </button>
                  <button type="button" className="nx-btn nx-btn-primary" style={{ flex: 1 }}
                    onClick={() => handleResolve('separate')} disabled={resolving}>
                    <SvcIcon name="user-plus" size={13} />
                    {t('nameCard.separateNew', { defaultValue: '開新聯絡人（舊卡 keep versioning）' })}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="nc-detail-footer">
          <div className="nc-detail-footer-left">
            <button className="nx-btn nc-btn-danger-ghost" onClick={handleDelete}
              title={t('common.delete', { defaultValue: '刪除' })}
              aria-label={t('common.delete', { defaultValue: '刪除' })}>
              <SvcIcon name="trash-2" size={13} /> <span className="nc-btn-label">{t('common.delete', { defaultValue: '刪除' })}</span>
            </button>
            <button className="nx-btn nx-btn-secondary" onClick={handleCopyContact}
              title={t('nameCard.copyContact', { defaultValue: '複製名片' })}
              aria-label={t('nameCard.copyContact', { defaultValue: '複製名片' })}>
              <SvcIcon name="copy" size={13} /> <span className="nc-btn-label">{t('nameCard.copyContact', { defaultValue: '複製名片' })}</span>
            </button>
            <button className="nx-btn nx-btn-secondary" onClick={handleDuplicate}
              title={t('nameCard.duplicateCard', { defaultValue: '建立副本' })}
              aria-label={t('nameCard.duplicateCard', { defaultValue: '建立副本' })}>
              <SvcIcon name="files" size={13} /> <span className="nc-btn-label">{t('nameCard.duplicateCard', { defaultValue: '建立副本' })}</span>
            </button>
          </div>
          <button className="nx-btn nx-btn-primary" onClick={handleSave} disabled={saving}
            title={t('common.saveChanges', { defaultValue: '儲存變更' })}
            aria-label={t('common.saveChanges', { defaultValue: '儲存變更' })}>
            {saving ? t('common.saving') : (<><SvcIcon name="check" size={13} /> <span className="nc-btn-label">{t('common.saveChanges', { defaultValue: '儲存變更' })}</span></>)}
          </button>
        </div>
      </div>
    </div>
  )
}

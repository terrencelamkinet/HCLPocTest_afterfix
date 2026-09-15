import { useState, useRef, useCallback, useMemo, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useDropzone } from 'react-dropzone'
import SvcIcon from '../components/SvcIcon'
import { apiClient } from '../lib/api'
import { NameCardDetailModal } from './NameCardDetailModal'
import type { NameCardRecord, NameCardTag } from './module-types'
import CameraScanSheet from '../components/mobile/CameraScanSheet'

/* ═══════════════════════════════════════════════════════════
   NameCardsPageV2 — Redesigned Name Card Gallery
   Features: tag filter, grid/list view toggle, hover quick-actions,
   bulk select bar, duplicate detection badge, unlinked-contact indicator.

   2026-09-13 Terrence：「Name card 下面四個 add option 放入 click『新增名片』後嘅 popup」
   ⇒ 拍照上載 / 相簿選取 / 貼上圖片 / 批量上載 四個方式收埋入 .nc-sheet bottom sheet；
      桌面拖放區保留（mobile 隱藏），上載進度／錯誤狀態所有寬度照顯示。
   ═══════════════════════════════════════════════════════════ */

export default function NameCardsPageV2() {
  const { t } = useTranslation()
  const [cards, setCards] = useState<NameCardRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<'grid' | 'list'>(() => {
    /* 2026-09-13 Terrence（v4 MD suggestion T3）：記住 Gallery/List 偏好。
       舊版冇持久化 ⇒ 每次入返嚟都跳返格狀，用家要再撳一次。 */
    try { return localStorage.getItem('nc_view') === 'list' ? 'list' : 'grid' } catch { return 'grid' }
  })
  useEffect(() => { try { localStorage.setItem('nc_view', view) } catch { /* ignore */ } }, [view])
  const [search, setSearch] = useState('')
  const [activeTag, setActiveTag] = useState<string>('all')
  // 2026-09-12 Terrence：mobile search 收成 icon，撳 icon 才彈出輸入框
  const [searchOpen, setSearchOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (searchOpen) searchRef.current?.focus() }, [searchOpen])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [detailCard, setDetailCard] = useState<NameCardRecord | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  /* Namecard scan v2（2026-09-07）: CameraScanSheet（live camera + 對位 + crop）— upload mode */
  const [cameraOpen, setCameraOpen] = useState(false)
  /* 2026-09-13：四個上載方式嘅 popup */
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const galleryInputRef = useRef<HTMLInputElement>(null)
  const bulkInputRef = useRef<HTMLInputElement>(null)

  const allTags: NameCardTag[] = useMemo(() => {
    const seen = new Map<string, number>()
    cards.forEach(c => (c.tags || []).forEach(tg => seen.set(tg, (seen.get(tg) || 0) + 1)))
    return Array.from(seen.entries()).map(([label, count]) => ({ label, count }))
  }, [cards])

  const filteredCards = useMemo(() => {
    return cards.filter(c => {
      // WORKFLOW-2026-09: pending（重複）卡淨係喺 pending area 顯示 — 唔好喺主 gallery 重複
      const st = (c as any).status
      if (st === 'review' || st === 'pending') return false
      if (activeTag === 'unlinked' && c.contact_id) return false
      if (activeTag === 'unlinked') return matchesSearch(c, search)
      if (activeTag !== 'all' && !(c.tags || []).includes(activeTag)) return false
      return matchesSearch(c, search)
    })
  }, [cards, activeTag, search])

  function matchesSearch(c: NameCardRecord, q: string) {
    if (!q.trim()) return true
    const hay = `${c.parsed_data?.name || c.name || ''} ${c.parsed_data?.company || c.company || ''} ${c.parsed_data?.title || c.title || ''}`.toLowerCase()
    return hay.includes(q.toLowerCase())
  }

  const fetchCards = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ items: NameCardRecord[] }>('/api/v1/crm/name-cards?limit=200')
      setCards(res.items || [])
    } catch { /* noop */ }
    finally { setLoading(false) }
  }, [])

  useMemo(() => { fetchCards() }, [fetchCards])

  const handleUpload = async (files: FileList | File[]) => {
    setUploading(true)
    setUploadError(null)
    const list = Array.from(files || [])
    let firstErr: any = null
    try {
      // Sequential to keep the shared upload endpoint from being hammered;
      // a single bad file must NOT white-screen the whole batch → per-file try.
      for (const file of list) {
        try {
          const formData = new FormData()
          // 2026-09-13 修（KB-041）：後端 field name 係 `file`，唔係 `image`
          // （舊寫法每次上載都 422 "field required: file"）
          formData.append('file', file)
          await apiClient.postForm('/api/v1/crm/name-cards/upload', formData)
        } catch (e: any) {
          if (!firstErr) firstErr = e
        }
      }
      await fetchCards()
    } catch (e: any) {
      firstErr = e
    } finally {
      setUploading(false)
      if (firstErr) {
        setUploadError(firstErr?.detail || firstErr?.message || t('nameCard.uploadFailed', { defaultValue: '上載失敗' }))
      }
    }
  }

  /* 2026-09-13：「貼上圖片」由純提示變成真係試讀剪貼板；唔得就照樣提示用家手動貼。 */
  const handlePasteFromClipboard = async () => {
    setAddMenuOpen(false)
    const hint = t('nameCard.pasteUnavailable', {
      defaultValue: '剪貼板未有圖片 — 喺頁面直接按 Ctrl+V（電腦）或長按「貼上」（手機）',
    })
    try {
      const items: any[] = await (navigator as any).clipboard.read()
      const files: File[] = []
      for (const it of items || []) {
        for (const type of (it.types || [])) {
          if (String(type).startsWith('image/')) {
            const blob = await it.getType(String(type))
            files.push(new File([blob], `clipboard-${Date.now()}.png`, { type: String(type) }))
          }
        }
      }
      if (files.length) { handleUpload(files); return }
      setUploadError(hint)
    } catch {
      setUploadError(hint)
    }
  }

  // Dropzone target is the visible dropzone box only (not the whole page).
  // NOTE: Do NOT add an extra `onClick` onto the getRootProps spread — react-dropzone
  // injects its own onClick that opens the hidden file input; overriding it is exactly
  // what broke "點擊上載" (the click-to-upload dead bug).
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp', '.heic'] },
    multiple: true,
    onDrop: (files) => { if (files.length) handleUpload(files) },
    noClick: true, // handled explicitly by the visible .nc-dropzone click below
  })

  // Paste-to-upload support
  useMemo(() => {
    const handler = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return
      const imgFiles: File[] = []
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          const f = item.getAsFile()
          if (f) imgFiles.push(f)
        }
      }
      if (imgFiles.length) handleUpload(imgFiles)
    }
    window.addEventListener('paste', handler)
    return () => window.removeEventListener('paste', handler)
  }, [])

  const toggleSelect = (id: string) => {
    setSelected(s => {
      const next = new Set(s)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleBulkDelete = async () => {
    if (!confirm(t('nameCard.confirmBulkDelete', { count: selected.size, defaultValue: '刪除已選 {{count}} 張名片？' }))) return
    await Promise.all(Array.from(selected).map(id => apiClient.delete(`/api/v1/crm/name-cards/${id}`)))
    setSelected(new Set())
    fetchCards()
  }

  const handleDuplicate = async (card: NameCardRecord, e: React.MouseEvent) => {
    e.stopPropagation()
    await apiClient.post(`/api/v1/crm/name-cards/${card.id}/duplicate`, {})
    fetchCards()
  }

  const handleDelete = async (card: NameCardRecord, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(t('nameCard.confirmDelete', { defaultValue: '刪除呢張名片？' }))) return
    await apiClient.delete(`/api/v1/crm/name-cards/${card.id}`)
    fetchCards()
  }

  return (
    <div className="nc-page">
      {/* Hidden file inputs — one per quick-method (camera/gallery/bulk). */}
      <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" hidden
        onChange={(e) => e.target.files && handleUpload(e.target.files)} />
      <input ref={galleryInputRef} type="file" accept="image/*" hidden
        onChange={(e) => e.target.files && handleUpload(e.target.files)} />
      <input ref={bulkInputRef} type="file" accept="image/*" multiple hidden
        onChange={(e) => e.target.files && handleUpload(e.target.files)} />
      <div className="nc-header">
        <div className="nc-header-top">
          <h1 className="nc-title">
            {t('nameCard.title', { defaultValue: '名片管理' })}
            <span className="nc-title-count">{t('nameCard.scannedCount', { count: cards.length, defaultValue: `${cards.length} 張名片` })}</span>
          </h1>
          <div className="nc-header-actions">
            <div className="nc-view-toggle">
              <div className={`nc-view-btn ${view === 'grid' ? 'active' : ''}`} onClick={() => setView('grid')}><SvcIcon name="grid-3x3" size={16} /></div>
              <div className={`nc-view-btn ${view === 'list' ? 'active' : ''}`} onClick={() => setView('list')}><SvcIcon name="list" size={16} /></div>
            </div>
            {/* 2026-09-12 Terrence：mobile 只顯示 icon（文字由 .nc-btn-label 隱藏）
                2026-09-13 Terrence：撳呢個掣彈出四個上載方式（唔再直接開相簿） */}
            <button className="nx-btn nx-btn-primary" onClick={() => setAddMenuOpen(true)} title={t('nameCard.addNew', { defaultValue: '新增名片' }) as string}>
              <SvcIcon name="plus" size={14} /> <span className="nc-btn-label">{t('nameCard.addNew', { defaultValue: '新增名片' })}</span>
            </button>
          </div>
        </div>

        {/* 桌面拖放區（mobile 由 CSS 隱藏；四個方式已收入 popup）。
            注意：drag 只喺呢個 box 捕捉，唔好放去整頁（之前試過 drop 會 white-screen 跳走）。
            noClick: true ⇒ click handler 由呢個 div 自己加，指向相簿選取。 */}
        <div
          {...getRootProps()}
          onClick={() => galleryInputRef.current?.click()}
          className={`nc-dropzone nc-dropzone-slim ${isDragActive ? 'drag-active' : ''}`}
        >
          <input {...getInputProps()} />
          <SvcIcon name="upload-cloud" size={18} />
          <div className="nc-dropzone-title">
            {t('nameCard.dropHint', { defaultValue: '拖放圖片到此處，或點擊上載' })}
          </div>
        </div>

        {/* 上載狀態 — 所有寬度都顯示（mobile 冇 dropzone 都睇到進度／錯誤） */}
        {(uploading || uploadError) && (
          <div className={`nc-upload-status ${uploadError ? 'is-error' : 'is-uploading'}`}>
            {uploadError
              ? <>{uploadError}</>
              : <><span className="nx-spinner" /> {t('nameCard.uploading', { defaultValue: '正在上載並辨識…' })}</>}
          </div>
        )}

        {/* Search + tag filter */}
        <div className={`nc-filter-row ${searchOpen ? 'search-open' : ''}`}>
          <button type="button" className="nc-search-toggle" aria-label={t('common.search', { defaultValue: '搜尋' }) as string} onClick={() => setSearchOpen(o => !o)}>
            <SvcIcon name="search" size={16} />
          </button>
          <div className="nc-search-wrap">
            <SvcIcon name="search" size={14} style={{ position: 'absolute', left: 12, top: 12, color: 'var(--color-text-secondary)' }} />
            <input
              ref={searchRef}
              className="nc-search-input" style={{ paddingLeft: 34 }}
              placeholder={t('nameCard.searchPlaceholder', { defaultValue: '搜尋姓名、公司、職位…' })}
              value={search} onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="nc-tag-filter">
            <span className={`nc-tag-chip ${activeTag === 'all' ? 'active' : ''}`} onClick={() => setActiveTag('all')}>
              {t('nameCard.allTags', { defaultValue: '全部' })}
            </span>
            {allTags.map(tg => (
              <span key={tg.label} className={`nc-tag-chip ${activeTag === tg.label ? 'active' : ''}`} onClick={() => setActiveTag(tg.label)}>
                🏷 {tg.label}
              </span>
            ))}
            <span className={`nc-tag-chip ${activeTag === 'unlinked' ? 'active' : ''}`} onClick={() => setActiveTag('unlinked')}>
              <SvcIcon name="alert-triangle" size={11} /> {t('nameCard.unlinked', { defaultValue: '未連結' })}
            </span>
          </div>
        </div>
      </div>

      <div className="nc-gallery-body">
        {/* WORKFLOW-2026-09: Pending area — duplicated records（2+）等決定 併入/開新 */}
        {(() => {
          const pend = cards.filter((c: any) => c.status === 'review' || c.status === 'pending')
          if (!pend.length) return null
          return (
            <div className="nc-pending-section">
              <div className="nc-pending-head">
                <SvcIcon name="alert-triangle" size={13} />
                {t('nameCard.pendingTitle', { defaultValue: '待處理重複' })}
                <span className="nc-pending-count">{pend.length} 張</span>
                <span className="nc-pending-hint">{t('nameCard.pendingHint', { defaultValue: '同現有聯絡人重複 — 決定併入定開新（可能換咗公司）' })}</span>
              </div>
              <div className="nc-pending-grid">
                {pend.map((card: any) => {
                  const pd = card.parsed_data || {}
                  const cand = (card.review_candidates || [])[0]
                  return (
                    <div className="nc-pending-card" key={card.id} onClick={() => setDetailCard(card)}>
                      {card.cropped_image_url || card.image_url ? (
                        <img className="nc-pending-img" src={card.cropped_image_url || card.image_url} alt={pd.name} />
                      ) : (
                        <div className="nc-pending-noimg"><SvcIcon name="image" size={16} /></div>
                      )}
                      <div className="nc-pending-info">
                        <div className="nc-pending-name">{pd.name || card.name || '未辨識'}</div>
                        {cand && (
                          <div className="nc-pending-cand">
                            {t('nameCard.dupSuggest', { defaultValue: '建議併入' })}：{cand.name}
                            {cand.confidence ? `（${Math.round(Number(cand.confidence) * 100)}%）` : ''}
                          </div>
                        )}
                      </div>
                      <button className="nx-btn nx-btn-primary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}
                        onClick={(e) => { e.stopPropagation(); setDetailCard(card) }}>
                        {t('nameCard.resolve', { defaultValue: '處理' })}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}
        {loading ? (
          <div className="nc-empty">{t('common.loading')}</div>
        ) : filteredCards.length === 0 ? (
          <div className="nc-empty">
            <div className="nc-empty-icon"><SvcIcon name="image" size={28} /></div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('nameCard.emptyTitle', { defaultValue: '暫無名片' })}</div>
            <div style={{ fontSize: 12.5, color: 'var(--color-text-secondary)' }}>{t('nameCard.emptyDesc', { defaultValue: '上載第一張名片，AI 會自動辨識並建立聯絡人' })}</div>
          </div>
        ) : (
          <div className={`nc-gallery-grid ${view === 'list' ? 'list-view' : ''}`}>
            {filteredCards.map(card => {
              const pd = card.parsed_data || {}
              const isDup = !!card.duplicate_candidate
              return (
                <div className="nc-card" key={card.id} onClick={() => setDetailCard(card)}>
                  <input
                    type="checkbox" className="nc-card-checkbox"
                    checked={selected.has(card.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleSelect(card.id)}
                  />
                  <div className="nc-card-img-wrap">
                    {card.cropped_image_url || card.image_url ? (
                      <img className="nc-card-img" src={card.cropped_image_url || card.image_url} alt={pd.name || card.name} />
                    ) : (
                      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)', fontSize: 11 }}>
                        {t('nameCard.noImage', { defaultValue: '名片圖片' })}
                      </div>
                    )}
                    {isDup && <div className="nc-card-dup-badge"><SvcIcon name="alert-triangle" size={10} /> {t('nameCard.possibleDup', { defaultValue: '疑似重複' })}</div>}
                    <div className="nc-card-quick-actions">
                      <div className="nc-card-quick-btn" onClick={(e) => { e.stopPropagation(); setDetailCard(card) }}><SvcIcon name="pencil" size={13} /></div>
                      <div className="nc-card-quick-btn" onClick={(e) => handleDuplicate(card, e)}><SvcIcon name="copy" size={13} /></div>
                      <div className="nc-card-quick-btn" onClick={(e) => handleDelete(card, e)}><SvcIcon name="trash-2" size={13} /></div>
                    </div>
                  </div>
                  <div className="nc-card-body">
                    <div className="nc-card-name">{pd.name || card.name || t('nameCard.unrecognized', { defaultValue: '未辨識' })}</div>
                    <div className="nc-card-meta">{[pd.company || card.company, pd.title || card.title].filter(Boolean).join(' · ') || '—'}</div>
                    {(card.tags || []).length > 0 && (
                      <div className="nc-card-tags">{card.tags!.map(tg => <span className="nc-card-tag" key={tg}>{tg}</span>)}</div>
                    )}
                    {card.contact_id
                      ? <div className="nc-card-linked"><SvcIcon name="check" size={11} /> {t('nameCard.linked', { defaultValue: '已連結聯絡人' })}</div>
                      : <div className="nc-card-unlinked">○ {t('nameCard.notLinked', { defaultValue: '未連結' })}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {selected.size > 0 && (
        <div className="nc-bulk-bar">
          <span className="nc-bulk-count">{t('nameCard.selectedCount', { count: selected.size, defaultValue: `已選 ${selected.size} 張` })}</span>
          <button className="nx-btn nx-btn-secondary" style={{}}>{t('nameCard.addTagBulk', { defaultValue: '加 Tag' })}</button>
          <button className="nx-btn nc-btn-danger-ghost" style={{ marginLeft: 'auto' }} onClick={handleBulkDelete}>
            <SvcIcon name="trash-2" size={13} /> {t('common.delete', { defaultValue: '刪除' })}
          </button>
        </div>
      )}

      {detailCard && (
        <NameCardDetailModal
          card={detailCard}
          onClose={() => setDetailCard(null)}
          onSaved={() => { setDetailCard(null); fetchCards() }}
          onDeleted={() => { setDetailCard(null); fetchCards() }}
        />
      )}

      {/* Namecard scan v2: CameraScanSheet — live camera + 自動對位 + 微調 crop → upload（upload mode） */}
      <CameraScanSheet
        open={cameraOpen}
        mode="upload"
        onClose={() => setCameraOpen(false)}
        onSaved={() => { setCameraOpen(false); fetchCards() }}
      />

      {/* 2026-09-13 Terrence：四個上載方式 popup（撳「新增名片」彈出） */}
      {addMenuOpen && (
        <div className="nc-sheet-scrim" onClick={() => setAddMenuOpen(false)}>
          <div className="nc-sheet" role="dialog" aria-modal="true" aria-label={t('nameCard.addNew', { defaultValue: '新增名片' }) as string}
            onClick={(e) => e.stopPropagation()}>
            <div className="nc-sheet-title">{t('nameCard.addNew', { defaultValue: '新增名片' })}</div>
            <button type="button" className="nc-sheet-item"
              onClick={() => { setAddMenuOpen(false); setCameraOpen(true) }}>
              <SvcIcon name="camera" size={16} /> {t('nameCard.takePhoto', { defaultValue: '拍照上載' })}
            </button>
            <button type="button" className="nc-sheet-item"
              onClick={() => { setAddMenuOpen(false); galleryInputRef.current?.click() }}>
              <SvcIcon name="image" size={16} /> {t('nameCard.pickGallery', { defaultValue: '相簿選取' })}
            </button>
            <button type="button" className="nc-sheet-item" onClick={handlePasteFromClipboard}>
              <SvcIcon name="clipboard" size={16} /> {t('nameCard.pasteImage', { defaultValue: '貼上圖片 (Ctrl+V)' })}
            </button>
            <button type="button" className="nc-sheet-item"
              onClick={() => { setAddMenuOpen(false); bulkInputRef.current?.click() }}>
              <SvcIcon name="upload-cloud" size={16} /> {t('nameCard.bulkUpload', { defaultValue: '批量上載' })}
            </button>
            <button type="button" className="nc-sheet-cancel" onClick={() => setAddMenuOpen(false)}>
              {t('common.cancel', { defaultValue: '取消' })}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

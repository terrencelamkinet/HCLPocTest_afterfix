import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../components/SvcIcon'
import { apiClient } from '../lib/api'
import type { NameCardTagDef } from './module-types'

/* ═══════════════════════════════════════════════════════════
   TagManagementPage — 名片 Tag 分類管理中心
   Features: create/edit/delete/merge tags, color coding,
   usage count, AI-suggested tag cleanup (near-duplicate merge),
   drag-to-reorder, search/filter.
   ═══════════════════════════════════════════════════════════ */

const TAG_COLORS = [
  { key: 'violet', hex: '#7c5cfc' }, { key: 'blue', hex: '#2563eb' },
  { key: 'green', hex: '#22c55e' }, { key: 'amber', hex: '#f59e0b' },
  { key: 'rose', hex: '#ef4444' }, { key: 'cyan', hex: '#06b6d4' },
  { key: 'pink', hex: '#ec4899' }, { key: 'slate', hex: '#64748b' },
]

export default function TagManagementPage() {
  const { t } = useTranslation()
  const [tags, setTags] = useState<NameCardTagDef[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [newTagOpen, setNewTagOpen] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [newTagColor, setNewTagColor] = useState(TAG_COLORS[0].hex)
  const [mergeMode, setMergeMode] = useState(false)
  const [mergeSelection, setMergeSelection] = useState<Set<string>>(new Set())
  const [aiSuggestions, setAiSuggestions] = useState<{ groupLabel: string; tagIds: string[]; reason: string }[]>([])
  const [aiScanLoading, setAiScanLoading] = useState(false)

  const fetchTags = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get<{ items: NameCardTagDef[] }>('/api/v1/crm/namecard-tags?with_counts=true')
      setTags(res.items || [])
    } finally { setLoading(false) }
  }
  useMemo(() => { fetchTags() }, [])

  const filtered = useMemo(
    () => tags.filter(tg => tg.label.toLowerCase().includes(search.toLowerCase())),
    [tags, search]
  )

  const handleCreate = async () => {
    if (!newTagName.trim()) return
    await apiClient.post('/api/v1/crm/namecard-tags', { label: newTagName.trim(), color: newTagColor })
    setNewTagName(''); setNewTagOpen(false)
    fetchTags()
  }

  const handleRename = async (id: string, label: string) => {
    await apiClient.patch(`/api/v1/crm/namecard-tags/${id}`, { label })
    setEditingId(null)
    fetchTags()
  }

  const handleColorChange = async (id: string, color: string) => {
    await apiClient.patch(`/api/v1/crm/namecard-tags/${id}`, { color })
    fetchTags()
  }

  const handleDelete = async (tg: NameCardTagDef) => {
    if (!confirm(t('tags.confirmDelete', { defaultValue: `刪除「${tg.label}」？呢個 Tag 會從 ${tg.usage_count || 0} 張名片中移除。` }))) return
    await apiClient.delete(`/api/v1/crm/namecard-tags/${tg.id}`)
    fetchTags()
  }

  /* ═══ AI-powered near-duplicate tag detection (2026 UX pattern) ═══ */
  const runAiCleanupScan = async () => {
    setAiScanLoading(true)
    try {
      const res = await apiClient.post<{ groups: any[] }>('/api/v1/crm/namecard-tags/ai-cleanup-scan', {})
      setAiSuggestions(res.groups || [])
    } finally { setAiScanLoading(false) }
  }

  const acceptMergeSuggestion = async (group: { tagIds: string[]; groupLabel: string }) => {
    await apiClient.post('/api/v1/crm/namecard-tags/merge', { tag_ids: group.tagIds, into_label: group.groupLabel })
    setAiSuggestions(s => s.filter(g => g !== group))
    fetchTags()
  }

  const toggleMergeSelect = (id: string) => {
    setMergeSelection(s => {
      const next = new Set(s)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleManualMerge = async () => {
    if (mergeSelection.size < 2) return
    const survivor = tags.find(t => mergeSelection.has(t.id))
    await apiClient.post('/api/v1/crm/namecard-tags/merge', {
      tag_ids: Array.from(mergeSelection), into_label: survivor?.label,
    })
    setMergeSelection(new Set()); setMergeMode(false)
    fetchTags()
  }

  return (
    <div className="tg-page">
      <div className="tg-header">
        <div>
          <h1 className="nc-title">{t('tags.title', { defaultValue: '名片分類 Tag 管理' })}</h1>
          <p className="tg-subtitle">{t('tags.subtitle', { defaultValue: `共 ${tags.length} 個分類 · 用嚟整理同篩選你嘅名片庫` })}</p>
        </div>
        <div className="tg-header-actions">
          {mergeMode ? (
            <>
              <button className="nx-btn nx-btn-secondary" onClick={() => { setMergeMode(false); setMergeSelection(new Set()) }}
                title={t('common.cancel', { defaultValue: '取消' })}>
                <SvcIcon name="x" size={14} /> <span className="nc-btn-label">{t('common.cancel', { defaultValue: '取消' })}</span>
              </button>
              <button className="nx-btn nx-btn-primary" disabled={mergeSelection.size < 2} onClick={handleManualMerge}
                title={t('tags.mergeSelected', { defaultValue: '合併已選' })}>
                <SvcIcon name="merge" size={14} /> <span className="nc-btn-label">{t('tags.mergeSelected', { defaultValue: '合併已選' })}</span>
                <span className="nc-btn-label"> ({mergeSelection.size})</span>
              </button>
            </>
          ) : (
            <>
              <button className="nx-btn nx-btn-secondary" onClick={() => setMergeMode(true)}
                title={t('tags.mergeMode', { defaultValue: '合併模式' })}>
                <SvcIcon name="merge" size={14} /> <span className="nc-btn-label">{t('tags.mergeMode', { defaultValue: '合併模式' })}</span>
              </button>
              <button className="nx-btn nx-btn-primary" onClick={() => setNewTagOpen(true)}
                title={t('tags.newTag', { defaultValue: '新增 Tag' })}>
                <SvcIcon name="plus" size={14} /> <span className="nc-btn-label">{t('tags.newTag', { defaultValue: '新增 Tag' })}</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* ═══ AI Cleanup Card — 2026-era proactive suggestion pattern ═══ */}
      <div className="tg-ai-card">
        <div className="tg-ai-card-header">
          <div className="tg-ai-icon"><SvcIcon name="sparkles" size={16} /></div>
          <div style={{ flex: 1 }}>
            <div className="tg-ai-title">{t('tags.aiCleanupTitle', { defaultValue: 'AI Tag 整理建議' })}</div>
            <div className="tg-ai-sub">{t('tags.aiCleanupSub', { defaultValue: '偵測相似或重複嘅 Tag（例如「物流」同「物流業」），建議合併' })}</div>
          </div>
          <button className="nx-btn nx-btn-secondary" onClick={runAiCleanupScan} disabled={aiScanLoading}
            title={t('tags.scanNow', { defaultValue: '立即掃描' })}>
            <SvcIcon name="sparkles" size={14} /> <span className="nc-btn-label">{aiScanLoading ? t('tags.scanning', { defaultValue: '掃描中…' }) : t('tags.scanNow', { defaultValue: '立即掃描' })}</span>
          </button>
        </div>
        {aiSuggestions.length > 0 && (
          <div className="tg-ai-suggestions">
            {aiSuggestions.map((g, i) => (
              <div className="tg-ai-suggestion-row" key={i}>
                <div className="tg-ai-suggestion-tags">
                  {g.tagIds.map(id => {
                    const tg = tags.find(x => x.id === id)
                    return tg ? <span className="nc-card-tag" key={id}>{tg.label}</span> : null
                  })}
                  <span className="tg-ai-arrow">→</span>
                  <span className="nc-tag-editable">{g.groupLabel}</span>
                </div>
                <div className="tg-ai-suggestion-reason">{g.reason}</div>
                <button className="nx-btn nx-btn-primary" style={{ fontSize: 12 }} onClick={() => acceptMergeSuggestion(g)}
                  title={t('tags.acceptMerge', { defaultValue: '採用' })}>
                  <SvcIcon name="check" size={12} /> <span className="nc-btn-label">{t('tags.acceptMerge', { defaultValue: '採用' })}</span>
                </button>
                <button className="nx-btn nx-btn-secondary" style={{ fontSize: 12 }}
                  onClick={() => setAiSuggestions(s => s.filter(x => x !== g))}>
                  {t('common.dismiss', { defaultValue: '忽略' })}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ═══ Search ═══ */}
      <div style={{ position: 'relative', marginBottom: 16 }}>
        <SvcIcon name="search" size={14} style={{ position: 'absolute', left: 12, top: 12, color: 'var(--color-text-secondary)' }} />
        <input
          className="nc-search-input" style={{ width: '100%', paddingLeft: 34 }}
          placeholder={t('tags.searchPlaceholder', { defaultValue: '搜尋 Tag 名稱…' })}
          value={search} onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* ═══ New tag inline form ═══ */}
      {newTagOpen && (
        <div className="tg-new-form">
          <input
            className="input-field" autoFocus placeholder={t('tags.tagNamePlaceholder', { defaultValue: '輸入新 Tag 名稱' })}
            value={newTagName} onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
          />
          <div className="tg-color-picker">
            {TAG_COLORS.map(c => (
              <div key={c.key} className={`tg-color-dot ${newTagColor === c.hex ? 'active' : ''}`}
                style={{ background: c.hex }} onClick={() => setNewTagColor(c.hex)} />
            ))}
          </div>
          <button className="nx-btn nx-btn-primary" onClick={handleCreate}>{t('common.create', { defaultValue: '建立' })}</button>
          <button className="nx-btn nx-btn-secondary" onClick={() => setNewTagOpen(false)}><SvcIcon name="x" size={14} /></button>
        </div>
      )}

      {/* ═══ Tag list/grid ═══ */}
      {loading ? (
        <div className="nc-empty">{t('common.loading')}</div>
      ) : filtered.length === 0 ? (
        <div className="nc-empty">
          <div className="nc-empty-icon"><SvcIcon name="tags" size={26} /></div>
          <div style={{ fontWeight: 600 }}>{t('tags.emptyTitle', { defaultValue: '暫無分類 Tag' })}</div>
        </div>
      ) : (
        <div className="tg-grid">
          {filtered.map(tg => (
            <div className={`tg-card ${mergeMode ? 'merge-mode' : ''} ${mergeSelection.has(tg.id) ? 'selected' : ''}`}
              key={tg.id} onClick={() => mergeMode && toggleMergeSelect(tg.id)}>
              {mergeMode && <input type="checkbox" className="nc-card-checkbox" style={{ position: 'static' }} checked={mergeSelection.has(tg.id)} readOnly />}
              <div className="tg-card-dot" style={{ background: tg.color || '#7c5cfc' }} />
              <div className="tg-card-body">
                {editingId === tg.id ? (
                  <input
                    className="input-field" autoFocus defaultValue={tg.label}
                    onBlur={(e) => handleRename(tg.id, e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleRename(tg.id, (e.target as HTMLInputElement).value) }}
                  />
                ) : (
                  <div className="tg-card-label">{tg.label}</div>
                )}
                <div className="tg-card-count">{t('tags.usageCount', { count: tg.usage_count || 0, defaultValue: `${tg.usage_count || 0} 張名片` })}</div>
              </div>
              {!mergeMode && (
                <div className="tg-card-actions">
                  <div className="tg-color-picker inline">
                    {TAG_COLORS.map(c => (
                      <div key={c.key} className={`tg-color-dot small ${tg.color === c.hex ? 'active' : ''}`}
                        style={{ background: c.hex }} onClick={(e) => { e.stopPropagation(); handleColorChange(tg.id, c.hex) }} />
                    ))}
                  </div>
                  <div className="nc-card-quick-btn" onClick={(e) => { e.stopPropagation(); setEditingId(tg.id) }}><SvcIcon name="pencil" size={13} /></div>
                  <div className="nc-card-quick-btn" onClick={(e) => { e.stopPropagation(); handleDelete(tg) }}><SvcIcon name="trash-2" size={13} /></div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

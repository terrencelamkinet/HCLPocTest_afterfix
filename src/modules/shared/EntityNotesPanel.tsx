import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { apiClient } from '../../lib/api'
import { sanitizeHtml } from '../../lib/sanitizeHtml'
import NexusEditor from '../../components/editor/NexusEditor'
import { extractRecordMentions } from '../../components/editor/RecordMention'

/* 共用 Notes 面板 — link 到任意 entity（project / task / contact / company）
   用法: <EntityNotesPanel entityType="project" entityId={id} />
   Notes V2 (T2.1): 重用 nexus_crm.tags + note_tags junction — tag 可搜尋/即場建立/刪除，
   列表可按 tag 篩選，meta row 顯示有顏色嘅 chip（同名 tag 重用唔重複）。 */

interface NoteTagRef {
  id: string
  name: string
  color?: string | null
}

interface NoteLinkRef {
  id: string
  entity_type: string
  entity_id?: string | null
  label?: string | null
  url?: string | null
}

interface NoteItem {
  id: string
  title: string | null
  content: string | null
  pinned: boolean
  created_at: string
  contact_id?: string | null
  company_id?: string | null
  note_tags?: NoteTagRef[]
  note_links?: NoteLinkRef[]
  /** 由 mention 關係（note_links）帶出嘅筆記 —— 提及此 record 但唔係掛住 */
  mentioned?: boolean
}

interface Props {
  entityType: 'project' | 'task' | 'contact' | 'company'
  entityId: string
  filterKey: 'project_id' | 'task_id' | 'contact_id' | 'company_id'
  compact?: boolean
}

const TAG_COLORS = ['#2870b8', '#387a3a', '#c23b4a', '#b9760f', '#7350ad', '#0f6f6f', '#6f6d68']

function chipStyle(color?: string | null) {
  const c = color || '#6f6d68'
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '1px 8px', borderRadius: 999,
    fontSize: 11, lineHeight: '18px', fontWeight: 600,
    color: '#fff', background: c, whiteSpace: 'nowrap' as const,
  }
}

function timeAgo(iso: string): string {
  const d = new Date(iso)
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 60) return '剛剛'
  if (s < 3600) return `${Math.floor(s / 60)} 分鐘前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小時前`
  return d.toLocaleDateString()
}

export default function EntityNotesPanel({ entityType, entityId, filterKey, compact }: Props) {
  const { t } = useTranslation()
  const [notes, setNotes] = useState<NoteItem[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')

  /* ── Notes V2 (T2.1) tags ── */
  const [allTags, setAllTags] = useState<NoteTagRef[]>([])
  const [draftTags, setDraftTags] = useState<NoteTagRef[]>([])
  const [tagQuery, setTagQuery] = useState('')
  const [tagPickerOpen, setTagPickerOpen] = useState(false)
  const [filterTagId, setFilterTagId] = useState<string>('')
  const [draftColor, setDraftColor] = useState<string>(TAG_COLORS[0])

  /* ── Notes v2 (T3.1) record links ── */
  const [draftLinks, setDraftLinks] = useState<{ entity_type: string; entity_id: string; label: string }[]>([])
  const [linkQuery, setLinkQuery] = useState('')
  const [linkResults, setLinkResults] = useState<{ id: string; type: string; label: string }[]>([])
  const [linkPickerOpen, setLinkPickerOpen] = useState(false)

  /* ── Notes v2 (T3.3) 規則比對建議連結（唔用 LLM）── */
  const [linkSuggestions, setLinkSuggestions] = useState<Record<string, { entity_type: string; entity_id: string; label: string }[]>>({})

  const loadSuggestions = useCallback(async (items: NoteItem[]) => {
    const ids = items.filter(n => (n.content || '').trim().length > 3).slice(0, 20).map(n => n.id)
    if (!ids.length) { setLinkSuggestions({}); return }
    try {
      const res = await apiClient.post<Record<string, { entity_type: string; entity_id: string; label: string }[]>>(
        '/api/v1/crm/notes/link-suggestions', { note_ids: ids }
      )
      setLinkSuggestions(res || {})
    } catch { setLinkSuggestions({}) }
  }, [])

  const acceptSuggestion = async (noteId: string, s: { entity_type: string; entity_id: string; label: string }) => {
    try {
      await apiClient.post(`/api/v1/crm/notes/${noteId}/links`, s)
      setLinkSuggestions(prev => {
        const next = { ...prev }
        next[noteId] = (next[noteId] || []).filter(x => !(x.entity_type === s.entity_type && x.entity_id === s.entity_id))
        if (!next[noteId].length) delete next[noteId]
        return next
      })
      load()
    } catch (e: any) { alert(e.detail || e.message) }
  }

  const dismissSuggestion = async (noteId: string, s: { entity_type: string; entity_id: string; label: string }) => {
    try {
      await apiClient.post(`/api/v1/crm/notes/${noteId}/dismiss-link`, { entity_type: s.entity_type, entity_id: s.entity_id })
      setLinkSuggestions(prev => {
        const next = { ...prev }
        next[noteId] = (next[noteId] || []).filter(x => !(x.entity_type === s.entity_type && x.entity_id === s.entity_id))
        if (!next[noteId].length) delete next[noteId]
        return next
      })
    } catch (e: any) { alert(e.detail || e.message) }
  }

  useEffect(() => {
    const q = linkQuery.trim()
    if (!q) { setLinkResults([]); return }
    let alive = true
    const tm = setTimeout(async () => {
      try {
        const res: any = await apiClient.get('/api/v1/crm/search', { params: { q, limit: '6', types: 'contact,company,project,task,touchpoint' } })
        /* ⚠️ 2026-09-13 修（同 RecordMention.ts 同一個 bug）：backend 回 {results:[…]}，
           原本只讀 res.items → entity notes 面板嘅「連結 record」搜尋永遠冇結果。 */
        const rows: any[] = Array.isArray(res) ? res : (res?.results || res?.items || [])
        if (alive) setLinkResults(rows.slice(0, 6).map(r => ({ id: String(r.id), type: String(r.type), label: String(r.label || '') })))
      } catch { if (alive) setLinkResults([]) }
    }, 250)
    return () => { alive = false; clearTimeout(tm) }
  }, [linkQuery])

  const loadTags = useCallback(async () => {
    try {
      const res = await apiClient.get<{ items: NoteTagRef[] }>('/api/v1/crm/tags?limit=200')
      setAllTags(res.items || [])
    } catch { setAllTags([]) }
  }, [])

  const load = useCallback(async () => {
    try {
      const tagParam = filterTagId ? `&tag_id=${filterTagId}` : ''
      /* spec §8.3 反向查詢：除咗「掛住呢個 record」嘅筆記，仲要列出**提及過**嘅
         （note_links durable relation，內容由 server canonical 抽出，唔靠文字相似）。
         backend 已有 mention_of_type / mention_of_id filter → 純前端合併 + 去重。 */
      const entType = filterKey.endsWith('_id') ? filterKey.slice(0, -3) : null
      const [res, mentioned] = await Promise.all([
        apiClient.get<{ items: NoteItem[] }>(
          `/api/v1/crm/notes?limit=50&${filterKey}=${entityId}${tagParam}`
        ),
        entType
          ? apiClient
              .get<{ items: NoteItem[] }>(
                `/api/v1/crm/notes?limit=50&mention_of_type=${entType}&mention_of_id=${entityId}${tagParam}`
              )
              .catch(() => ({ items: [] as NoteItem[] }))
          : Promise.resolve({ items: [] as NoteItem[] }),
      ])
      const attached = res.items || []
      const seen = new Set(attached.map(n => n.id))
      // 提及但未掛住 → 標記 mentioned，UI 用 chip 分辨（唔會靜靜雞多咗嘢）
      const extra = (mentioned.items || [])
        .filter(n => !seen.has(n.id))
        .map(n => ({ ...n, mentioned: true }))
      const items = [...attached, ...extra]
      setNotes(items)
      void loadSuggestions(items)
    } catch { setNotes([]) }
    finally { setLoading(false) }
  }, [entityId, filterKey, filterTagId])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadTags() }, [loadTags])

  const suggestions = useMemo(() => {
    const q = tagQuery.trim().toLowerCase()
    const chosen = new Set(draftTags.map(x => x.id || `name:${x.name.toLowerCase()}`))
    return allTags
      .filter(tg => !chosen.has(tg.id) && (!q || tg.name.toLowerCase().includes(q)))
      .slice(0, 8)
  }, [allTags, tagQuery, draftTags])

  const exactExists = useMemo(
    () => allTags.some(tg => tg.name.toLowerCase() === tagQuery.trim().toLowerCase()),
    [allTags, tagQuery]
  )

  const addDraftTag = (tag: NoteTagRef) => {
    setDraftTags(prev => prev.some(x => (tag.id && x.id === tag.id) || x.name.toLowerCase() === tag.name.toLowerCase())
      ? prev : [...prev, tag])
    setTagQuery('')
    setTagPickerOpen(false)
  }

  const createDraftTag = () => {
    const name = tagQuery.trim()
    if (!name) return
    addDraftTag({ id: '', name, color: draftColor })
  }

  const addNote = async () => {
    if (!title.trim()) return
    setSaving(true)
    try {
      const created = await apiClient.post<{ id: string }>('/api/v1/crm/notes', {
        title: title.trim(),
        content: content || null,
        [filterKey]: entityId,
      })
      // Attach tags (backend reuses same-name tags → no duplicates)
      for (const tg of draftTags) {
        try {
          await apiClient.post(`/api/v1/crm/notes/${created.id}/tags`, tg.id
            ? { tag_id: tg.id }
            : { name: tg.name, color: tg.color || draftColor })
        } catch { /* tag attach best-effort — note is already saved */ }
      }
      // T3.1 — record links: @mention chips in content + manual +Link record
      const merged = [...extractRecordMentions(content), ...draftLinks]
      const seen = new Set<string>()
      for (const lk of merged) {
        const k = `${lk.entity_type}:${lk.entity_id}`
        if (seen.has(k)) continue
        seen.add(k)
        try { await apiClient.post(`/api/v1/crm/notes/${created.id}/links`, lk) } catch { /* best-effort */ }
      }
      setTitle(''); setContent(''); setOpen(false)
      setDraftTags([]); setTagQuery('')
      setDraftLinks([]); setLinkQuery(''); setLinkResults([])
      load(); loadTags()
    } catch (e: any) { alert(e.detail || e.message) }
    finally { setSaving(false) }
  }

  const removeNote = async (id: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/notes/${id}`)
      setNotes(prev => prev.filter(n => n.id !== id))
    } catch (e: any) { alert(e.detail || e.message) }
  }

  const removeLinkFromNote = async (noteId: string, linkId: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/notes/${noteId}/links/${linkId}`)
      setNotes(prev => prev.map(n => n.id === noteId
        ? { ...n, note_links: (n.note_links || []).filter(l => l.id !== linkId) }
        : n))
    } catch (e: any) { alert(e.detail || e.message) }
  }

  const removeTagFromNote = async (noteId: string, tagId: string) => {
    try {
      await apiClient.delete(`/api/v1/crm/notes/${noteId}/tags/${tagId}`)
      setNotes(prev => prev.map(n => n.id === noteId
        ? { ...n, note_tags: (n.note_tags || []).filter(tg => tg.id !== tagId) }
        : n))
    } catch (e: any) { alert(e.detail || e.message) }
  }

  return (
    <div className={`nx-notes-panel${compact ? ' compact' : ''}`}>
      <div className="nx-notes-head">
        <span className="f-label">{t('pages.contacts.detail.notes', { defaultValue: 'Notes' })}</span>
        <button className="btn-ghost" onClick={() => setOpen(true)}>+ {t('pages.contacts.detail.addNote', { defaultValue: 'Add Note' })}</button>
      </div>

      {/* Tag filter — 列表按 tag 篩選 */}
      {allTags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0 10px' }}>
          <button
            className={filterTagId === '' ? 'btn-primary' : 'btn-secondary'}
            style={{ padding: '2px 10px', fontSize: 11, borderRadius: 999 }}
            onClick={() => setFilterTagId('')}
          >{t('common.all', { defaultValue: '全部' })}</button>
          {allTags.map(tg => (
            <button
              key={tg.id}
              style={{ ...chipStyle(filterTagId === tg.id ? tg.color : null), opacity: filterTagId && filterTagId !== tg.id ? 0.55 : 1, border: 'none', cursor: 'pointer' }}
              onClick={() => setFilterTagId(prev => prev === tg.id ? '' : tg.id)}
            >{tg.name}</button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="nx-empty-state">{t('common.loading', { defaultValue: 'Loading…' })}</div>
      ) : notes.length === 0 ? (
        <div className="nx-empty-state">{t('pages.contacts.detail.noNotes', { defaultValue: 'No notes yet' })}</div>
      ) : (
        <div className="flex-col" style={{ gap: 8 }}>
          {notes.map(n => (
            <div key={n.id} className="nx-note-card">
              <div className="nx-note-title-row">
                <span className="list-title">{n.title}</span>
                {n.mentioned && (
                  <span style={{ ...chipStyle('#6f6d68'), marginLeft: 6 }}>
                    {t('notes.mentionedBadge', { defaultValue: 'Mentioned' })}
                  </span>
                )}
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {n.pinned && <span className="badge badge-p1">📌</span>}
                  <button className="icon-btn-small" title={t('common.delete')} onClick={() => removeNote(n.id)} style={{ color: 'var(--color-notification)' }}>✕</button>
                </div>
              </div>
              {n.content && (
                /* 2026-09-15 SAST：dangerouslySetInnerHTML 前一律過 sanitizeHtml（nh3 對應前端層）*/
                <div className="nxe-rendered-content" dangerouslySetInnerHTML={{ __html: sanitizeHtml(n.content) }} />
              )}
              {/* T3.3 — 規則比對建議連結 banner（一鍵連結 / 略過） */}
              {(linkSuggestions[n.id] || []).length > 0 && (
                <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--text-tertiary, #999)' }}>💡 可能相關：</span>
                  {(linkSuggestions[n.id] || []).map(s => (
                    <span key={s.entity_type + s.entity_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
                      <span style={{ fontWeight: 600 }}>{s.label}</span>
                      <button className="btn-primary" style={{ padding: '1px 9px', fontSize: 11, borderRadius: 999 }}
                        onClick={() => acceptSuggestion(n.id, s)}>連結</button>
                      <button className="btn-secondary" style={{ padding: '1px 9px', fontSize: 11, borderRadius: 999 }}
                        onClick={() => dismissSuggestion(n.id, s)}>略過</button>
                    </span>
                  ))}
                </div>
              )}
              <div className="nx-note-meta">
                <span>{timeAgo(n.created_at)}</span>
                {/* meta row 顯示 tag chip（有顏色、可刪） */}
                {(n.note_tags || []).map(tg => (
                  <span key={tg.id} style={{ ...chipStyle(tg.color), marginLeft: 6 }}>
                    {tg.name}
                    <button
                      title={t('common.delete')}
                      style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', padding: 0, fontSize: 11, lineHeight: 1 }}
                      onClick={() => removeTagFromNote(n.id, tg.id)}
                    >✕</button>
                  </span>
                ))}
                {/* T3.1 — 連結 record chip（可 click 去 record / 可刪） */}
                {(n.note_links || []).map(lk => (
                  <span key={lk.id} style={{ ...chipStyle('#2870b8'), marginLeft: 6 }}>
                    {lk.url
                      ? <Link to={lk.url} style={{ color: '#fff', textDecoration: 'none' }}>🔗 {lk.label || lk.entity_type}</Link>
                      : <span>🔗 {lk.label || lk.entity_type}</span>}
                    <button
                      title={t('common.delete')}
                      style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', padding: 0, fontSize: 11, lineHeight: 1 }}
                      onClick={() => removeLinkFromNote(n.id, lk.id)}
                    >✕</button>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {open && (
        <div className="share-overlay" onClick={() => setOpen(false)}>
          <div className="share-dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 640 }}>
            <h3>{t('pages.contacts.detail.addNote', { defaultValue: 'Add Note' })}</h3>
            <div className="dt-field" style={{ marginTop: 10 }}>
              <span className="f-label">{t('pages.contacts.detail.titleRequired', { defaultValue: 'Title' })}</span>
              <input type="text" className="input-field" value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder={t('pages.contacts.detail.noteTitlePlaceholder', { defaultValue: 'Note title…' })} />
            </div>
            <div className="dt-field" style={{ marginTop: 8 }}>
              <span className="f-label">{t('common.content', { defaultValue: 'Content' })}</span>
              <NexusEditor
                content={content}
                onChange={html => setContent(html)}
                minHeight={160}
                entityContext={{ type: entityType, id: entityId }}
              />
            </div>

            {/* Tag editor — 可搜尋 / 即場建立 / 可刪 */}
            <div className="dt-field" style={{ marginTop: 8 }}>
              <span className="f-label">{t('common.tags', { defaultValue: 'Tags' })}</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 6 }}>
                {draftTags.map(tg => (
                  <span key={tg.id || tg.name} style={chipStyle(tg.color)}>
                    {tg.name}
                    <button
                      title={t('common.delete')}
                      style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', padding: 0, fontSize: 11, lineHeight: 1 }}
                      onClick={() => setDraftTags(prev => prev.filter(x => !(x.id === tg.id && x.name === tg.name)))}
                    >✕</button>
                  </span>
                ))}
              </div>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  className="input-field"
                  value={tagQuery}
                  placeholder={t('pages.notes.tagPlaceholder', { defaultValue: '搜尋或輸入新 tag…' })}
                  onChange={e => { setTagQuery(e.target.value); setTagPickerOpen(true) }}
                  onFocus={() => setTagPickerOpen(true)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      const first = suggestions[0]
                      if (first && tagQuery.trim() && first.name.toLowerCase().includes(tagQuery.trim().toLowerCase())) addDraftTag(first)
                      else createDraftTag()
                    }
                  }}
                />
                {tagPickerOpen && (tagQuery.trim() || suggestions.length > 0) && (
                  <div style={{
                    position: 'absolute', zIndex: 20, left: 0, right: 0, top: '100%',
                    background: 'var(--color-surface, #fff)', border: '1px solid var(--color-border, #ddd)',
                    borderRadius: 8, boxShadow: '0 6px 18px rgba(0,0,0,.12)', maxHeight: 220, overflowY: 'auto', marginTop: 2,
                  }}>
                    {suggestions.map(tg => (
                      <div key={tg.id} style={{ padding: '7px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}
                        onMouseDown={e => { e.preventDefault(); addDraftTag(tg) }}>
                        <span style={chipStyle(tg.color)}>{tg.name}</span>
                        <span style={{ color: 'var(--text-tertiary, #999)', fontSize: 11 }}>{t('common.use', { defaultValue: '使用' })}</span>
                      </div>
                    ))}
                    {tagQuery.trim() && !exactExists && (
                      <div style={{ padding: '7px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, borderTop: suggestions.length ? '1px solid var(--color-border, #eee)' : 'none' }}
                        onMouseDown={e => { e.preventDefault(); createDraftTag() }}>
                        <span style={chipStyle(draftColor)}>{tagQuery.trim()}</span>
                        <span style={{ color: 'var(--text-tertiary, #999)', fontSize: 11 }}>{t('pages.notes.createTag', { defaultValue: '即場建立' })}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6, padding: '7px 10px', borderTop: '1px solid var(--color-border, #eee)' }}>
                      <span style={{ fontSize: 11, color: 'var(--text-tertiary, #999)', alignSelf: 'center' }}>{t('pages.notes.tagColor', { defaultValue: '新 tag 顏色' })}</span>
                      {TAG_COLORS.map(c => (
                        <button key={c} type="button" onClick={() => setDraftColor(c)}
                          style={{ width: 16, height: 16, borderRadius: 999, background: c, border: draftColor === c ? '2px solid #111' : '1px solid rgba(0,0,0,.15)', cursor: 'pointer' }} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* T3.1 — + Link record（@ 亦可喺編輯器直接 mention） */}
            <div className="dt-field" style={{ marginTop: 8 }}>
              <span className="f-label">{t('pages.notes.linkedRecords', { defaultValue: '連結 Record（或喺內容打 @）' })}</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginBottom: 6 }}>
                {draftLinks.map(lk => (
                  <span key={lk.entity_type + lk.entity_id} style={chipStyle('#2870b8')}>
                    🔗 {lk.label || lk.entity_type}
                    <button
                      title={t('common.delete')}
                      style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', padding: 0, fontSize: 11, lineHeight: 1 }}
                      onClick={() => setDraftLinks(prev => prev.filter(x => !(x.entity_id === lk.entity_id && x.entity_type === lk.entity_type)))}
                    >✕</button>
                  </span>
                ))}
              </div>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  className="input-field"
                  value={linkQuery}
                  placeholder={t('pages.notes.linkPlaceholder', { defaultValue: '搜尋 contact / company / project / task / touchpoint…' })}
                  onChange={e => { setLinkQuery(e.target.value); setLinkPickerOpen(true) }}
                  onFocus={() => setLinkPickerOpen(true)}
                />
                {linkPickerOpen && linkResults.length > 0 && (
                  <div style={{
                    position: 'absolute', zIndex: 20, left: 0, right: 0, top: '100%',
                    background: 'var(--color-surface, #fff)', border: '1px solid var(--color-border, #ddd)',
                    borderRadius: 8, boxShadow: '0 6px 18px rgba(0,0,0,.12)', maxHeight: 220, overflowY: 'auto', marginTop: 2,
                  }}>
                    {linkResults.map(r => (
                      <div key={r.type + r.id}
                        style={{ padding: '7px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}
                        onMouseDown={e => {
                          e.preventDefault()
                          setDraftLinks(prev => prev.some(x => x.entity_id === r.id && x.entity_type === r.type)
                            ? prev : [...prev, { entity_type: r.type, entity_id: r.id, label: r.label }])
                          setLinkQuery(''); setLinkResults([]); setLinkPickerOpen(false)
                        }}>
                        <span style={{ fontWeight: 600 }}>{r.label}</span>
                        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary, #999)' }}>{r.type}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
              <button className="btn-secondary" onClick={() => setOpen(false)}>{t('common.cancel', { defaultValue: 'Cancel' })}</button>
              <button className="btn-primary" disabled={saving || !title.trim()} onClick={addNote}>
                {saving ? t('common.saving', { defaultValue: 'Saving…' }) : t('common.save', { defaultValue: 'Save' })}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

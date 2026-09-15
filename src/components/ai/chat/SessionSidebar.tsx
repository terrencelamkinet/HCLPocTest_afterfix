import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../../components/SvcIcon'

export interface SessionItem {
  session_id: string
  title: string
  status: string
  created_at: string | null
  is_pinned?: boolean
}

interface Props {
  sessions: SessionItem[]
  currentSessionId: string | null
  onSwitch: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onPin: (id: string, pinned: boolean) => void
  onExport: (id: string) => void
  isOpen: boolean
  onToggle: () => void
}

export default function SessionSidebar({ sessions, currentSessionId, onSwitch, onNew, onRename, onDelete, onPin, onExport, isOpen, onToggle }: Props) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const [renameId, setRenameId] = useState<string | null>(null)
  const [renameText, setRenameText] = useState('')
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; session: SessionItem } | null>(null)

  const filtered = search
    ? sessions.filter(s => s.title.toLowerCase().includes(search.toLowerCase()))
    : sessions

  const today = new Date()
  const todayStr = today.toDateString()
  const weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7)

  const groups = [
    { label: 'Today', sessions: filtered.filter(s => s.created_at && new Date(s.created_at).toDateString() === todayStr) },
    {
      label: 'Past 7 days', sessions: filtered.filter(s => {
        if (!s.created_at) return false
        const d = new Date(s.created_at)
        return d.toDateString() !== todayStr && d >= weekAgo
      })
    },
    { label: 'Earlier', sessions: filtered.filter(s => s.created_at && new Date(s.created_at) < weekAgo) },
  ]

  const handleRename = useCallback((sid: string) => {
    onRename(sid, renameText)
    setRenameId(null)
  }, [renameText, onRename])

  const deleteWithConfirm = useCallback((sid: string) => {
    if (confirm(t('chat.deleteConfirm'))) {
      onDelete(sid)
    }
    setContextMenu(null)
  }, [t, onDelete])

  const sessionName = (s: SessionItem) =>
    s.title
      ? s.title.length > 30 ? s.title.slice(0, 30) + '…' : s.title
      : 'New chat'

  return (
    <>
      {/* Toggle button */}
      <button onClick={onToggle}
        aria-label={t('chat.sessionList')}
        title={t('chat.sessionList')}
        style={{
          width: 28, height: 28, borderRadius: 6,
          display: 'grid', placeItems: 'center',
          background: 'transparent', border: 0,
          color: isOpen ? 'var(--color-primary)' : 'var(--color-text-muted)',
          cursor: 'pointer', flexShrink: 0,
          transition: 'color var(--transition-interactive)',
        }}
      >
        <SvcIcon name="clock" size={15} />
      </button>

      {/* Sidebar overlay */}
      {isOpen && (
        <>
          <div style={{
            position: 'absolute', top: 'var(--topbar-h, 56px)',
            left: 0, bottom: 0, width: 240,
            background: 'var(--color-surface)',
            borderRight: '1px solid var(--color-divider)',
            boxShadow: 'var(--shadow-md)',
            display: 'flex', flexDirection: 'column',
            zIndex: 60, overflow: 'hidden',
            animation: 'fadeIn 200ms var(--ease-out) both',
          }}>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '12px 12px 8px',
              borderBottom: '1px solid var(--color-divider)',
              flexShrink: 0,
            }}>
              <span style={{ flex: 1, fontWeight: 600, fontSize: 13, color: 'var(--color-text)' }}>History</span>
              <button onClick={onNew}
                aria-label={t('chat.newChat')}
                style={{
                  width: 26, height: 26, borderRadius: 6,
                  display: 'grid', placeItems: 'center',
                  background: 'var(--color-primary)', border: 0,
                  color: '#fff', cursor: 'pointer',
                }}
              >
                <SvcIcon name="plus" size={13} />
              </button>
            </div>

            {/* Search */}
            <div style={{ padding: '8px 10px', flexShrink: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'var(--color-surface-offset)', borderRadius: 6,
                padding: '4px 8px',
              }}>
                <SvcIcon name="search" size={13} style={{ color: 'var(--color-text-faint)', flexShrink: 0 }} />
                <input value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={t('chat.searchSessions')}
                  style={{
                    flex: 1, border: 0, outline: 'none',
                    background: 'transparent', font: 'inherit',
                    color: 'inherit', fontSize: 12.5,
                  }}
                />
              </div>
            </div>

            {/* Session list */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 6px 8px' }}>
              {groups.map(group => {
                const groupSessions = group.sessions.slice(0, 20)
                if (groupSessions.length === 0) return null
                return (
                  <div key={group.label}>
                    <div style={{
                      fontSize: 11, fontWeight: 600, color: 'var(--color-text-faint)',
                      padding: '8px 6px 4px', textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}>
                      {group.label}
                    </div>
                    {groupSessions.map(s => (
                      <div key={s.session_id} style={{ position: 'relative' }}>
                        {renameId === s.session_id ? (
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: 4,
                            padding: '6px 8px',
                          }}>
                            <input value={renameText}
                              onChange={e => setRenameText(e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter') handleRename(s.session_id)
                                if (e.key === 'Escape') setRenameId(null)
                              }}
                              autoFocus
                              style={{
                                flex: 1, border: '1px solid var(--color-primary)',
                                outline: 'none', borderRadius: 4, padding: '3px 6px',
                                font: 'inherit', fontSize: 12,
                                background: 'var(--color-surface)', color: 'inherit',
                              }}
                            />
                            <button onClick={() => handleRename(s.session_id)}
                              style={{
                                border: 0, background: 'var(--color-primary)',
                                color: '#fff', borderRadius: 4, padding: '2px 8px',
                                fontSize: 11, cursor: 'pointer', fontWeight: 600,
                              }}
                            >
                              {t('common.save')}
                            </button>
                          </div>
                        ) : (
                          <div
                            onClick={() => { setContextMenu(null); onSwitch(s.session_id) }}
                            onContextMenu={e => {
                              e.preventDefault()
                              setContextMenu({ x: e.clientX, y: e.clientY, session: s })
                            }}
                            className="sidebar-session-row"
                            style={{
                              display: 'flex', alignItems: 'center', gap: 4,
                              width: '100%', padding: '6px 8px', border: 'none',
                              borderRadius: 6,
                              background: s.session_id === currentSessionId ? 'var(--color-primary-highlight)' : 'transparent',
                              color: s.session_id === currentSessionId ? 'var(--color-text)' : 'var(--color-text)',
                              fontSize: 12.5, cursor: 'pointer', textAlign: 'left',
                              transition: 'background var(--transition-interactive)',
                            }}
                            onMouseEnter={e => {
                              if (s.session_id !== currentSessionId)
                                e.currentTarget.style.background = 'var(--color-surface-offset)'
                            }}
                            onMouseLeave={e => {
                              if (s.session_id !== currentSessionId)
                                e.currentTarget.style.background = 'transparent'
                            }}
                          >
                            <span style={{
                              flex: 1, minWidth: 0,
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                            }}>
                              {sessionName(s)}
                            </span>
                            {s.is_pinned && (
                              <SvcIcon name="pin" size={10} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />
                            )}
                            <button onClick={e => {
                              e.stopPropagation()
                              setContextMenu(ctx =>
                                ctx?.session.session_id === s.session_id ? null
                                  : { x: e.clientX - 80, y: e.clientY, session: s }
                              )
                            }}
                              style={{
                                width: 20, height: 20, border: 0, borderRadius: 4,
                                background: 'transparent', color: 'var(--color-text-faint)',
                                cursor: 'pointer', display: 'none', placeItems: 'center',
                                flexShrink: 0,
                              }}
                              className="sidebar-more-btn"
                            >
                              <SvcIcon name="more-horizontal" size={11} />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Context menu */}
          {contextMenu && (
            <>
              <div style={{ position: 'fixed', inset: 0, zIndex: 98 }}
                onClick={() => setContextMenu(null)} />
              <div style={{
                position: 'fixed',
                left: Math.min(contextMenu.x, window.innerWidth - 140),
                top: Math.min(contextMenu.y, window.innerHeight - 200),
                background: 'var(--color-surface-2)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--shadow-lg)',
                zIndex: 99,
                padding: '4px 0',
                minWidth: 130,
                animation: 'fadeIn 100ms ease-out both',
              }}>
                <CtxBtn onClick={() => {
                  setRenameId(contextMenu.session.session_id)
                  setRenameText(contextMenu.session.title)
                  setContextMenu(null)
                }}>
                  <SvcIcon name="pencil" size={12} /> {t('chat.rename')}
                </CtxBtn>
                <CtxBtn onClick={() => {
                  onPin(contextMenu.session.session_id, !contextMenu.session.is_pinned)
                  setContextMenu(null)
                }}>
                  <SvcIcon name="pin" size={12} /> {contextMenu.session.is_pinned ? t('chat.unpin') : t('chat.pin')}
                </CtxBtn>
                <CtxBtn onClick={() => {
                  onExport(contextMenu.session.session_id)
                  setContextMenu(null)
                }}>
                  <SvcIcon name="download" size={12} /> {t('chat.export')}
                </CtxBtn>
                <div style={{ borderTop: '1px solid var(--color-divider)', margin: '4px 0' }} />
                <CtxBtn danger onClick={() => deleteWithConfirm(contextMenu.session.session_id)}>
                  <SvcIcon name="trash-2" size={12} /> {t('chat.delete')}
                </CtxBtn>
              </div>
            </>
          )}
        </>
      )}

      <style>{`
        .sidebar-session-row:hover .sidebar-more-btn { display: grid !important; }
      `}</style>
    </>
  )
}

function CtxBtn({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick}
      style={{
        width: '100%', padding: '6px 12px', border: 'none',
        background: 'transparent',
        color: danger ? 'var(--color-notification)' : 'var(--color-text)',
        fontSize: 12, cursor: 'pointer', textAlign: 'left',
        display: 'flex', alignItems: 'center', gap: 8,
        transition: 'background .1s',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      {children}
    </button>
  )
}

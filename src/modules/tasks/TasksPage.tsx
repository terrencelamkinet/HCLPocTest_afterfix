import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import GenericListPage from '../GenericListPage'
import taskConfig from './config'
import TodoPage from './TodoPage'

type ViewMode = 'todo' | 'table'

export default function TasksPage() {
  const { t } = useTranslation()
  const [view, setView] = useState<ViewMode>(() => {
    const saved = localStorage.getItem('tasks_view_mode')
    return (saved === 'todo' || saved === 'table') ? saved : 'todo'
  })

  const switchView = (v: ViewMode) => {
    setView(v)
    localStorage.setItem('tasks_view_mode', v)
  }

  return (
    <div className={view === 'table' ? 'tasks-table-mode' : ''}>
      {/* View switcher — floating toggle above the page */}
      <div style={{
        display: 'flex', justifyContent: 'flex-end', gap: 6,
        padding: '8px 12px 0',
        position: 'relative', zIndex: 10,
      }}>
        <button
          onClick={() => switchView('todo')}
          style={{
            padding: '4px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
            border: view === 'todo' ? '2px solid var(--color-primary)' : '1px solid var(--color-border)',
            background: view === 'todo' ? 'var(--color-primary)' : 'var(--color-surface)',
            color: view === 'todo' ? '#fff' : 'var(--color-text-muted)',
            cursor: 'pointer', transition: 'all .15s',
          }}
        >
          📋 {t('pages.tasks.title')}
        </button>
        <button
          onClick={() => switchView('table')}
          style={{
            padding: '4px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
            border: view === 'table' ? '2px solid var(--color-primary)' : '1px solid var(--color-border)',
            background: view === 'table' ? 'var(--color-primary)' : 'var(--color-surface)',
            color: view === 'table' ? '#fff' : 'var(--color-text-muted)',
            cursor: 'pointer', transition: 'all .15s',
          }}
        >
          📊 {t('pages.tasks.table')}
        </button>
      </div>

      {view === 'todo' ? <TodoPage /> : <GenericListPage config={taskConfig} />}
    </div>
  )
}

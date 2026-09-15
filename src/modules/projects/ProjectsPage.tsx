import { lazy, useState, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import SvcIcon from '../../components/SvcIcon'
import GenericListPage from '../GenericListPage'
import projectConfig from './config'

const ProjectCalendarView = lazy(() => import('./ProjectCalendarView'))

export default function ProjectsPage() {
  const { t } = useTranslation()
  const [showCalendar, setShowCalendar] = useState(false)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 style={{ display: 'none' }}>{t('pages.projects.title')}</h2>
        <div />
        <div className="range-toggle">
          <button
            onClick={() => setShowCalendar(false)}
            className={!showCalendar ? 'active' : ''}
          >
            <SvcIcon name="table-2" className="w-3.5 h-3.5" />
            {t('pages.projects.table')}
          </button>
          <button
            onClick={() => setShowCalendar(true)}
            className={showCalendar ? 'active' : ''}
          >
            <SvcIcon name="calendar-days" className="w-3.5 h-3.5" />
            {t('pages.projects.calendar')}
          </button>
        </div>
      </div>

      {showCalendar ? (
        <Suspense fallback={<div className="flex items-center justify-center py-20 text-sm text-slate-400">{t('common.loading')}</div>}>
          <ProjectCalendarView />
        </Suspense>
      ) : (
        <GenericListPage config={projectConfig} />
      )}
    </div>
  )
}

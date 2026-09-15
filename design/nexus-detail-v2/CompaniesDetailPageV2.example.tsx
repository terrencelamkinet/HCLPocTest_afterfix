import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import { NexusDetailPageV2, UnifiedTimeline, useAIInsight, type TimelineEvent } from './NexusDetailPageV2'
import { ContactsTab, DealsTab, ProjectsTab, ProductsTab, TouchpointsTab, NotesTab, TasksTab } from './CompanyDetailTabs'
import { useEntity } from './hooks/useEntity'   // existing data-fetch hook in your codebase
import { companyModuleConfig } from './config'

/* ═══════════════════════════════════════════════════════════
   Example integration: CompaniesDetailPage.tsx (V2)
   Drop-in replacement for the old flat tab layout.
   Wire up your existing tab components — no rewrite needed,
   they just render inside NexusDetailPageV2's tab slot.
   ═══════════════════════════════════════════════════════════ */

export default function CompaniesDetailPageV2() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { entity, loading, refresh } = useEntity('companies', id!)
  const { insight, loading: insightLoading, refresh: refreshInsight } = useAIInsight('company', id!)

  const [counts, setCounts] = useState({ contacts: 0, deals: 0, projects: 0, tasks: 0, notes: 0, timeline: 0 })

  if (loading || !entity) return <div className="nx-loading-shell">{t('common.loading')}</div>

  // Example: derive highlight widgets from entity + related counts (fetch in useEntity or a dedicated hook)
  const highlights = [
    { label: t('common.openDeals', { defaultValue: 'Open Deals' }), value: counts.deals },
    { label: t('common.contacts', { defaultValue: 'Contacts' }), value: counts.contacts },
    { label: t('common.overdueTasks', { defaultValue: 'Overdue Tasks' }), value: entity.overdue_tasks_count ?? 0, trend: (entity.overdue_tasks_count ?? 0) > 0 ? 'down' as const : 'neutral' as const },
    { label: t('common.healthScore', { defaultValue: 'Health Score' }), value: entity.health_score ?? '—', trend: 'up' as const },
  ]

  const timelineEvents: TimelineEvent[] = [] // build from activities/touchpoints/notes — see UnifiedTimeline usage in prior tab components

  return (
    <NexusDetailPageV2
      entity={entity}
      moduleConfig={companyModuleConfig}
      avatarLabel={entity.name?.slice(0, 2).toUpperCase() || '?'}
      subline={[entity.industry, entity.company_size, entity.city].filter(Boolean)}
      highlights={highlights}
      aiInsight={insight ?? undefined}
      aiInsightLoading={insightLoading}
      onRefreshInsight={refreshInsight}
      breadcrumbLabel={t('pages.companies.title', { defaultValue: 'Companies' })}
      breadcrumbHref="/companies"
      onEdit={() => navigate(`/companies/${id}/edit`)}
      onAskAI={() => window.dispatchEvent(new CustomEvent('nexus:open-ai-panel', { detail: { context: entity } }))}
      sidebarSections={[
        {
          title: t('common.generalInfo', { defaultValue: 'General Info' }),
          fields: [
            { label: t('fields.industry', { defaultValue: 'Industry' }), value: entity.industry || '—' },
            { label: t('fields.size', { defaultValue: 'Size' }), value: entity.company_size || '—' },
            { label: t('fields.website', { defaultValue: 'Website' }), value: entity.website || '—', aiEnriched: entity.website_ai_filled },
            { label: t('fields.phone', { defaultValue: 'Phone' }), value: entity.phone || '—' },
          ],
        },
        {
          title: t('common.ownership', { defaultValue: 'Ownership' }),
          fields: [
            { label: t('fields.salesOwner', { defaultValue: 'Sales Owner' }), value: entity.owner_name || '—' },
            { label: t('fields.created', { defaultValue: 'Created' }), value: new Date(entity.created_at).toLocaleDateString() },
          ],
        },
      ]}
      relatedCards={entity.top_project ? [{
        title: entity.top_project.name,
        meta: `Project · Deadline ${entity.top_project.deadline}`,
        badge: entity.top_project.status,
      }] : []}
      tabs={[
        { key: 'overview', label: t('common.overview', { defaultValue: 'Overview' }), render: () => <UnifiedTimeline events={timelineEvents.slice(0, 5)} /> },
        { key: 'timeline', label: t('common.timeline', { defaultValue: 'Timeline' }), count: counts.timeline, render: () => <UnifiedTimeline events={timelineEvents} /> },
        { key: 'contacts', label: t('common.contacts', { defaultValue: 'Contacts' }), count: counts.contacts, render: () => <ContactsTab entity={entity} moduleConfig={companyModuleConfig} refresh={refresh} /> },
        { key: 'deals', label: t('common.deals', { defaultValue: 'Deals' }), count: counts.deals, render: () => <DealsTab entity={entity} moduleConfig={companyModuleConfig} refresh={refresh} /> },
        { key: 'projects', label: t('common.projects', { defaultValue: 'Projects' }), count: counts.projects, render: () => <ProjectsTab entity={entity} moduleConfig={companyModuleConfig} refresh={refresh} /> },
        { key: 'tasks', label: t('common.tasks', { defaultValue: 'Tasks' }), count: counts.tasks, render: () => <TasksTab entity={entity} moduleConfig={companyModuleConfig} refresh={refresh} /> },
        { key: 'notes', label: t('common.notes', { defaultValue: 'Notes' }), count: counts.notes, render: () => <NotesTab entity={entity} moduleConfig={companyModuleConfig} refresh={refresh} /> },
      ]}
    />
  )
}

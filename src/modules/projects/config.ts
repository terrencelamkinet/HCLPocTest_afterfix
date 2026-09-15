// ═══════════════════════════════════════════
//  Penguin CRM — Projects Module Config
//  ═══════════════════════════════════════════

import type { ResourceConfig } from '../module-types'
import { lazy } from 'react'

const ProjectDetailCalendar = lazy(() => import('./ProjectDetailCalendar'))

const projectConfig: ResourceConfig = {
  name: 'project',
  label: 'Project',
  labelPlural: 'Projects',
  icon: 'FolderKanban',
  apiPath: '/api/v1/crm/projects',
  routePrefix: 'projects',

  fields: [
    { key: 'name',         label: 'Project Name',  type: 'title',    required: true,  searchable: true, sortable: true, visibleByDefault: true },
    { key: 'description',  label: 'Description',   type: 'rich_text', gridColumn: 'full', visibleByDefault: false },
    { key: 'status',       label: 'Status',        type: 'select',   sortable: true, filterable: true, bulkEditable: true, visibleByDefault: true,
      options: [
        { value: 'planning',     label: 'Planning',     color: 'blue' },
        { value: 'in_progress',  label: 'In Progress',  color: 'green' },
        { value: 'on_hold',      label: 'On Hold',      color: 'yellow' },
        { value: 'completed',    label: 'Completed',    color: 'gray' },
        { value: 'cancelled',    label: 'Cancelled',    color: 'red' },
      ]},
    { key: 'priority',     label: 'Priority',      type: 'select',   sortable: true, filterable: true, bulkEditable: true, visibleByDefault: true,
      options: [
        { value: 'low',      label: 'Low',      color: 'blue' },
        { value: 'medium',   label: 'Medium',   color: 'yellow' },
        { value: 'high',     label: 'High',     color: 'orange' },
        { value: 'critical', label: 'Critical', color: 'red' },
      ]},
    { key: 'start_date',   label: 'Start Date',    type: 'date',     sortable: true, visibleByDefault: false },
    { key: 'deadline',     label: 'Deadline',      type: 'date',     sortable: true, visibleByDefault: true },
    { key: 'budget_amount',   label: 'Budget',        type: 'number',   format: 'hkd',  sortable: true, visibleByDefault: false },
    // 2026-09-11 用戶指示：Project 唔需要綁公司 → 唔再 required
    // （NexusSmartAddModal L273 會因 required 空白而封鎖提交；L281 對非 required 空白會 delete key）
    { key: 'company',         label: 'Company',       type: 'relation', sortable: false, filterable: true, visibleByDefault: true,
      relation: { resource: 'companies', multiple: false, displayField: 'name' }, apiKey: 'company_id' },
    { key: 'sales_owner_id',  label: 'Sales Owner',   type: 'relation', sortable: true, filterable: true, visibleByDefault: true,
      relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
    { key: 'incharge_client_id', label: 'Incharge Client', type: 'relation', sortable: true, filterable: true, visibleByDefault: false,
      relation: { resource: 'contacts', multiple: false, displayField: 'name' } },
    { key: 'project_manager_id',     label: 'Project Manager',         type: 'relation', sortable: true, filterable: true, visibleByDefault: true,
      relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
    { key: 'created_at',   label: 'Created',       type: 'created_time', sortable: true, visibleByDefault: true },
  ],

  listColumns: ['name', 'status', 'priority', 'company', 'deadline', 'sales_owner_id'],
  defaultSort: [{ field: 'created_at', direction: 'desc' }],
  defaultView: 'table',
  views: [
    { type: 'table', label: 'Table' },
    { type: 'calendar', label: 'Calendar' },
  ],
  allowedBulkActions: ['update', 'archive', 'export'],

  hideProfileCard: true,

  savedViews: [
    { id: 'all', name: 'All Projects', layout: 'table' },
  ],

  detailTabs: [
    { id: 'details', label: 'Details', fields: [
      'name', 'description', 'status', 'priority',
      'start_date', 'deadline', 'budget_amount',
      'company', 'sales_owner_id', 'incharge_client_id', 'project_manager_id', 'created_at',
    ]},
    { id: 'team',     label: 'Team' },
    { id: 'tasks',    label: 'Tasks' },
    { id: 'notes',    label: 'Notes' },
    { id: 'timeline', label: 'Timeline', render: ProjectDetailCalendar },
  ],
}

export default projectConfig

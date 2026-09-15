// ═══════════════════════════════════════════
//  Penguin CRM — Touchpoints Module Config
//  ═══════════════════════════════════════════

import type { ResourceConfig } from '../module-types'

const touchpointConfig: ResourceConfig = {
  name: 'touchpoint',
  label: 'Touchpoint',
  labelPlural: 'Touchpoints',
  icon: 'Activity',
  apiPath: '/api/v1/crm/touchpoints',
  routePrefix: 'touchpoints',

  fields: [
    { key: 'title',          label: 'Title',        type: 'title',    required: true,  searchable: true, sortable: true, visibleByDefault: true },
    { key: 'type',           label: 'Type',         type: 'select',   filterable: true, bulkEditable: true, visibleByDefault: true,
      options: [
        { value: 'meeting',  label: 'Meeting',   color: 'blue' },
        { value: 'call',     label: 'Call',      color: 'green' },
        { value: 'email',    label: 'Email',     color: 'purple' },
        { value: 'note',     label: 'Note',      color: 'yellow' },
        { value: 'social',   label: 'Social',    color: 'pink' },
        { value: 'lunch',    label: 'Lunch',     color: 'orange' },
        { value: 'other',    label: 'Other',     color: 'gray' },
      ]},
    { key: 'description',    label: 'Description',  type: 'rich_text', gridColumn: 'full', visibleByDefault: false },
    /* 2026-09-11: format 'datetime' adds the TIME picker — the field was date-only,
       so a touchpoint could not record WHEN it happened (「During 沒有時間選擇」). */
    { key: 'date',           label: 'Date',         type: 'date',     format: 'datetime', sortable: true, visibleByDefault: true },
    { key: 'duration_minutes', label: 'Duration',   type: 'number',   format: 'hours', visibleByDefault: false },
    { key: 'location',       label: 'Location',     type: 'text',     visibleByDefault: false },
    { key: 'participants',  label: 'Contact',    type: 'relation', sortable: false, filterable: true, visibleByDefault: true,
      relation: { resource: 'contacts', multiple: true, displayField: 'name' } },
    { key: 'companies',      label: 'Company',     type: 'relation', sortable: false, filterable: true, visibleByDefault: true,
      relation: { resource: 'companies', multiple: true, displayField: 'name' } },
    { key: 'created_at',     label: 'Created',      type: 'created_time', sortable: true, visibleByDefault: true },
  ],

  listColumns: ['title', 'type', 'date', 'participants', 'companies', 'created_at'],
  defaultSort: [{ field: 'date', direction: 'desc' }],
  defaultView: 'table',
  allowedBulkActions: ['update', 'archive', 'export'],

  hideProfileCard: true,

  savedViews: [
    { id: 'all', name: 'All Touchpoints', layout: 'table' },
  ],

  detailTabs: [
    { id: 'details', label: 'Details', fields: [
      'title', 'type', 'description', 'date', 'duration_minutes',
      'location', 'participants', 'companies', 'created_at',
    ]},
    { id: 'timeline', label: 'Timeline' },
  ],
}

export default touchpointConfig

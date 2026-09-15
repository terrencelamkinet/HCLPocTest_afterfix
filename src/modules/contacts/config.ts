// ═══════════════════════════════════════════
//  Penguin CRM — Contacts Module Config
//  ═══════════════════════════════════════════

import type { ResourceConfig } from '../module-types'

const contactConfig: ResourceConfig = {
  name: 'contact',
  label: 'Contact',
  labelPlural: 'Contacts',
  icon: 'User',
  apiPath: '/api/v1/crm/contacts',

  fields: [
    { key: 'name',           label: 'Client Name',  type: 'title',    required: true,  searchable: true, sortable: true, visibleByDefault: true },
    { key: 'chinese_name',   label: 'Chinese Name', type: 'text',     searchable: true, visibleByDefault: false },
    { key: 'nick_name',      label: 'Nick Name',    type: 'text',     searchable: true, visibleByDefault: false },
    { key: 'job_title',       label: 'Title',        type: 'text',     sortable: true, visibleByDefault: false },
    { key: 'department',     label: 'Department',   type: 'text',     sortable: true, visibleByDefault: false },
    { key: 'contact_type',   label: 'Contact Type', type: 'select',   filterable: true, bulkEditable: true,
      options: [{ value: 'Distributor', label: 'Distributor', color: 'blue' }, { value: 'Vendor', label: 'Vendor', color: 'purple' }, { value: 'Client', label: 'Client', color: 'green' }] },
    { key: 'grade',          label: 'Grade',        type: 'select',   filterable: true, bulkEditable: true,
      options: [{ value: '1', label: '1', color: 'green' }, { value: '2', label: '2', color: 'blue' }, { value: '3', label: '3', color: 'yellow' }, { value: '4', label: '4', color: 'red' }] },
    { key: 'tags',           label: 'Tag',          type: 'multi_select', bulkEditable: true,
      options: [{ value: 'Sales', label: 'Sales', color: 'blue' }, { value: 'Client', label: 'Client', color: 'green' }, { value: 'Technical', label: 'Technical', color: 'purple' }, { value: 'Head', label: 'Head', color: 'yellow' }, { value: 'Internal Sales', label: 'Internal Sales', color: 'gray' }] },
    { key: 'numbers',        label: 'Contact No.',  type: 'multi_select',
      options: [{ value: '1', label: '1' }, { value: '2', label: '2' }, { value: '3', label: '3' }, { value: '4', label: '4' }, { value: '5', label: '5' }, { value: '6', label: '6' }, { value: '7', label: '7' }, { value: '8', label: '8' }] },
    { key: 'email',          label: 'Email',        type: 'email',    sortable: true, searchable: true, visibleByDefault: true },
    { key: 'phone',          label: 'Phone',        type: 'phone',    visibleByDefault: true, searchable: true },
    { key: 'office_phone',   label: 'Office Phone', type: 'phone',    visibleByDefault: false },
    { key: 'linkedin_url',   label: 'LinkedIn URL', type: 'url',      visibleByDefault: false },
    { key: 'address',        label: 'Address',      type: 'text',     visibleByDefault: false },
    { key: 'notes',          label: 'Notes',        type: 'rich_text', gridColumn: 'full', visibleByDefault: false },
    { key: 'namecard_path',  label: 'Name Card',    type: 'text',     gridColumn: 'full', visibleByDefault: false },
    { key: 'company',        label: 'Company',      type: 'relation', sortable: false, filterable: true, visibleByDefault: true,
      relation: { resource: 'companies', multiple: false, displayField: 'name' } },
    { key: 'status',         label: 'Status',       type: 'status',   sortable: true, filterable: true, bulkEditable: true, visibleByDefault: true,
      options: [{ value: 'Active', label: 'Active', color: 'green' }, { value: 'Warm', label: 'Warm', color: 'yellow' }, { value: 'Cold', label: 'Cold', color: 'blue' }, { value: 'VIP', label: 'VIP', color: 'purple' }, { value: 'Inactive', label: 'Inactive', color: 'gray' }] },
    { key: 'created_at',     label: 'Created',      type: 'created_time', sortable: true, visibleByDefault: true },
  ],

  listColumns: ['name', 'company', 'email', 'status', 'created_at'],
  defaultSort: [{ field: 'created_at', direction: 'desc' }],
  defaultView: 'table',
  allowedBulkActions: ['update', 'archive', 'export'],

  savedViews: [
    { id: 'all', name: 'All Contacts', layout: 'table' },
  ],

  detailTabs: [
    { id: 'details', label: 'Details', fields: [
      'name', 'chinese_name', 'nick_name', 'job_title', 'department',
      'contact_type', 'grade', 'tags', 'numbers',
      'email', 'phone', 'office_phone', 'linkedin_url', 'address',
      'notes', 'namecard_path', 'company', 'created_at',
    ]},
    { id: 'timeline',    label: 'Timeline' },
    { id: 'deals',       label: 'Deals',
      condition: (e: any) => e._salesOn !== false },
    { id: 'tasks',       label: 'Tasks' },
    { id: 'touchpoints', label: 'Touchpoints' },
    { id: 'notes',       label: 'Notes' },
    { id: 'projects',    label: 'Projects' },
  ],

  // NovaCRM-style architecture: group detail fields into labelled sections (G08 design tokens)
  fieldGroups: [
    { id: 'profile',  label: 'Basic Info',   fields: ['name', 'chinese_name', 'nick_name', 'job_title', 'department', 'company'] },
    { id: 'contact',  label: 'Contact Info', fields: ['email', 'phone', 'office_phone', 'linkedin_url', 'address', 'numbers'] },
    { id: 'classify', label: 'Category',     fields: ['contact_type', 'grade', 'tags'] },
    { id: 'other',    label: 'Other',        fields: ['notes', 'namecard_path', 'created_at'] },
  ],
}

export default contactConfig

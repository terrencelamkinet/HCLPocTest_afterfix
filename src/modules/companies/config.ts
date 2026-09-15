// ═══════════════════════════════════════════
//  Penguin CRM — Companies Module Config
//  ═══════════════════════════════════════════

import type { ResourceConfig } from '../module-types'

const companyConfig: ResourceConfig = {
  name: 'company',
  label: 'Company',
  labelPlural: 'Companies',
  icon: 'Building2',
  apiPath: '/api/v1/crm/companies',
  routePrefix: 'companies',

  fields: [
    { key: 'name',            label: 'Company Name',   type: 'title',    required: true,  searchable: true, sortable: true, visibleByDefault: true },
    { key: 'category',        label: 'Category',       type: 'select',   filterable: true, bulkEditable: true,
      options: [
        { value: 'Client', label: 'Client', color: 'green' },
        { value: 'Vendor', label: 'Vendor', color: 'blue' },
        { value: 'Partner', label: 'Partner', color: 'purple' },
        { value: 'Distributor', label: 'Distributor', color: 'yellow' },
        { value: 'Vendor-Distributor', label: 'Vendor-Distributor', color: 'orange' },
      ]},
    { key: 'industry',        label: 'Industry',       type: 'select', bulkEditable: true,
      options: [
        { value: 'Storage Provider', label: 'Storage Provider' },
        { value: 'ITSM Solution', label: 'ITSM Solution' },
        { value: 'Enterprise Software', label: 'Enterprise Software' },
        { value: 'Investment', label: 'Investment' },
        { value: 'Properties', label: 'Properties' },
        { value: 'Hospitality', label: 'Hospitality' },
        { value: 'Manufactures', label: 'Manufactures' },
        { value: 'Services Provider', label: 'Services Provider' },
        { value: 'Education', label: 'Education' },
        { value: 'Exhibition', label: 'Exhibition' },
        { value: 'Data Center Provider', label: 'Data Center Provider' },
        { value: 'Technology', label: 'Technology' },
        { value: 'Health Care', label: 'Health Care' },
        { value: 'Government', label: 'Government' },
        { value: 'Distributor', label: 'Distributor' },
      ]},
    { key: 'address',         label: 'Address',        type: 'text',     visibleByDefault: false },
    { key: 'ceo_name',        label: 'CEO',            type: 'text',     searchable: true, visibleByDefault: false },
    { key: 'website',         label: 'Website',        type: 'url',      visibleByDefault: false },
    { key: 'linkedin_url',    label: 'LinkedIn',       type: 'url',      visibleByDefault: false },
    { key: 'domain',          label: 'Domain',         type: 'text',     searchable: true, visibleByDefault: false },
    { key: 'phone',           label: 'Phone',          type: 'phone',    searchable: true, visibleByDefault: false },
    { key: 'notes',           label: 'Notes',          type: 'rich_text', gridColumn: 'full', visibleByDefault: false },
    { key: 'status',          label: 'Status',         type: 'status',   sortable: true, filterable: true, bulkEditable: true, visibleByDefault: true,
      options: [
        { value: 'ACTIVE', label: 'Active', color: 'green' },
        { value: 'INACTIVE', label: 'Inactive', color: 'gray' },
        { value: 'LEAD', label: 'Lead', color: 'blue' },
        { value: 'PROSPECT', label: 'Prospect', color: 'yellow' },
        { value: 'CHURNED', label: 'Churned', color: 'red' },
      ]},
    { key: 'owner_id',        label: 'Sales Owner',    type: 'relation', sortable: true, filterable: true,
      relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
    { key: 'created_at',      label: 'Created',        type: 'created_time', sortable: true, visibleByDefault: true },
  ],

  listColumns: ['name', 'category', 'status', 'owner_id', 'created_at'],
  defaultSort: [{ field: 'created_at', direction: 'desc' }],
  defaultView: 'table',
  allowedBulkActions: ['update', 'archive', 'export'],

  savedViews: [
    { id: 'all', name: 'All Companies', layout: 'table' },
  ],

  detailTabs: [
    { id: 'details', label: 'Details', fields: [
      'name', 'category', 'industry',
      'address', 'ceo_name', 'website', 'linkedin_url', 'domain',
      'phone', 'notes', 'status', 'owner_id', 'created_at',
    ]},
    { id: 'contacts',      label: 'Contacts' },
    { id: 'deals',         label: 'Deals' },
    { id: 'projects',      label: 'Projects' },
    { id: 'products',      label: 'Products' },
    { id: 'partners',      label: 'Partners' },
    { id: 'tasks',         label: 'Tasks' },
    { id: 'touchpoints',   label: 'Touchpoints' },
    { id: 'notes',         label: 'Notes' },
    { id: 'timeline',      label: 'Timeline' },
  ],
}

export default companyConfig

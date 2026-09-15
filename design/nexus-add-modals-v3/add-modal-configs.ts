// ═══════════════════════════════════════════════════════
// add-modal-configs.ts
// 5 個 module 嘅 Add Modal field 定義（company / contact / task / project / touchpoint）
// 直接被 NexusSmartAddModal 使用，唔需要為每個 module 各寫一份 modal
// ═══════════════════════════════════════════════════════
import type { ModuleConfig } from './module-types'

export const companyAddConfig: ModuleConfig = {
  name: 'company',
  apiPath: '/api/v1/crm/companies',
  fields: [
    { key: 'name', label: 'Company Name', type: 'title', required: true, gridColumn: 'full' },
    { key: 'industry', label: 'Industry', type: 'select', options: [
      { value: 'logistics', label: 'Logistics' }, { value: 'trading', label: 'Trading' },
      { value: 'manufacturing', label: 'Manufacturing' }, { value: 'other', label: 'Other' },
    ]},
    { key: 'size', label: 'Company Size', type: 'select', options: [
      { value: '1-10', label: '1-10' }, { value: '11-50', label: '11-50' }, { value: '51-200', label: '51-200' }, { value: '200+', label: '200+' },
    ]},
    { key: 'website', label: 'Website', type: 'url' },
    { key: 'phone', label: 'Phone', type: 'text' },
    { key: 'address', label: 'Address', type: 'rich_text', gridColumn: 'full' },
  ],
}

export const contactAddConfig: ModuleConfig = {
  name: 'contact',
  apiPath: '/api/v1/crm/contacts',
  fields: [
    { key: 'name', label: 'Name', type: 'title', required: true, gridColumn: 'full' },
    { key: 'email', label: 'Email', type: 'email' },
    { key: 'phone', label: 'Phone', type: 'text' },
    { key: 'company', label: 'Company', type: 'relation', relation: { resource: 'companies', displayField: 'name' }, gridColumn: 'full' },
    { key: 'job_title', label: 'Job Title', type: 'text' },
    { key: 'status', label: 'Status', type: 'select', options: [
      { value: 'lead', label: 'Lead', color: 'blue' }, { value: 'active', label: 'Active', color: 'green' },
      { value: 'inactive', label: 'Inactive', color: 'gray' },
    ]},
  ],
}

export const taskAddConfig: ModuleConfig = {
  name: 'task',
  apiPath: '/api/v1/crm/tasks',
  fields: [
    { key: 'title', label: 'Task Title', type: 'title', required: true, gridColumn: 'full' },
    { key: 'priority', label: 'Priority', type: 'select', options: [
      { value: 'low', label: 'Low', color: 'blue' }, { value: 'medium', label: 'Medium', color: 'yellow' },
      { value: 'high', label: 'High', color: 'orange' },
    ]},
    { key: 'due_date', label: 'Due Date', type: 'date' },
    { key: 'assignee_id', label: 'Assignee', type: 'relation', relation: { resource: 'users', displayField: 'display_name' } },
    { key: 'related_company', label: 'Related Company', type: 'relation', relation: { resource: 'companies', displayField: 'name' } },
    { key: 'description', label: 'Description', type: 'rich_text', gridColumn: 'full' },
  ],
}

export const projectAddConfig: ModuleConfig = {
  name: 'project',
  apiPath: '/api/v1/crm/projects',
  fields: [
    { key: 'name', label: 'Project Name', type: 'title', required: true, gridColumn: 'full' },
    { key: 'status', label: 'Status', type: 'select', options: [
      { value: 'planning', label: 'Planning', color: 'blue' }, { value: 'in_progress', label: 'In Progress', color: 'green' },
    ]},
    { key: 'priority', label: 'Priority', type: 'select', options: [
      { value: 'low', label: 'Low', color: 'blue' }, { value: 'high', label: 'High', color: 'orange' },
    ]},
    { key: 'deadline', label: 'Deadline', type: 'date' },
    { key: 'budget_amount', label: 'Budget', type: 'number', format: 'hkd' },
    { key: 'company', label: 'Company', type: 'relation', required: true, relation: { resource: 'companies', displayField: 'name' }, gridColumn: 'full' },
  ],
}

export const touchpointAddConfig: ModuleConfig = {
  name: 'touchpoint',
  apiPath: '/api/v1/crm/touchpoints',
  fields: [
    { key: 'title', label: 'Touchpoint Title', type: 'title', required: true, gridColumn: 'full' },
    { key: 'channel', label: 'Channel', type: 'select', options: [
      { value: 'whatsapp', label: 'WhatsApp', color: 'green' }, { value: 'email', label: 'Email', color: 'blue' },
      { value: 'call', label: 'Call', color: 'yellow' }, { value: 'meeting', label: 'Meeting', color: 'purple' },
    ]},
    { key: 'occurred_at', label: 'Date', type: 'date' },
    { key: 'contact', label: 'Contact', type: 'relation', relation: { resource: 'contacts', displayField: 'name' } },
    { key: 'summary', label: 'Summary', type: 'rich_text', gridColumn: 'full' },
  ],
}

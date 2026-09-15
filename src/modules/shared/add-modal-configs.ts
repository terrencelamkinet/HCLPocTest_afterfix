// ═══════════════════════════════════════════════════════
// add-modal-configs.ts
// 5 個 module 嘅 Add Modal field 定義（company / contact / task / project / touchpoint）
// 直接被 NexusSmartAddModal 使用，唔需要為每個 module 各寫一份 modal
//
// fields = real module config 入面「全部 editable fields」：
//   - editable !== false，且 type 唔係 rollup/formula/created_time/
//     last_edited_time/created_by/last_edited_by/unique_id
//   - key 唔係 created_at / updated_at
// 排序：zip 版有嘅 field 跟 zip 順序排頭，其餘跟 real config 順序補上。
// ═══════════════════════════════════════════════════════
import type { FieldConfig } from '../module-types'

/** Slim config shape for the smart add modal (name/apiPath/fields/label). */
export interface AddModalConfig {
  name: string
  label?: string
  apiPath: string
  fields: FieldConfig[]
}

export const ADD_CONFIGS: Record<string, AddModalConfig> = {
  company: {
    name: 'company',
    label: 'Company',
    apiPath: '/api/v1/crm/companies',
    fields: [
      // zip 版順序
      { key: 'name',      label: 'Company Name', type: 'title', required: true, gridColumn: 'full' },
      { key: 'industry',  label: 'Industry',     type: 'select', options: [
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
      ] },
      { key: 'website',   label: 'Website',      type: 'url' },
      { key: 'phone',     label: 'Phone',        type: 'text' },
      { key: 'address',   label: 'Address',      type: 'text' },
      // real config 補上
      { key: 'category',  label: 'Category',     type: 'select', options: [
        { value: 'Client', label: 'Client', color: 'green' },
        { value: 'Vendor', label: 'Vendor', color: 'blue' },
        { value: 'Partner', label: 'Partner', color: 'purple' },
        { value: 'Distributor', label: 'Distributor', color: 'yellow' },
        { value: 'Vendor-Distributor', label: 'Vendor-Distributor', color: 'orange' },
      ] },
      { key: 'ceo_name',  label: 'CEO',          type: 'text' },
      { key: 'linkedin_url', label: 'LinkedIn',  type: 'url' },
      { key: 'domain',    label: 'Domain',       type: 'text' },
      { key: 'notes',     label: 'Notes',        type: 'rich_text', gridColumn: 'full' },
      { key: 'status',    label: 'Status',       type: 'status', options: [
        { value: 'ACTIVE', label: 'Active', color: 'green' },
        { value: 'INACTIVE', label: 'Inactive', color: 'gray' },
        { value: 'LEAD', label: 'Lead', color: 'blue' },
        { value: 'PROSPECT', label: 'Prospect', color: 'yellow' },
        { value: 'CHURNED', label: 'Churned', color: 'red' },
      ] },
      { key: 'owner_id',  label: 'Sales Owner',  type: 'relation', relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
    ],
  },

  contact: {
    name: 'contact',
    label: 'Contact',
    apiPath: '/api/v1/crm/contacts',
    fields: [
      // zip 版順序
      { key: 'name',      label: 'Name',         type: 'title', required: true, gridColumn: 'full' },
      { key: 'email',     label: 'Email',        type: 'email' },
      { key: 'phone',     label: 'Phone',        type: 'phone' },
      { key: 'company',   label: 'Company',      type: 'relation', relation: { resource: 'companies', multiple: false, displayField: 'name' } },
      { key: 'job_title', label: 'Title',        type: 'text' },
      { key: 'status',    label: 'Status',       type: 'status', options: [
        { value: 'Active', label: 'Active', color: 'green' },
        { value: 'Warm', label: 'Warm', color: 'yellow' },
        { value: 'Cold', label: 'Cold', color: 'blue' },
        { value: 'VIP', label: 'VIP', color: 'purple' },
        { value: 'Inactive', label: 'Inactive', color: 'gray' },
      ] },
      // real config 補上
      { key: 'chinese_name', label: 'Chinese Name', type: 'text' },
      { key: 'nick_name', label: 'Nick Name', type: 'text' },
      { key: 'department', label: 'Department', type: 'text' },
      { key: 'contact_type', label: 'Contact Type', type: 'select', options: [
        { value: 'Distributor', label: 'Distributor', color: 'blue' },
        { value: 'Vendor', label: 'Vendor', color: 'purple' },
        { value: 'Client', label: 'Client', color: 'green' },
      ] },
      { key: 'grade',     label: 'Grade',        type: 'select', options: [
        { value: '1', label: '1', color: 'green' },
        { value: '2', label: '2', color: 'blue' },
        { value: '3', label: '3', color: 'yellow' },
        { value: '4', label: '4', color: 'red' },
      ] },
      { key: 'tags',      label: 'Tag',          type: 'multi_select', options: [
        { value: 'Sales', label: 'Sales', color: 'blue' },
        { value: 'Client', label: 'Client', color: 'green' },
        { value: 'Technical', label: 'Technical', color: 'purple' },
        { value: 'Head', label: 'Head', color: 'yellow' },
        { value: 'Internal Sales', label: 'Internal Sales', color: 'gray' },
      ] },
      { key: 'numbers',   label: 'Contact No.',  type: 'multi_select', options: [
        { value: '1', label: '1' }, { value: '2', label: '2' }, { value: '3', label: '3' },
        { value: '4', label: '4' }, { value: '5', label: '5' }, { value: '6', label: '6' },
        { value: '7', label: '7' }, { value: '8', label: '8' },
      ] },
      { key: 'office_phone', label: 'Office Phone', type: 'phone' },
      { key: 'linkedin_url', label: 'LinkedIn URL', type: 'url' },
      { key: 'address',   label: 'Address',      type: 'text' },
      { key: 'notes',     label: 'Notes',        type: 'rich_text', gridColumn: 'full' },
      { key: 'namecard_path', label: 'Name Card', type: 'text', gridColumn: 'full' },
    ],
  },

  task: {
    name: 'task',
    label: 'Task',
    apiPath: '/api/v1/crm/tasks',
    fields: [
      // zip 版順序
      { key: 'title',     label: 'Task Title',   type: 'title', required: true, gridColumn: 'full' },
      { key: 'priority',  label: 'Priority',     type: 'select', options: [
        { value: 'P0', label: 'Urgent', color: 'red' },
        { value: 'P1', label: 'High', color: 'orange' },
        { value: 'P2', label: 'Medium', color: 'blue' },
        { value: 'P3', label: 'Low', color: 'gray' },
      ] },
      { key: 'due_date',  label: 'Due Date',     type: 'date' },
      { key: 'assignee_id', label: 'Assignee',   type: 'relation', relation: { resource: 'users', multiple: false, displayField: 'email' } },
      { key: 'company_id',  label: 'Company',    type: 'relation', relation: { resource: 'companies', multiple: false, displayField: 'name' } },
      { key: 'description', label: 'Description', type: 'rich_text', gridColumn: 'full' },
      // real config 補上
      { key: 'status',    label: 'Status',       type: 'status', options: [
        { value: 'pending', label: 'Pending', color: 'yellow' },
        { value: 'in_progress', label: 'In Progress', color: 'blue' },
        { value: 'done', label: 'Done', color: 'green' },
        { value: 'cancelled', label: 'Cancelled', color: 'gray' },
      ] },
      { key: 'contact_id', label: 'Contact',     type: 'relation', relation: { resource: 'contacts', multiple: false, displayField: 'name' } },
      { key: 'notes_html', label: 'Notes',       type: 'rich_text', gridColumn: 'full' },
    ],
  },

  project: {
    name: 'project',
    label: 'Project',
    apiPath: '/api/v1/crm/projects',
    fields: [
      // zip 版順序
      { key: 'name',         label: 'Project Name', type: 'title', required: true, gridColumn: 'full' },
      { key: 'status',       label: 'Status',       type: 'select', options: [
        { value: 'planning', label: 'Planning', color: 'blue' },
        { value: 'in_progress', label: 'In Progress', color: 'green' },
        { value: 'on_hold', label: 'On Hold', color: 'yellow' },
        { value: 'completed', label: 'Completed', color: 'gray' },
        { value: 'cancelled', label: 'Cancelled', color: 'red' },
      ] },
      { key: 'priority',     label: 'Priority',     type: 'select', options: [
        { value: 'low', label: 'Low', color: 'blue' },
        { value: 'medium', label: 'Medium', color: 'yellow' },
        { value: 'high', label: 'High', color: 'orange' },
        { value: 'critical', label: 'Critical', color: 'red' },
      ] },
      { key: 'deadline',     label: 'Deadline',     type: 'date' },
      { key: 'budget_amount', label: 'Budget',      type: 'number', format: 'hkd' },
      // 2026-09-11 用戶指示：Project 唔需要綁公司 → 唔再 required
      { key: 'company',      label: 'Company',      type: 'relation', relation: { resource: 'companies', multiple: false, displayField: 'name' }, apiKey: 'company_id' },
      // real config 補上
      { key: 'description',  label: 'Description',  type: 'rich_text', gridColumn: 'full' },
      { key: 'start_date',   label: 'Start Date',   type: 'date' },
      { key: 'sales_owner_id', label: 'Sales Owner', type: 'relation', relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
      { key: 'incharge_client_id', label: 'Incharge Client', type: 'relation', relation: { resource: 'contacts', multiple: false, displayField: 'name' } },
      { key: 'project_manager_id', label: 'Project Manager', type: 'relation', relation: { resource: 'users', multiple: false, displayField: 'display_name' } },
    ],
  },

  touchpoint: {
    name: 'touchpoint',
    label: 'Touchpoint',
    apiPath: '/api/v1/crm/touchpoints',
    fields: [
      // zip 版順序
      { key: 'title',    label: 'Touchpoint Title', type: 'title', required: true, gridColumn: 'full' },
      { key: 'type',     label: 'Type',             type: 'select', options: [
        { value: 'meeting', label: 'Meeting', color: 'blue' },
        { value: 'call', label: 'Call', color: 'green' },
        { value: 'email', label: 'Email', color: 'purple' },
        { value: 'note', label: 'Note', color: 'yellow' },
        { value: 'social', label: 'Social', color: 'pink' },
        { value: 'lunch', label: 'Lunch', color: 'orange' },
        { value: 'other', label: 'Other', color: 'gray' },
      ] },
      { key: 'date',     label: 'Date',             type: 'date' },
      // 2026-09-09: 人物支援多於一個（contact_id 單一 → participants multi — backend alias 已食）
      { key: 'participants', label: 'Contact',      type: 'relation', relation: { resource: 'contacts', multiple: true, displayField: 'name' } },
      // touchpoint 正文 = description（summary 係 zip legacy — 移除避免混淆）
      { key: 'description', label: 'Description',   type: 'rich_text', gridColumn: 'full' },
      { key: 'duration_minutes', label: 'Duration', type: 'number', format: 'hours' },
      { key: 'location', label: 'Location',         type: 'text' },
      // 2026-09-09: 多公司（011 — companies 全列；第一個 = 主要 company_id）
      { key: 'companies',  label: 'Company',        type: 'relation', relation: { resource: 'companies', multiple: true, displayField: 'name' } },
    ],
  },

  // v6.93: project-centric — Note quick-create（設計文件 Add grid 有 Note，Deal 移除）
  note: {
    name: 'note',
    label: 'Note',
    apiPath: '/api/v1/crm/notes',
    fields: [
      { key: 'title',   label: 'Note Title', type: 'title', required: true, gridColumn: 'full' },
      { key: 'content', label: 'Content',    type: 'rich_text', gridColumn: 'full' },
      { key: 'contact', label: 'Contact',    type: 'relation', relation: { resource: 'contacts', multiple: false, displayField: 'name' }, apiKey: 'contact_id' },
      { key: 'company', label: 'Company',    type: 'relation', relation: { resource: 'companies', multiple: false, displayField: 'name' }, apiKey: 'company_id' },
      { key: 'project', label: 'Project',    type: 'relation', relation: { resource: 'projects', multiple: false, displayField: 'name' }, apiKey: 'project_id' },
    ],
  },
}

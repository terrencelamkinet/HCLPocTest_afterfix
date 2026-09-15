// ═══════════════════════════════════════════
//  Shared i18n label helpers for module config
//  Config files keep raw EN labels (data layer);
//  this maps field keys → i18n keys at render time
//  ═══════════════════════════════════════════

import type { FieldConfig } from '../module-types'

/** field.key → i18n key (keys shared across modules) */
const FIELD_LABEL_KEYS: Record<string, string> = {
  name: 'common.clientName',
  chinese_name: 'common.chineseName',
  nick_name: 'common.nickName',
  job_title: 'common.jobTitle',
  department: 'common.department',
  contact_type: 'common.contactType',
  grade: 'common.grade',
  tags: 'common.tag',
  numbers: 'common.number',
  email: 'common.email',
  phone: 'common.phone',
  office_phone: 'common.office',
  linkedin_url: 'common.linkedin',
  address: 'common.address',
  notes: 'common.notes',
  company: 'common.company',
  status: 'common.status',
  category: 'common.category',
  priority: 'common.priority',
  deadline: 'common.deadline',
  description: 'common.description',
  start_date: 'common.startDate',
  budget_amount: 'common.budget',
  sales_owner_id: 'common.salesOwner',
  incharge_client_id: 'common.inchargeClient',
  project_manager_id: 'common.projectManager',
  created_at: 'pages.contacts.detail.createdTime',
  namecard_path: 'pages.contacts.detail.nameCard',
}

/** detail tab id → i18n key */
const TAB_LABEL_KEYS: Record<string, string> = {
  details: 'pages.contacts.detail.tabs.details',
  timeline: 'pages.contacts.detail.tabs.timeline',
  deals: 'pages.contacts.detail.tabs.deals',
  tasks: 'pages.contacts.detail.tabs.tasks',
  touchpoints: 'pages.contacts.detail.tabs.touchpoints',
  notes: 'pages.contacts.detail.tabs.notes',
  projects: 'pages.contacts.detail.tabs.projects',
}

/** Resource label (Contact/Contacts) → i18n */
const RESOURCE_LABEL_KEYS: Record<string, string> = {
  contact: 'nav.contacts',
  contact_plural: 'pages.contacts.title',
  company: 'nav.companies',
  company_plural: 'pages.companies.title',
}

export function fieldLabelKey(field: FieldConfig): string | null {
  return FIELD_LABEL_KEYS[field.key] || null
}

export function localizeFieldLabel(field: FieldConfig, t: (k: string) => string): string {
  const key = FIELD_LABEL_KEYS[field.key]
  return key ? t(key) : field.label
}

export function localizeTabLabel(id: string, fallback: string, t: (k: string) => string): string {
  const key = TAB_LABEL_KEYS[id]
  return key ? t(key) : fallback
}

export function localizeResourceLabel(name: string, plural: boolean, fallback: string, t: (k: string) => string): string {
  const key = RESOURCE_LABEL_KEYS[plural ? `${name}_plural` : name]
  return key ? t(key) : fallback
}

/** Data-driven select option value (Client/Vendor/Active...) → i18n; falls back to raw value */
export function localizeOptionLabel(value: string | null | undefined, fallback: string, t: (k: string, o?: any) => string): string {
  if (!value) return fallback
  return t(`common.optionValues.${value}`, { defaultValue: fallback })
}

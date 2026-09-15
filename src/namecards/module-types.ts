// ═══════════════════════════════════════════════════════════
// module-types.ts — Shared TypeScript types for Name Card module
// ═══════════════════════════════════════════════════════════

export interface NameCardTag {
  label: string
  count: number
}

export interface NameCardTagDef {
  id: string
  label: string
  color?: string
  usage_count?: number
  created_at?: string
}

export interface NameCardFieldConfidence {
  name?: number
  email?: number
  phone?: number
  company?: number
  title?: number
  [key: string]: number | undefined
}

export interface DuplicateCandidate {
  contact_id: string
  reason?: string
}

export interface NameCardParsedData {
  name?: string
  company?: string
  title?: string
  email?: string
  phone?: string
  website?: string
}

export interface LinkedContact {
  id: string
  name: string
  company_name?: string
  job_title?: string
}

export interface NameCardRecord {
  id: string
  image_url?: string
  cropped_image_url?: string
  name?: string
  company?: string
  title?: string
  email?: string
  phone?: string
  tags?: string[]
  status?: 'processing' | 'done' | 'error'
  parsed_data?: NameCardParsedData
  field_confidence?: NameCardFieldConfidence
  duplicate_candidate?: DuplicateCandidate | null
  contact_id?: string | null
  contact?: LinkedContact | null
  created_at?: string
}

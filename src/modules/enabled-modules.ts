// ═══════════════════════════════════════════
//  Penguin CRM — Enabled Modules Registry
//  ═══════════════════════════════════════════
//  Tenant-level feature toggle for modules.
//  Fetched from backend DB (tenant_modules table)
//  via the /module-settings API endpoint.
//  ═══════════════════════════════════════════

import { apiClient, isAuthenticated } from '../lib/api'

/** All known module keys */
const KNOWN_MODULES = [
  'contacts',
  'companies',
  'tasks',
  'touchpoints',
  'projects',
  'sales',
  'shipping',
  'notes',
]

let enabledModules: string[] = [...KNOWN_MODULES]
let hasInitialised = false

async function loadFromApi(): Promise<void> {
  if (hasInitialised) return
  hasInitialised = true
  try {
    const settings = await apiClient.get<{ module_key: string; enabled: boolean }[]>('/api/v1/crm/module-settings')
    if (Array.isArray(settings) && settings.length > 0) {
      enabledModules = KNOWN_MODULES.filter(mk => {
        const s = settings.find(s => s.module_key === mk)
        // Default to enabled if no setting exists
        return s ? s.enabled : true
      })
    }
  } catch {
    // Fallback: all modules enabled
    enabledModules = [...KNOWN_MODULES]
  }
}

// Start loading immediately but don't block — skip when not authenticated
// (module-settings requires a valid JWT; calling it on the public login page
// produces a noisy 403 in the console)
if (typeof window !== 'undefined' && isAuthenticated()) {
  loadFromApi()
}

export function isModuleEnabled(name: string): boolean {
  return enabledModules.includes(name)
}

export function getEnabledModules(): string[] {
  return [...enabledModules]
}

/** Force reload from API (e.g. after toggling in Settings) */
export async function refreshModules(): Promise<void> {
  hasInitialised = false
  await loadFromApi()
}

export default enabledModules

// ═══════════════════════════════════════════
//  useEntity — fetch a single entity record (Detail Page V2)
//  Follows GenericDetailPage's fetch pattern: GET /api/v1/crm/<module>/<id>
//  ═══════════════════════════════════════════
import { useState, useEffect, useCallback } from 'react'
import { apiClient } from '../../lib/api'
import type { EntityRecord } from '../module-types'

// module → API path segment mapping
const MODULE_PATH: Record<string, string> = {
  company: 'companies',
  contact: 'contacts',
  project: 'projects',
  task: 'tasks',
  touchpoint: 'touchpoints',
}

export function useEntity(module: string, id: string) {
  const [entity, setEntity] = useState<EntityRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const path = MODULE_PATH[module] || module
      const res = await apiClient.get<EntityRecord>(`/api/v1/crm/${path}/${id}`)
      setEntity(res)
    } catch (e: any) {
      setError(e.detail || e.message || 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [module, id])

  useEffect(() => { refresh() }, [refresh])

  return { entity, loading, error, refresh }
}

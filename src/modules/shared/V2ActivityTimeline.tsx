import { useState, useEffect } from 'react'
import { UnifiedTimeline, type TimelineEvent } from './NexusDetailPageV2'
import { apiClient } from '../../lib/api'

interface ActivityItem {
  id: string
  entity_id?: string
  entity_type?: string
  action?: string
  description?: string
  created_at: string
}

interface Touchpoint {
  id: string
  title?: string
  type?: string
  description?: string
  company_id?: string
  contact_id?: string
  created_at: string
}

function timeAgo(d: string): string {
  if (!d) return ''
  const then = new Date(d).getTime()
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return '剛剛'
  if (mins < 60) return `${mins} 分鐘前`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} 小時前`
  return `${Math.floor(hrs / 24)} 天前`
}

const typeEmoji: Record<string, string> = {
  call: '📞', meeting: '🤝', email: '✉️', note: '📝', task: '✅', default: '📌',
}

/**
 * V2 timeline for Overview/Timeline tabs.
 * 用 UnifiedTimeline render → 冇 events 時自動顯示 .nx-empty-state（Bug #2 fix）。
 */
export function V2ActivityTimeline({ entityId, filterType }: {
  entityId: string
  filterType: 'company' | 'contact' | 'project' | 'task' | 'touchpoint'
}) {
  const [events, setEvents] = useState<TimelineEvent[]>([])

  useEffect(() => {
    let alive = true
    Promise.all([
      apiClient.get<{ items: ActivityItem[] }>('/api/v1/crm/activities?page_size=100').catch(() => ({ items: [] })),
      apiClient.get<{ items: Touchpoint[] }>('/api/v1/crm/touchpoints?limit=100').catch(() => ({ items: [] })),
    ]).then(([aRes, tpRes]) => {
      if (!alive) return
      const acts = (aRes.items || []).filter(a => a.entity_id === entityId)
      const tps = (tpRes.items || []).filter(tp => {
        if (filterType === 'company') return tp.company_id === entityId
        if (filterType === 'contact') return tp.contact_id === entityId
        return tp.company_id === entityId || tp.contact_id === entityId
      })
      const mapped: TimelineEvent[] = [
        ...acts.map(a => ({
          id: `a-${a.id}`, icon: '📝', title: a.action || '—', meta: timeAgo(a.created_at),
          body: a.description || undefined, sortKey: a.created_at,
        })),
        ...tps.map(tp => ({
          id: `tp-${tp.id}`, icon: typeEmoji[tp.type || ''] || typeEmoji.default, title: tp.title || '—',
          meta: timeAgo(tp.created_at), body: tp.description || undefined, sortKey: tp.created_at,
        })),
      ].sort((a, b) => new Date(b.sortKey).getTime() - new Date(a.sortKey).getTime())
      setEvents(mapped)
    })
    return () => { alive = false }
  }, [entityId, filterType])

  return <UnifiedTimeline events={events} />
}

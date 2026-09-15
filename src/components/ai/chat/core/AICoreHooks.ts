import { useCallback, useEffect, useState } from 'react'

/* ─────────────────────────────────────────────────────────────
   AICoreHooks — data hooks for tenant-level AI admin surfaces.
   All endpoints are tenant-scoped; no system access.
   ───────────────────────────────────────────────────────────── */

export interface AiAgentInfo {
  id: string
  key: string
  name: string
  description: string
  scope: string
}

export interface SecretarySettings {
  tone: string
  greeting_slots: { morning: string; afternoon: string; evening: string }
  work_hours: { start: string; end: string }
  lang_pref: string
}

export interface QuotaState {
  used: number
  limit: number
  periodLabel: string
  /** 'pro subscription' | 'free subscription'（2026-09-07 Terrence） */
  plan?: string
}

export interface ProviderHealth {
  provider: string
  is_byok: boolean
  status: string
  expires_in_days?: number
}

const DEFAULT_SECRETARY: SecretarySettings = {
  tone: 'friendly',
  greeting_slots: { morning: '早晨', afternoon: '午安', evening: '晚上好' },
  work_hours: { start: '09:00', end: '18:30' },
  lang_pref: 'zh-HK',
}

export function getGreeting(s: SecretarySettings): string {
  const hour = new Date().getHours()
  if (hour < 12) return s.greeting_slots.morning
  if (hour < 18) return s.greeting_slots.afternoon
  return s.greeting_slots.evening
}

export function isWithinWorkHours(s: SecretarySettings): boolean {
  const now = new Date()
  const [sh, sm] = (s.work_hours.start || '09:00').split(':').map(Number)
  const [eh, em] = (s.work_hours.end || '18:30').split(':').map(Number)
  const nowMin = now.getHours() * 60 + now.getMinutes()
  return nowMin >= sh * 60 + sm && nowMin <= eh * 60 + em
}

async function getJSON<T>(url: string): Promise<T | null> {
  try {
    // 2026-09-15 SAST：session 喺 httpOnly cookie，唔再手動加 Authorization
    const res = await fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'include' })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export function useAiAgents() {
  const [agents, setAgents] = useState<AiAgentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    const data = await getJSON<{ agents: AiAgentInfo[] }>('/api/v1/crm/ai/agents')
    setAgents(data?.agents ?? [])
    setLoading(false)
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  return { agents, loading, refresh }
}

export function useSecretarySettings() {
  const [settings, setSettings] = useState<SecretarySettings>(DEFAULT_SECRETARY)
  useEffect(() => {
    void (async () => {
      const data = await getJSON<any>('/api/v1/ai-secretary/settings')
      if (!data) return
      setSettings({
        tone: data.tone ?? DEFAULT_SECRETARY.tone,
        greeting_slots: {
          morning: data.greeting_slots?.morning ?? DEFAULT_SECRETARY.greeting_slots.morning,
          afternoon: data.greeting_slots?.afternoon ?? DEFAULT_SECRETARY.greeting_slots.afternoon,
          evening: data.greeting_slots?.evening ?? DEFAULT_SECRETARY.greeting_slots.evening,
        },
        work_hours: {
          start: data.work_start ?? DEFAULT_SECRETARY.work_hours.start,
          end: data.work_end ?? DEFAULT_SECRETARY.work_hours.end,
        },
        lang_pref: data.lang_pref ?? DEFAULT_SECRETARY.lang_pref,
      })
    })()
  }, [])
  return settings
}

export function useQuota() {
  const [quota, setQuota] = useState<QuotaState | null>(null)
  useEffect(() => {
    void (async () => {
      const data = await getJSON<any>('/api/v1/ai-secretary/llm-usage')
      if (!data) return
      const usage = data.usage ?? data
      setQuota({
        used: usage.total_tokens ?? usage.tokens_used ?? usage.used ?? 0,
        limit: usage.limit ?? usage.quota_limit ?? 0,
        periodLabel: usage.period ?? '本月',
        plan: usage.plan ?? data.plan,
      })
    })()
  }, [])
  return quota
}

export function useProviderHealth() {
  const [providers, setProviders] = useState<ProviderHealth[]>([])
  useEffect(() => {
    void (async () => {
      const data = await getJSON<{ providers: ProviderHealth[] }>('/api/v1/crm/ai/provider-health')
      setProviders(data?.providers ?? [])
    })()
  }, [])
  return providers
}

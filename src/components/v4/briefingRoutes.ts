/* ═══════════════════════════════════════════════════════════
   Briefing section → portal route map (DATA-DRIVEN extension point)

   The AI briefing content is shared with Telegram (same generated text).
   Portal rendering auto-applies: each `**section header**` maps to a page
   via this config — NOT hardcoded inside components.

   HOW TO EXTEND:
   - New section type → add a group here with zh + en patterns.
   - Headers arrive with emoji prefixes + （date）suffixes — normalization
     strips both before matching, so patterns are bare keywords.
   - Sections with no match (info-only, e.g. 天氣/新聞/交通/總結) stay plain
     text — listed in BRIEFING_INFO_SECTIONS to document intent.
   - Item-level fallback (strong signals only) catches LLM-freeform headers
     that drift from known patterns.
   ═══════════════════════════════════════════════════════════ */

export interface BriefingRouteGroup {
  route: string | null
  icon: string
  patterns: string[]
}

export const BRIEFING_ROUTE_MAP: BriefingRouteGroup[] = [
  {
    route: '/tasks',
    icon: 'tasks',
    patterns: ['任務', '優先', '未完', '到期', '死線', '提醒', 'todo', 'task', 'priority', 'overdue', 'deadline', 'reminder'],
  },
  {
    route: '/calendar',
    icon: 'calendar',
    patterns: ['行程', '會議', '活動', '預告', 'schedule', 'meeting', 'calendar', 'event', 'agenda'],
  },
  {
    route: '/contacts',
    icon: 'crm',
    patterns: ['crm', '客戶', '聯絡人', '生日', '人脈', 'lead', 'contact', 'customer', 'birthday', 'sentiment'],
  },
  {
    route: '/projects',
    icon: 'spark',
    patterns: ['項目', 'project'],
  },
  {
    route: '/team',
    icon: 'spark',
    patterns: ['團隊', 'team'],
  },
  {
    route: '/notifications',
    icon: 'spark',
    patterns: ['通知', 'notification'],
  },
]

/* Info-only sections — documented as intentionally non-clickable. */
export const BRIEFING_INFO_SECTIONS = [
  '天氣', 'weather',
  '新聞', 'news', '行業',
  '交通', '通勤', 'traffic', 'commute',
  '電郵', '郵件', '草稿', 'email', 'draft',
  '開支', '支出', 'expense',
  '總結', '回顧', '展望', 'summary', 'review', 'outlook', '其他', 'other',
]

const EMOJI_RE = /[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE0F}\u{2B00}-\u{2BFF}]/gu
const PAREN_RE = /（[^）]*）|\([^)]*\)/g

export function normalizeBriefingHeader(h: string): string {
  return h
    .replace(EMOJI_RE, '')
    .replace(PAREN_RE, '')
    .replace(/[\s:：]+/g, '')
    .trim()
    .toLowerCase()
}

export function sectionRoute(header: string): string | null {
  const n = normalizeBriefingHeader(header)
  if (!n) return null
  for (const g of BRIEFING_ROUTE_MAP) {
    if (g.patterns.some(p => n.includes(p))) return g.route
  }
  return null
}

export function sectionIcon(header: string): string {
  const n = normalizeBriefingHeader(header)
  for (const g of BRIEFING_ROUTE_MAP) {
    if (g.patterns.some(p => n.includes(p))) return g.icon
  }
  return 'spark'
}

/* Item-level fallback — strong signals only, used when the header itself
   has no route match (LLM-freeform headers that drift). */
const ITEM_SIGNALS: { route: string; patterns: string[] }[] = [
  { route: '/calendar', patterns: ['會議', 'meeting', 'teams', '📅', '📆'] },
  { route: '/tasks', patterns: ['死線', 'due', 'p1', 'p2', 'p3', '優先', '📚', '📖', '🖥', '⏰', '✅'] },
  { route: '/contacts', patterns: ['生日', 'birthday', '客戶'] },
]

export function sectionRouteWithItemFallback(header: string, itemText: string): string | null {
  const direct = sectionRoute(header)
  if (direct) return direct
  const item = itemText.toLowerCase()
  for (const s of ITEM_SIGNALS) {
    if (s.patterns.some(p => item.includes(p))) return s.route
  }
  return null
}

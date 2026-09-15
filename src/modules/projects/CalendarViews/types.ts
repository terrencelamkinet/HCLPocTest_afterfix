/** CalendarViews — shared types for the custom calendar system */

export type CalendarViewType = 'month' | 'week' | 'day' | 'deadline';

export interface CalendarEvent {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  event_type: string | null;
  start: string;
  end: string;
  is_all_day: boolean;
  color: string | null;
  location: string | null;
  project_name?: string;
  source?: string | null;
}

export interface CalendarEventFormatted {
  id: string;
  title: string;
  start: Date;
  end: Date;
  allDay: boolean;
  color: string;
  description: string | null;
  location: string | null;
  eventType: string | null;
  projectId: string;
  projectName?: string;
  source?: string | null;
}

export const TYPE_COLORS: Record<string, string> = {
  milestone: '#00693E',
  task: '#00B4D8',
  meeting: '#F4A261',
  reminder: '#E76F51',
};

/** Source label shown as a type badge for synced calendar events */
export const SOURCE_LABELS: Record<string, string> = {
  google_oauth: 'Google',
  ics: 'ICS',
  outlook: 'Outlook',
  manual: 'Manual',
};

export function formatEvents(events: CalendarEvent[]): CalendarEventFormatted[] {
  /* 2026-09-13 修（用戶報：月曆 event 排序變咗「晚到早」）：
     每個 view 本來各自 sort，但 mobile 嘅 MobileAgendaList / MobileAgendaView
     完全冇 sort → 直接照 API 原序出，而 touchpoints API 係 newest-first，
     所以月曆格同 agenda 名單變成晚 → 早。集中喺呢度排一次（早 → 晚），
     所有 view 自動跟同一個次序，唔使每個 view 各自記住做。 */
  return events
    .map((ev) => ({
    id: ev.id,
    title: ev.title,
    start: new Date(ev.start),
    end: new Date(ev.end || ev.start),
    allDay: ev.is_all_day,
    color: ev.color || TYPE_COLORS[ev.event_type || ''] || '#6B7280',
    description: ev.description,
    location: ev.location,
    eventType: ev.event_type,
    projectId: ev.project_id,
    projectName: ev.project_name,
    source: ev.source || null,
    }))
    .sort((a, b) => a.start.getTime() - b.start.getTime())
}

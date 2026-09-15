import { useState, useEffect, useCallback } from 'react';
import CalendarViews from './CalendarViews/CalendarViews';
import { formatEvents } from './CalendarViews/types';
import type { CalendarEvent } from './CalendarViews/types';
import { apiClient } from '../../lib/api';

export default function ProjectCalendarView() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await apiClient.get<any>('/api/v1/crm/projects?limit=500');
      const items: any[] = (resp as any)?.items || (resp as any) || [];
      const all: CalendarEvent[] = [];

      // Dedupe layer 2: title|start-time (minute precision). ICS + google_oauth
      // sync the same underlying event (e.g. Annual leave) with DIFFERENT
      // external_event_id, so ext-id dedupe can't catch it. Keep the first,
      // skip later duplicates with the same title + same start minute. Applies
      // to all pushed events (project-scoped, milestones, and merged NULL ones).
      const seenTitleStart = new Set<string>();
      const pushDeduped = (ev: CalendarEvent) => {
        const key = (ev.title || '(untitled)') + '|' + String(ev.start || '').slice(0, 16);
        if (seenTitleStart.has(key)) return;
        seenTitleStart.add(key);
        all.push(ev);
      };

      for (const proj of items) {
        try {
          const evs: CalendarEvent[] = await apiClient.get(`/api/v1/crm/projects/${proj.id}/calendar-events`);
          evs.forEach((ev) => pushDeduped({ ...ev, project_id: proj.id, project_name: proj.name }));
        } catch { /* skip */ }

        if (proj.start_date) {
          pushDeduped({
            id: `proj-start-${proj.id}`, project_id: proj.id,
            title: `${proj.name} starts`, description: null,
            event_type: 'milestone', start: proj.start_date, end: proj.start_date,
            is_all_day: true, color: '#00693E', location: null,
          });
        }
        if (proj.deadline) {
          pushDeduped({
            id: `proj-deadline-${proj.id}`, project_id: proj.id,
            title: `${proj.name} due`, description: null,
            event_type: 'milestone', start: proj.deadline, end: proj.deadline,
            is_all_day: true, color: '#E76F51', location: null,
          });
        }
      }

      // Dedupe key: external_event_id (ics + google_oauth sync the same underlying
      // events). Events without an external_event_id (manual ones) are never deduped.
      const seenExternal = new Set<string>();
      all.forEach((ev) => {
        const ext = (ev as any).external_event_id;
        if (ext) seenExternal.add(String(ext));
      });

      // Merge project_id=NULL events (e.g. Annual leave from shared ICS/Outlook)
      // that never appear via per-project fetches. Skip any that share an
      // external_event_id already present in the project-scoped list above.
      try {
        const allEvs: any = await apiClient.get('/api/v1/crm/calendar-events?limit=500');
        (Array.isArray(allEvs) ? allEvs : (allEvs?.items || [])).forEach((ev: any) => {
          const ext = ev?.external_event_id;
          if (ext && seenExternal.has(String(ext))) return;
          if (ext) seenExternal.add(String(ext));
          pushDeduped({
            id: ev.id,
            project_id: null,
            project_name: null,
            title: ev.title || '(untitled)',
            description: ev.description ?? null,
            event_type: ev.event_type ?? null,
            start: ev.start,
            end: ev.end || ev.start,
            is_all_day: !!ev.is_all_day,
            color: ev.color ?? null,
            location: ev.location ?? null,
            source: ev.source ?? null,
          } as unknown as CalendarEvent);
        });
      } catch { /* silent */ }

      setEvents(all);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);

  return (
    <CalendarViews
      events={formatEvents(events)}
      loading={loading}
      onRefresh={fetchEvents}
    />
  );
}

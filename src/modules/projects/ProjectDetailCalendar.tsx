import { useState, useEffect, useCallback } from 'react';
import CalendarViews from './CalendarViews/CalendarViews';
import { formatEvents } from './CalendarViews/types';
import type { CalendarEvent } from './CalendarViews/types';
import { apiClient } from '../../lib/api';
import type { ModuleConfig, EntityRecord } from '../module-types';

interface Props {
  entity: EntityRecord;
  moduleConfig: ModuleConfig;
  refresh: () => void;
}

export default function ProjectDetailCalendar({ entity }: Props) {
  const projectId = entity?.id;
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchEvents = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const list: CalendarEvent[] = await apiClient.get(`/api/v1/crm/projects/${projectId}/calendar-events`);
      setEvents(list.map((ev) => ({
        ...ev,
        start: new Date(ev.start).toISOString(),
        end: new Date(ev.end || ev.start).toISOString(),
      })));
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);

  return (
    <CalendarViews
      events={formatEvents(events)}
      loading={loading}
      onRefresh={fetchEvents}
    />
  );
}

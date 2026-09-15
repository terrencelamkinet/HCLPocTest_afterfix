import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../../components/SvcIcon';
import { formatDateKey, DAY_NAMES, isSameDay } from './calendar-utils';
import type { CalendarEventFormatted } from './types';
import { TYPE_COLORS } from './types';

interface GanttViewProps {
  events: CalendarEventFormatted[];
  date: Date;
  onDateChange: (d: Date) => void;
  onEventClick?: (ev: CalendarEventFormatted) => void;
}

/** Minimum number of days to show in the timeline */
const MIN_DAYS = 30;

/** Width per day column in pixels */
const DAY_WIDTH = 32;

/** Get event type color or fallback */
function getEventColor(ev: CalendarEventFormatted): string {
  if (ev.eventType && TYPE_COLORS[ev.eventType]) return TYPE_COLORS[ev.eventType];
  return ev.color;
}

interface ProjectTimeline {
  projectId: string;
  projectName: string;
  events: CalendarEventFormatted[];
  minStart: Date;
  maxEnd: Date;
}

export default function GanttView({ events, onEventClick }: GanttViewProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  // Compute project timelines
  const { projects, dayRange, dayHeaders } = useMemo(() => {
    if (events.length === 0) {
      return { projects: [] as ProjectTimeline[], dayRange: 0, dayHeaders: [] as Date[] };
    }

    // Find overall date range
    let minDate = new Date(events[0].start);
    let maxDate = new Date(events[0].end);
    for (const ev of events) {
      if (ev.start < minDate) minDate = new Date(ev.start);
      if (ev.end > maxDate) maxDate = new Date(ev.end);
    }

    // Ensure at least MIN_DAYS range
    const rangeMs = maxDate.getTime() - minDate.getTime();
    const rangeDays = Math.max(Math.ceil(rangeMs / (1000 * 60 * 60 * 24)), MIN_DAYS);
    maxDate = new Date(minDate.getTime() + rangeDays * 24 * 60 * 60 * 1000);

    // Build day headers
    const headers: Date[] = [];
    for (let i = 0; i < rangeDays; i++) {
      const d = new Date(minDate);
      d.setDate(minDate.getDate() + i);
      headers.push(d);
    }

    // Group events by projectId
    const projectMap = new Map<string, ProjectTimeline>();
    for (const ev of events) {
      const pid = ev.projectId || 'ungrouped';
      if (!projectMap.has(pid)) {
        projectMap.set(pid, {
          projectId: pid,
          projectName: ev.projectName || 'Uncategorized',
          events: [],
          minStart: new Date(ev.start),
          maxEnd: new Date(ev.end),
        });
      }
      const proj = projectMap.get(pid)!;
      proj.events.push(ev);
      if (ev.start < proj.minStart) proj.minStart = new Date(ev.start);
      if (ev.end > proj.maxEnd) proj.maxEnd = new Date(ev.end);
    }

    return {
      projects: Array.from(projectMap.values()),
      dayRange: rangeDays,
      dayHeaders: headers,
    };
  }, [events]);

  // Utility: days between two dates
  const daysBetween = (from: Date, to: Date): number => {
    return Math.round((to.getTime() - from.getTime()) / (1000 * 60 * 60 * 24));
  };

  if (events.length === 0) {
    return (
      <div>
        {/* Empty state */}
        <div className="calendar-empty">
          <SvcIcon name="calendar-days" />
          <p>No events for Gantt view</p>
        </div>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div>
        <div className="calendar-empty">
          <SvcIcon name="calendar-days" />
          <p>No project data available</p>
        </div>
      </div>
    );
  }

  const totalWidth = dayRange * DAY_WIDTH;

  return (
    <div className="gantt-panel">
      {/* Scrollable container */}
      <div className="gantt-scroll">
        <div className="gantt-container">
          {/* Y-axis label column + day headers */}
          <div className="gantt-header-row">
            {/* Y-axis label header */}
            <div className="gantt-label-header">
              Project
            </div>

            {/* Day header row (scrolls with content) */}
            <div className="gantt-day-headers" style={{ minWidth: totalWidth }}>
              {dayHeaders.map((d) => {
                const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                const isToday = isSameDay(d, new Date());
                return (
                  <div
                    key={formatDateKey(d)}
                    className={`gantt-day-cell${isWeekend ? ' weekend' : ''}${isToday ? ' today' : ''}`}
                    style={{ width: DAY_WIDTH }}
                  >
                    <div className="dw">{(() => {
                      try { return new Intl.DateTimeFormat(locale, { weekday: 'narrow' }).format(d) }
                      catch { return DAY_NAMES[d.getDay()].charAt(0) }
                    })()}</div>
                    <div className="dd">{d.getDate()}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Project rows */}
          {projects.map((proj) => {
            const projectStartOffset = daysBetween(dayHeaders[0], proj.minStart);
            const projectDuration = Math.max(daysBetween(proj.minStart, proj.maxEnd), 1);

            return (
              <div key={proj.projectId} className="gantt-row">
                {/* Project name */}
                <div className="gantt-row-label">
                  <span className="truncate">{proj.projectName}</span>
                </div>

                {/* Timeline area */}
                <div className="gantt-timeline" style={{ minWidth: totalWidth }}>
                  {/* Background grid lines (every day) */}
                  {dayHeaders.map((d) => (
                    <div
                      key={`grid-${formatDateKey(d)}`}
                      className="gantt-grid-line"
                      style={{ width: DAY_WIDTH }}
                    />
                  ))}

                  {/* Real-time "now" vertical line on today's column */}
                  {(() => {
                    const todayIdx = dayHeaders.findIndex((d) => isSameDay(d, new Date()));
                    if (todayIdx === -1) return null;
                    return (
                      <div
                        className="gantt-today-line"
                        style={{ left: todayIdx * DAY_WIDTH + DAY_WIDTH / 2 }}
                        title="Now"
                      />
                    );
                  })()}

                  {/* Project bar — from min start to max end */}
                  <div
                    className="gantt-project-bar"
                    style={{
                      left: projectStartOffset * DAY_WIDTH,
                      width: projectDuration * DAY_WIDTH,
                      minWidth: DAY_WIDTH,
                    }}
                    title={`${proj.projectName}: ${proj.events.length} events`}
                  />

                  {/* Individual event bars within the project */}
                  {proj.events.map((ev) => {
                    const evStartOffset = daysBetween(dayHeaders[0], ev.start);
                    const evDuration = Math.max(daysBetween(ev.start, ev.end), 0.5);
                    const color = getEventColor(ev);
                    const showTitle = evDuration >= 2;

                    return (
                      <div
                        key={ev.id}
                        className={`gantt-event-bar${onEventClick ? ' clickable' : ''}`}
                        style={{
                          left: evStartOffset * DAY_WIDTH,
                          width: evDuration * DAY_WIDTH,
                          backgroundColor: color,
                          minWidth: showTitle ? undefined : DAY_WIDTH * 0.5,
                        }}
                        title={`${ev.title}\n${ev.start.toLocaleDateString()} – ${ev.end.toLocaleDateString()}`}
                        onClick={onEventClick ? () => onEventClick(ev) : undefined}
                        role={onEventClick ? 'button' : undefined}
                      >
                        {showTitle && (
                          <span className="gantt-event-title">{ev.title}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="gantt-legend">
        {Object.entries(TYPE_COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-1.5">
            <div
              className="w-2.5 h-2.5 rounded"
              style={{ backgroundColor: color }}
            />
            <span className="capitalize">{key}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

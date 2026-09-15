import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  getMonthGrid,
  DAY_NAMES,
  formatDateKey,
  isEventOnDay,
  isSameDay,
} from './calendar-utils';
import type { CalendarEventFormatted } from './types';
import { TYPE_COLORS } from './types';

interface MonthViewProps {
  events: CalendarEventFormatted[];
  date: Date;
  onDateChange: (d: Date) => void;
  onEventClick?: (ev: CalendarEventFormatted) => void;
  onMoreClick?: (events: CalendarEventFormatted[], date: Date) => void;
  onCreate?: (d: Date) => void;
}

const MAX_EVENTS_PER_CELL = 3;
const MAX_DOTS = 6;

export default function MonthView({ events, date, onDateChange, onEventClick, onMoreClick, onCreate }: MonthViewProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  const year = date.getFullYear();
  const month = date.getMonth();
  const grid = useMemo(() => getMonthGrid(year, month), [year, month]);

  const todayRef = useMemo(() => new Date(), []);

  // Locale-aware weekday names (e.g. 日/一/二… for zh, Sun/Mon for en)
  const dayNames = useMemo(() => {
    try {
      return DAY_NAMES.map((_, idx) =>
        new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2026, 0, 4 + idx)))
    } catch {
      return DAY_NAMES
    }
  }, [locale])

  // Group events by date key — a multi-day event (e.g. Annual leave 8/24-26)
  // is added to EVERY day it spans (not just its start day). Within each day,
  // events are sorted ascending by start time (earliest start first).
  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEventFormatted[]>();
    for (const ev of events) {
      // add to every day the event spans
      const dStart = new Date(ev.start.getFullYear(), ev.start.getMonth(), ev.start.getDate());
      const dEnd = new Date(ev.end.getFullYear(), ev.end.getMonth(), ev.end.getDate());
      for (let d = new Date(dStart); d.getTime() <= dEnd.getTime(); d.setDate(d.getDate() + 1)) {
        if (!isEventOnDay(ev.start, ev.end, d)) continue;
        const key = formatDateKey(d);
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(ev);
      }
    }
    // sort each day's events ascending by start time
    for (const arr of map.values()) {
      arr.sort((a, b) => a.start.getTime() - b.start.getTime());
    }
    return map;
  }, [events]);

  return (
    <div>
      {/* ── Calendar Grid ── */}
      <div className="month-calendar">
        {/* Day names header */}
        <div className="month-header">
          {dayNames.map((name) => (
            <div key={name} className="month-day-name">
              {name}
            </div>
          ))}
        </div>

        {/* Day cells */}
        <div className="month-grid">
          {grid.map((week, weekIdx) =>
            week.map((day, dayIdx) => {
              if (day === null) {
                return (
                  <div
                    key={`empty-${weekIdx}-${dayIdx}`}
                    className="month-cell empty"
                  />
                );
              }

              const cellDate = new Date(year, month, day);
              const dateKey = formatDateKey(cellDate);
              const dayEvents = eventsByDay.get(dateKey) || [];
              const isCellToday = isSameDay(cellDate, todayRef);

              return (
                <div
                  key={`day-${day}`}
                  className={`month-cell${isCellToday ? ' today' : ''}`}
                  onClick={() => onDateChange(cellDate)}
                  onDoubleClick={(e) => { e.stopPropagation(); onCreate && onCreate(cellDate); }}
                >
                  <div className="month-date">{day}</div>

                  {/* Dot indicators (visible on mobile via CSS) */}
                  <div className="month-dots">
                    {dayEvents.slice(0, MAX_DOTS).map((ev) => (
                      <div
                        key={ev.id}
                        className="month-dot"
                        style={{ backgroundColor: ev.color || '#6B7280' }}
                      />
                    ))}
                    {dayEvents.length > MAX_DOTS && (
                      <span className="month-dot-more">+{dayEvents.length - MAX_DOTS}</span>
                    )}
                  </div>

                  {/* Event blocks (visible on desktop via CSS) */}
                  {dayEvents.slice(0, MAX_EVENTS_PER_CELL).map((ev) => (
                    <div
                      key={ev.id}
                      className={`month-event${onEventClick ? ' clickable' : ''}`}
                      style={{ background: `${ev.color}22`, color: ev.color, borderLeft: `2.5px solid ${ev.color}` }}
                      title={ev.title}
                      onClick={onEventClick ? (e) => { e.stopPropagation(); onEventClick(ev); } : undefined}
                      role={onEventClick ? 'button' : undefined}
                    >
                      {ev.allDay ? '' : `${ev.start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} `}{ev.title}
                    </div>
                  ))}
                  {dayEvents.length > MAX_EVENTS_PER_CELL && onMoreClick && (
                    <div
                      className="month-more"
                      role="button"
                      tabIndex={0}
                      onClick={(e) => { e.stopPropagation(); onMoreClick(dayEvents, cellDate); }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation();
                          onMoreClick(dayEvents, cellDate);
                        }
                      }}
                    >
                      +{dayEvents.length - MAX_EVENTS_PER_CELL} more
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="month-legend">
        {Object.entries(TYPE_COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-1.5">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="capitalize">{key}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

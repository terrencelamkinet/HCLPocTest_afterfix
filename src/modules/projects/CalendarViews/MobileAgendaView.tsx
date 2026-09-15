import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  formatMonthYear,
  formatDayHeader,
  formatDateKey,
  isSameDay,
  isToday,
} from './calendar-utils';
import type { CalendarEventFormatted } from './types';
import { TYPE_COLORS } from './types';

/* ── Shared helpers ── */

function formatTime(ev: CalendarEventFormatted, locale: string = 'en'): string {
  if (ev.allDay) return locale.startsWith('zh') ? '全天' : 'All day';
  const startStr = ev.start.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  const endStr = ev.end.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  return `${startStr} – ${endStr}`;
}

function eventColor(ev: CalendarEventFormatted): string {
  if (ev.color) return ev.color;
  return ev.eventType && TYPE_COLORS[ev.eventType] ? TYPE_COLORS[ev.eventType] : '#6B7280';
}

/* ── MobileAgendaList — Apple HIG style event list for a given date ── */

interface MobileAgendaListProps {
  events: CalendarEventFormatted[];
  date: Date;
  onEventClick?: (ev: CalendarEventFormatted) => void;
}

export function MobileAgendaList({ events, date, onEventClick }: MobileAgendaListProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  const dayEvents = useMemo(
    () => events.filter((ev) => isSameDay(ev.start, date)),
    [events, date],
  );

  return (
    <div className="mobile-agenda-list">
      {/* Liquid glass sticky header */}
      <div className="ma-list-header">
        <h2>{formatDayHeader(date, locale)}</h2>
      </div>

      <div className="ma-list-body">
        {dayEvents.length === 0 ? (
          <div className="ma-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <p>No events</p>
          </div>
        ) : (
          dayEvents.map((ev) => (
            <div
              key={ev.id}
              className={`ma-card${onEventClick ? ' clickable' : ''}`}
              onClick={onEventClick ? () => onEventClick(ev) : undefined}
              role={onEventClick ? 'button' : undefined}
            >
              <div
                className="ma-dot"
                style={{ backgroundColor: eventColor(ev) }}
              />
              <div className="ma-info">
                <div className="ma-title">{ev.title}</div>
                <div className="ma-meta">{formatTime(ev, locale)}</div>
                {ev.location && (
                  <div className="ma-location">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 12, height: 12 }}>
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                    {ev.location}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ── Full MobileAgendaView — date strip + event list ── */

interface MobileAgendaViewProps {
  events: CalendarEventFormatted[];
  date: Date;
  onDateChange: (d: Date) => void;
  onEventClick?: (ev: CalendarEventFormatted) => void;
}

export default function MobileAgendaView({ events, date, onDateChange, onEventClick }: MobileAgendaViewProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  const [selectedDate, setSelectedDate] = useState<Date>(date);
  const stripRef = useRef<HTMLDivElement>(null);

  const weekDates = useMemo(() => {
    const today = new Date();
    const days: Date[] = [];
    for (let i = -3; i <= 3; i++) {
      const d = new Date(today);
      d.setDate(today.getDate() + i);
      days.push(d);
    }
    return days;
  }, []);

  useEffect(() => {
    if (stripRef.current) {
      const activeEl = stripRef.current.querySelector('.mobile-agenda-date.active') as HTMLElement | null;
      if (activeEl) {
        activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      }
    }
  }, []);

  const handleDateSelect = useCallback(
    (d: Date) => {
      setSelectedDate(d);
      onDateChange(d);
    },
    [onDateChange],
  );

  return (
    <div className="mobile-agenda">
      <div className="mobile-agenda-strip">
        <div className="mobile-agenda-header">{formatMonthYear(selectedDate, locale)}</div>
        <div className="mobile-agenda-dates" ref={stripRef}>
          {weekDates.map((d) => {
            const dayName = d.toLocaleDateString(locale, { weekday: 'short' }).slice(0, 3);
            const dayNum = d.getDate();
            const active = isSameDay(d, selectedDate);
            const cellToday = isToday(d);
            return (
              <button
                key={formatDateKey(d)}
                className={`mobile-agenda-date${active ? ' active' : ''}${cellToday && !active ? ' today' : ''}`}
                onClick={() => handleDateSelect(d)}
              >
                <span className="m-date-day">{dayName}</span>
                <span className="m-date-num">{dayNum}</span>
              </button>
            );
          })}
        </div>
      </div>
      <MobileAgendaList events={events} date={selectedDate} onEventClick={onEventClick} />
    </div>
  );
}

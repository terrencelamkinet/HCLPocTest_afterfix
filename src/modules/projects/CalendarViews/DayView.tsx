import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../../components/SvcIcon';
import {
  getHourSlots,
  isSameDay,
  isEventOnDay,
  formatDayHeader,
} from './calendar-utils';
import type { CalendarEventFormatted } from './types';
import { TYPE_COLORS } from './types';

interface DayViewProps {
  events: CalendarEventFormatted[];
  date: Date;
  onDateChange: (d: Date) => void;
  onEventClick?: (ev: CalendarEventFormatted) => void;
  /** Optional counter — when it changes, re-scroll to the current-time line (real-time focus). */
  focusSignal?: number;
  onCreate?: (d: Date) => void;
}

const HOUR_HEIGHT = 74; // px per hour row — matches design03
const TOTAL_HEIGHT = 24 * HOUR_HEIGHT; // 1776px

/** Convert a Date to minutes since midnight */
function minutesSinceMidnight(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

/** Compute top offset (px) and height (px) for a time-based event */
function computeEventPosition(start: Date, end: Date, day?: Date): { top: number; height: number } {
  let s = start;
  let e = end;
  if (day) {
    const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate());
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayStart.getDate() + 1);
    const d0 = dayStart.getTime();
    if (s.getTime() < d0) s = dayStart;
    if (e.getTime() > dayEnd.getTime()) e = dayEnd;
  }
  const startMin = Math.max(0, minutesSinceMidnight(s));
  const endMin = Math.min(24 * 60, Math.max(startMin + 15, minutesSinceMidnight(e)));
  const top = (startMin / (24 * 60)) * TOTAL_HEIGHT;
  const height = ((endMin - startMin) / (24 * 60)) * TOTAL_HEIGHT;
  return { top, height };
}

/** Map event type/color to a severity class (ev-done, ev-high, ev-medium, ev-low) */
function getEventSeverityClass(ev: CalendarEventFormatted): string {
  const t = (ev.eventType || '').toLowerCase();
  const c = ev.color?.toLowerCase() || '';
  if (t === 'done' || t === 'completed' || t === 'reminder') return 'ev-done';
  if (t === 'high' || t === 'milestone') return 'ev-high';
  if (t === 'medium' || t === 'meeting') return 'ev-medium';
  if (t === 'low' || t === 'task') return 'ev-low';
  if (c.includes('00b4') || c.includes('f4a2')) return 'ev-medium';
  if (c.includes('e76f') || c.includes('0069')) return 'ev-high';
  if (c.includes('3f8a') || c.includes('6b72')) return 'ev-low';
  return 'ev-medium';
}

/** Format an event's status label */
function getEventStatus(ev: CalendarEventFormatted): string {
  const t = (ev.eventType || '').toLowerCase();
  if (t === 'done' || t === 'completed') return 'Done';
  if (t === 'milestone') return 'Milestone';
  if (t === 'meeting') return 'Meeting';
  if (t === 'task') return 'Task';
  if (t === 'reminder') return 'Reminder';
  if (t === 'high') return 'High';
  if (t === 'medium') return 'Medium';
  if (t === 'low') return 'Low';
  return t || 'Event';
}

export default function DayView({ events, date, onDateChange, onEventClick, focusSignal, onCreate }: DayViewProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  const [now, setNow] = useState<Date>(new Date());
  const scrollRef = useRef<HTMLDivElement>(null);

  const hourSlots = useMemo(() => getHourSlots(), []);
  const todayRef = useMemo(() => new Date(), []);

  // Scroll to the current time line on mount and whenever "Today/Now" is pressed.
  const scrollToNow = useCallback(() => {
    if (scrollRef.current) {
      const currentHour = new Date().getHours();
      scrollRef.current.scrollTop = Math.max(0, currentHour * HOUR_HEIGHT - 120);
    }
  }, []);

  useEffect(() => { scrollToNow(); }, [scrollToNow]);
  useEffect(() => { if (focusSignal) scrollToNow(); }, [focusSignal, scrollToNow]);

  // Update current time every minute
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const handlePrev = useCallback(() => {
    const prev = new Date(date);
    prev.setDate(date.getDate() - 1);
    onDateChange(prev);
  }, [onDateChange, date]);

  const handleNext = useCallback(() => {
    const next = new Date(date);
    next.setDate(date.getDate() + 1);
    onDateChange(next);
  }, [onDateChange, date]);

  const handleToday = useCallback(() => {
    onDateChange(new Date());
  }, [onDateChange]);

  // Separate all-day events from time-specific events, scoped to the selected day.
  // Multi-day events render on every day they span (isEventOnDay), so cross-
  // day events like multi-day annual leave show on each covered date.
  const { allDayEvents, timedEvents } = useMemo(() => {
    const allDay: CalendarEventFormatted[] = [];
    const timed: CalendarEventFormatted[] = [];
    for (const ev of events) {
      if (!isEventOnDay(ev.start, ev.end, date)) continue;
      if (ev.allDay) {
        allDay.push(ev);
      } else {
        timed.push(ev);
      }
    }
    return { allDayEvents: allDay, timedEvents: timed };
  }, [events, date]);

  // Current time line position
  const nowPercent = useMemo(() => {
    const totalMin = now.getHours() * 60 + now.getMinutes();
    return (totalMin / (24 * 60)) * 100;
  }, [now]);

  const isDateToday = isSameDay(date, todayRef);

  if (events.length === 0) {
    return (
      <div>
        {/* Navigation */}
        <div className="flex items-center justify-between mb-4 max-sm:flex-col max-sm:items-start flex-wrap gap-2">
          <div className="flex items-center gap-1">
            <button
              onClick={handlePrev}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-surface-offset)] transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
            >
              <SvcIcon name="chevron-left" className="w-4 h-4" />
            </button>
            <span className="text-sm font-semibold text-[var(--color-text)] px-3 min-w-[180px] text-center select-none">
              {formatDayHeader(date)}
            </span>
            <button
              onClick={handleNext}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-surface-offset)] transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
            >
              <SvcIcon name="chevron-right" className="w-4 h-4" />
            </button>
            <button
              onClick={handleToday}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary-highlight)] transition-colors ml-2 min-h-[36px]"
            >
              Today
            </button>
          </div>
        </div>

        {/* Empty state */}
        <div className="calendar-empty">
          <SvcIcon name="calendar-days" />
          <p>No events</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Navigation */}
      <div className="flex items-center justify-between mb-4 max-sm:flex-col max-sm:items-start flex-wrap gap-2">
        <div className="flex items-center gap-1">
          <button
            onClick={handlePrev}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-surface-offset)] transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
          >
            <SvcIcon name="chevron-left" className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold text-[var(--color-text)] px-3 min-w-[180px] text-center select-none">
            {formatDayHeader(date)}
          </span>
          <button
            onClick={handleNext}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-surface-offset)] transition-colors min-h-[36px] min-w-[36px] flex items-center justify-center"
          >
            <SvcIcon name="chevron-right" className="w-4 h-4" />
          </button>
          <button
            onClick={handleToday}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary-highlight)] transition-colors ml-2 min-h-[36px]"
          >
            Today
          </button>
        </div>
      </div>

      {/* Day view panel */}
      <div className="day-panel">
        {/* Day header */}
        <div className={`day-header${isDateToday ? ' today' : ''}`}>
          <div className="day-name">
            {date.toLocaleDateString(locale, { weekday: 'long' })}
          </div>
          <div className="day-date">
            {date.getDate()}
          </div>
        </div>

        {/* All-day events bar */}
        {allDayEvents.length > 0 && (
          <div className="day-allday-bar" style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {allDayEvents.map((ev) => (
              <div
                key={ev.id}
                className={`event-block ev-done${onEventClick ? ' ev-clickable' : ''}`}
                style={{
                  position: 'relative',
                  height: 'auto',
                  minHeight: 22,
                  padding: '2px 6px',
                  fontSize: '10px',
                  left: 'auto',
                  right: 'auto',
                  flexShrink: 0,
                  maxWidth: 200,
                }}
                title={ev.title}
                onClick={onEventClick ? () => onEventClick(ev) : undefined}
                role={onEventClick ? 'button' : undefined}
                onDoubleClick={(e) => e.stopPropagation()}
              >
                <div className="e-title" style={{ fontSize: '10px' }}>{ev.title}</div>
              </div>
            ))}
          </div>
        )}

        {/* Time grid (scrollable) */}
        <div ref={scrollRef} className="day-grid-scroll" style={{ maxHeight: '800px' }}>
          <div className="day-grid" style={{ minHeight: TOTAL_HEIGHT }}
            onDoubleClick={(e) => { e.stopPropagation(); onCreate && onCreate(date); }}>
            {/* Hour rows */}
            {hourSlots.map((slot) => (
              <div key={slot} className="day-hour-row">
                <span className="day-hour-label">{slot}</span>
              </div>
            ))}

            {/* Current time red line */}
            {isDateToday && (
              <div className="now-line" style={{ top: `${nowPercent}%` }}>
                <div className="now-dot" />
                <div className="now-label">
                  {now.getHours().toString().padStart(2, '0')}:{now.getMinutes().toString().padStart(2, '0')}
                </div>
              </div>
            )}

            {/* Positioned events */}
            {timedEvents.map((ev) => {
              const { top, height } = computeEventPosition(ev.start, ev.end, date);
              const sevClass = getEventSeverityClass(ev);
              const status = getEventStatus(ev);
              const timeStr = `${ev.start.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })} – ${ev.end.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}`;
              return (
                <div
                  key={ev.id}
                  className={`event-block ${sevClass}${onEventClick ? ' ev-clickable' : ''}`}
                  style={{ top: `${top}px`, height: `${height}px`, left: '60px', right: '8px' }}
                  title={`${ev.title}\n${timeStr}`}
                  onClick={onEventClick ? () => onEventClick(ev) : undefined}
                  role={onEventClick ? 'button' : undefined}
                  onDoubleClick={(e) => e.stopPropagation()}
                >
                  <div className="e-status">{status}</div>
                  <div className="e-title">{ev.title}</div>
                  {height >= 30 && (
                    <div className="e-sub">{timeStr}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 mt-4 text-xs text-[var(--color-text-muted)]">
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

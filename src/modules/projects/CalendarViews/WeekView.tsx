import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../../components/SvcIcon';
import {
  getWeekDatesMonFri,
  getWeekDates,
  getHourSlots,
  isSameDay,
  isEventOnDay,
  formatDateKey,
} from './calendar-utils';
import type { CalendarEventFormatted, CalendarViewType } from './types';
import { TYPE_COLORS } from './types';

interface WeekViewProps {
  events: CalendarEventFormatted[];
  date: Date;
  onDateChange: (d: Date) => void;
  viewType?: CalendarViewType;
  onViewChange?: (v: CalendarViewType) => void;
  showWeekends?: boolean;
  onEventClick?: (ev: CalendarEventFormatted) => void;
  /** Optional counter — when it changes, re-scroll to the current-time line (real-time focus). */
  focusSignal?: number;
  onCreate?: (d: Date) => void;
  onToggleWeekends?: () => void;
}

const HOUR_HEIGHT = 74;
const TOTAL_HEIGHT = 24 * HOUR_HEIGHT;
const ALL_DAY_EVENT_H = 22; // px per all-day event in the all-day strip row

/** Convert a Date to minutes since midnight */
function minutesSinceMidnight(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

/**
 * Compute top offset (px) and height (px) for a time-based event on a given
 * calendar day. Clamps the event's start/end into that day's [00:00,24:00)
 * range so multi-day events render correctly on every day they span (e.g.
 * annual leave: day 2 starts at 0:00, last day ends at 24:00).
 */
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
  // heuristic: dark/bright colors → high, muted → done, green → low, warm → medium
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

const SHORT_DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const FULL_DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Locale-aware weekday short names: weekdays 0-6 (Sun=0). */
function weekdayNames(locale: string, count: number, startIdx: number): string[] {
  try {
    return Array.from({ length: count }, (_, i) =>
      new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2026, 0, 4 + startIdx + i)))
  } catch {
    return (startIdx === 0 ? FULL_DAY_NAMES : SHORT_DAY_NAMES).slice(0, count)
  }
}

export default function WeekView({ events, date, onDateChange, showWeekends, onEventClick, focusSignal, onCreate, onToggleWeekends }: WeekViewProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  const [now, setNow] = useState<Date>(new Date());
  const scrollRef = useRef<HTMLDivElement>(null);

  const weekDates = useMemo(() => showWeekends ? getWeekDates(date) : getWeekDatesMonFri(date), [date, showWeekends]);
  const dayNames = useMemo(() => showWeekends
    ? weekdayNames(locale, 7, 0)
    : weekdayNames(locale, 5, 1), [showWeekends, locale]);
  const numDays = weekDates.length;
  const gridCols = `52px repeat(${numDays},1fr)`;
  const hourSlots = useMemo(() => getHourSlots(), []);

  // Scroll to the current time line on mount and whenever "Today/Now" is pressed.
  const scrollToNow = useCallback(() => {
    if (scrollRef.current) {
      const currentHour = new Date().getHours();
      scrollRef.current.scrollTop = Math.max(0, currentHour * HOUR_HEIGHT - 160);
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
    prev.setDate(date.getDate() - 7);
    onDateChange(prev);
  }, [onDateChange, date]);

  const handleNext = useCallback(() => {
    const next = new Date(date);
    next.setDate(date.getDate() + 7);
    onDateChange(next);
  }, [onDateChange, date]);

  // Separate all-day events from time-specific events
  const { allDayEvents, timedEvents } = useMemo(() => {
    const allDay: CalendarEventFormatted[] = [];
    const timed: CalendarEventFormatted[] = [];
    for (const ev of events) {
      if (ev.allDay) {
        allDay.push(ev);
      } else {
        timed.push(ev);
      }
    }
    return { allDayEvents: allDay, timedEvents: timed };
  }, [events]);

  // Group timed events by start day, then every day they span
  const timedSpanByDay = useMemo(() => {
    const map = new Map<string, CalendarEventFormatted[]>();
    for (const ev of timedEvents) {
      for (const wd of weekDates) {
        if (isEventOnDay(ev.start, ev.end, wd)) {
          const key = formatDateKey(wd);
          if (!map.has(key)) map.set(key, []);
          map.get(key)!.push(ev);
        }
      }
    }
    return map;
  }, [timedEvents, weekDates]);

  const allDaySpanByDay = useMemo(() => {
    const map = new Map<string, CalendarEventFormatted[]>();
    for (const ev of allDayEvents) {
      for (const wd of weekDates) {
        if (isEventOnDay(ev.start, ev.end, wd)) {
          const key = formatDateKey(wd);
          if (!map.has(key)) map.set(key, []);
          map.get(key)!.push(ev);
        }
      }
    }
    return map;
  }, [allDayEvents, weekDates]);

  // All-day strip row height = tallest day's count × per-event height (min 22px).
  const allDayRowHeight = useMemo(() => {
    const max = Math.max(0, ...weekDates.map(wd => (allDaySpanByDay.get(formatDateKey(wd)) || []).length));
    return Math.max(ALL_DAY_EVENT_H, max * ALL_DAY_EVENT_H + 2);
  }, [allDaySpanByDay, weekDates]);

  // Current time line position
  const nowMinutes = useMemo(() => {
    return now.getHours() * 60 + now.getMinutes();
  }, [now]);

  const nowTop = (nowMinutes / (24 * 60)) * TOTAL_HEIGHT;

  return (
    <div className="week-panel" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-divider)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
      {/* ── Toolbar ── */}
      <div className="week-toolbar">
        <h2>This Week</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div className="week-range-nav">
            <button onClick={handlePrev} aria-label="Previous">
              <SvcIcon name="chevron-left" className="w-3.5 h-3.5" />
            </button>
            <button onClick={handleNext} aria-label="Next">
              <SvcIcon name="chevron-right" className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="range-toggle">
            <button
              className={showWeekends ? 'active' : ''}
              onClick={onToggleWeekends}
              title="Toggle weekends"
            >
              {showWeekends ? 'Weekends: On' : 'Weekends: Off'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Week Grid ── */}
      <div className="week-grid-scroll">
        <div className="week-grid" style={{ gridTemplateColumns: gridCols, minWidth: 820 + (numDays - 5) * 160 }}>
          {/* Row 1: empty corner (col 1) + day headers (cols 2-6) */}
          <div />

          {/* Day column headers — Mon–Fri */}
          {weekDates.map((wd, idx) => {
            const isColToday = isSameDay(wd, now);
            return (
              <div key={`head-${formatDateKey(wd)}`} className={`day-col-head${isColToday ? ' today' : ''}`}>
                {dayNames[idx]}
                <b>{wd.getDate()}</b>
              </div>
            );
          })}

          {/* Row 2 (NEW): All-day strip — corner spacer + per-day all-day events (vertically stacked, no overlap) */}
          <div className="time-gutter all-day-gutter" />
          {weekDates.map((wd) => {
            const colKey = formatDateKey(wd);
            const dayAllDay = allDaySpanByDay.get(colKey) || [];
            return (
              <div
                key={`allday-${colKey}`}
                className="day-all-day"
                style={{ height: allDayRowHeight }}
                onDoubleClick={(e) => { e.stopPropagation(); onCreate && onCreate(wd); }}
              >
                {dayAllDay.map((ev, i) => (
                  <div
                    key={ev.id}
                    className={`event-block all-day-event${onEventClick ? ' ev-clickable' : ''}`}
                    style={{
                      top: i * ALL_DAY_EVENT_H,        // vertical stacking, no overlap
                      height: ALL_DAY_EVENT_H - 2,
                      left: 3, right: 3,
                      position: 'absolute',
                      background: `${ev.color}22`,
                      color: ev.color,
                      borderLeft: `2.5px solid ${ev.color}`,
                      padding: '2px 6px',
                      fontSize: '10px',
                      zIndex: 3,
                    }}
                    title={ev.title}
                    onClick={onEventClick ? () => onEventClick(ev) : undefined}
                    role={onEventClick ? 'button' : undefined}
                    onDoubleClick={(e) => e.stopPropagation()}
                  >
                    <div className="e-title" style={{ fontSize: '10px', color: ev.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ev.title}</div>
                  </div>
                ))}
              </div>
            );
          })}

          {/* Time gutter — empty corner */}
          <div className="time-gutter">
            {hourSlots.map((slot) => (
              <div key={slot} className="time-cell">
                {slot}
              </div>
            ))}
          </div>

          {/* Day columns */}
          {weekDates.map((wd) => {
            const colKey = formatDateKey(wd);
            const isColToday = isSameDay(wd, now);
            const dayTimed = timedSpanByDay.get(colKey) || [];

            return (
              <div key={`col-${colKey}`} className="day-col" style={{ height: TOTAL_HEIGHT }}
                onDoubleClick={(e) => { e.stopPropagation(); onCreate && onCreate(wd); }}>
                {/* Hour grid lines */}
                {hourSlots.map((slot) => (
                  <div key={`hl-${colKey}-${slot}`} className="hour-line" />
                ))}

                {/* Today's current time line */}
                {isColToday && (
                  <div className="now-line" style={{ top: `${nowTop}px` }}>
                    <div className="now-dot" />
                    <div className="now-label">
                      {now.getHours().toString().padStart(2, '0')}:{now.getMinutes().toString().padStart(2, '0')}
                    </div>
                  </div>
                )}

                {/* Positioned events */}
                {dayTimed.map((ev) => {
                  const { top, height } = computeEventPosition(ev.start, ev.end, wd);
                  const sevClass = getEventSeverityClass(ev);
                  const status = getEventStatus(ev);
                  const timeStr = `${ev.start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${ev.end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
                  return (
                    <div
                      key={ev.id}
                      className={`event-block ${sevClass}${onEventClick ? ' ev-clickable' : ''}`}
                      style={{ top: `${top}px`, height: `${height}px` }}
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
            );
          })}
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="month-legend" style={{ padding: '12px 18px', borderTop: '1px solid var(--color-divider)' }}>
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

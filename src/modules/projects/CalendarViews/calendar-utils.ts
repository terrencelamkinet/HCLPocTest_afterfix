/**
 * Calendar utility functions — pure functions only, no React dependencies.
 * Uses only native Date. TypeScript strict.
 */

export const DAY_NAMES: string[] = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export const MONTH_NAMES: string[] = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Returns the number of days in a given month.
 * @param year — full year (e.g. 2026)
 * @param month — 0-indexed month (0 = January)
 */
export function getDaysInMonth(year: number, month: number): number {
  // Day 0 of the next month = last day of the current month
  return new Date(year, month + 1, 0).getDate();
}

/**
 * Returns a 2D array representing a month grid.
 * Each sub-array (row) is a week with exactly 7 elements.
 * Days outside the month are null. Null padding fills the first/last row as needed.
 * @param year — full year (e.g. 2026)
 * @param month — 0-indexed month (0 = January)
 */
export function getMonthGrid(year: number, month: number): (number | null)[][] {
  const daysInMonth = getDaysInMonth(year, month);
  const firstDayOfWeek = new Date(year, month, 1).getDay(); // 0 = Sunday
  const rows: (number | null)[][] = [];
  let currentRow: (number | null)[] = [];

  // Leading null padding
  for (let i = 0; i < firstDayOfWeek; i++) {
    currentRow.push(null);
  }

  // Fill days of the month
  for (let day = 1; day <= daysInMonth; day++) {
    currentRow.push(day);
    if (currentRow.length === 7) {
      rows.push(currentRow);
      currentRow = [];
    }
  }

  // Trailing null padding for the last row
  if (currentRow.length > 0) {
    while (currentRow.length < 7) {
      currentRow.push(null);
    }
    rows.push(currentRow);
  }

  // Edge case: if the month is completely empty (shouldn't happen, but safe)
  if (rows.length === 0) {
    rows.push([null, null, null, null, null, null, null]);
  }

  return rows;
}

/**
 * Returns an array of 24 hour slot strings in "HH:00" format.
 */
export function getHourSlots(): string[] {
  const slots: string[] = [];
  for (let h = 0; h < 24; h++) {
    slots.push(`${h.toString().padStart(2, '0')}:00`);
  }
  return slots;
}

/**
 * Returns an array of 7 Date objects representing the week (Sunday–Saturday)
 * that contains the given date.
 */
export function getWeekDates(date: Date): Date[] {
  const dayOfWeek = date.getDay(); // 0 = Sunday
  const sunday = new Date(date);
  sunday.setDate(date.getDate() - dayOfWeek);

  const week: Date[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(sunday);
    d.setDate(sunday.getDate() + i);
    week.push(d);
  }
  return week;
}

/**
 * Compares two Date objects by year, month, and day.
 * Returns true if both represent the same calendar date.
 */
export function isSameDay(d1: Date, d2: Date): boolean {
  return (
    d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate()
  );
}

/**
 * True if the event [start, end) overlaps the given date (any part of it).
 * Used so multi-day events render on every day they span, not just the
 * start day.
 */
export function isEventOnDay(start: Date, end: Date, day: Date): boolean {
  const dStart = new Date(day.getFullYear(), day.getMonth(), day.getDate());
  // event's own end exclusive
  const evEnd = new Date(end);
  const dAfter = new Date(dStart);
  dAfter.setDate(dStart.getDate() + 1);
  return evEnd.getTime() > dStart.getTime() && start.getTime() < dAfter.getTime();
}

/**
 * Returns true if the given date is today (local time).
 */
export function isToday(d: Date): boolean {
  return isSameDay(d, new Date());
}

/**
 * Formats a date as "Month YYYY", e.g. "March 2026" / "2026年3月".
 */
export function formatMonthYear(date: Date, locale: string = 'en'): string {
  try {
    return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(date)
  } catch {
    return `${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`
  }
}

/**
 * Formats a date as "Dow, Mon DD", e.g. "Sun, Mar 15".
 */
export function formatDayHeader(date: Date, locale: string = 'en'): string {
  try {
    const wk = new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date)
    const mo = new Intl.DateTimeFormat(locale, { month: 'short' }).format(date)
    return `${wk}, ${mo} ${date.getDate()}`
  } catch {
    const dayName = DAY_NAMES[date.getDay()];
    const monthAbbr = MONTH_NAMES[date.getMonth()].slice(0, 3);
    const dayNum = date.getDate();
    return `${dayName}, ${monthAbbr} ${dayNum}`;
  }
}

/**
 * Formats a date as "YYYY-MM-DD", e.g. "2026-03-15".
 */
export function formatDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = (date.getMonth() + 1).toString().padStart(2, '0');
  const day = date.getDate().toString().padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Returns an array of 5 Date objects representing Mon–Fri of the week
 * that contains the given date.
 */
export function getWeekDatesMonFri(date: Date): Date[] {
  const dayOfWeek = date.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
  const monday = new Date(date);
  // If Sunday (0), go back 6 days. If Saturday (6), go back 5 days. Otherwise go back (dayOfWeek - 1)
  const diff = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
  monday.setDate(date.getDate() + diff);

  const week: Date[] = [];
  for (let i = 0; i < 5; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    week.push(d);
  }
  return week;
}

import { useEffect, useState } from 'react';

export interface GreetingSlot {
  key: 'morning' | 'afternoon' | 'evening' | 'lateNight';
  emoji: string;
  start: string; // "HH:MM" 24h
}

export const DEFAULT_GREETING_SLOTS: GreetingSlot[] = [
  { key: 'morning', emoji: '🌅', start: '05:00' },
  { key: 'afternoon', emoji: '☀️', start: '12:00' },
  { key: 'evening', emoji: '🌆', start: '18:00' },
  { key: 'lateNight', emoji: '🌙', start: '23:00' },
];

const STORAGE_KEY = 'nexus-greeting-slots';

export function loadGreetingSlots(): GreetingSlot[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_GREETING_SLOTS;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length !== 4) return DEFAULT_GREETING_SLOTS;
    const valid = DEFAULT_GREETING_SLOTS.every((d, i) => parsed[i] && parsed[i].key === d.key && /^\d{2}:\d{2}$/.test(parsed[i].start));
    return valid ? parsed : DEFAULT_GREETING_SLOTS;
  } catch {
    return DEFAULT_GREETING_SLOTS;
  }
}

export function saveGreetingSlots(slots: GreetingSlot[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(slots));
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

/** Current greeting slot based on local time + user-configured start times. */
export function getCurrentGreeting(now: Date = new Date(), slots: GreetingSlot[] = loadGreetingSlots()): GreetingSlot {
  const mins = now.getHours() * 60 + now.getMinutes();
  const sorted = [...slots].sort((a, b) => toMinutes(a.start) - toMinutes(b.start));
  // Last slot that has started; if none started yet (before first slot), wrap to last (late night).
  let current = sorted[sorted.length - 1];
  for (const s of sorted) {
    if (mins >= toMinutes(s.start)) current = s;
    else break;
  }
  return current;
}

export function useGreeting(): GreetingSlot {
  const [slot, setSlot] = useState<GreetingSlot>(() => getCurrentGreeting());

  useEffect(() => {
    const check = () => {
      const next = getCurrentGreeting();
      setSlot(prev => (prev.key === next.key ? prev : next));
    };
    // Re-evaluate every minute so greeting flips at the configured boundary.
    const t = setInterval(check, 60_000);
    // Also react to slot config changes from other tabs.
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) check();
    };
    window.addEventListener('storage', onStorage);
    return () => {
      clearInterval(t);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  return slot;
}

// ─────────────────────────────────────────────────────────────
// Working hours — task/project notifications are confined to
// this window (per-user, stored locally).
// ─────────────────────────────────────────────────────────────
export interface WorkingHours {
  start: string; // "HH:MM" 24h
  end: string;   // "HH:MM" 24h
}

export const DEFAULT_WORKING_HOURS: WorkingHours = { start: '09:00', end: '18:00' };

const WORKING_HOURS_KEY = 'nexus-working-hours';

export function loadWorkingHours(): WorkingHours {
  try {
    const raw = localStorage.getItem(WORKING_HOURS_KEY);
    if (!raw) return DEFAULT_WORKING_HOURS;
    const parsed = JSON.parse(raw);
    if (parsed && /^\d{2}:\d{2}$/.test(parsed.start) && /^\d{2}:\d{2}$/.test(parsed.end)) {
      return { start: parsed.start, end: parsed.end };
    }
    return DEFAULT_WORKING_HOURS;
  } catch {
    return DEFAULT_WORKING_HOURS;
  }
}

export function saveWorkingHours(hours: WorkingHours) {
  localStorage.setItem(WORKING_HOURS_KEY, JSON.stringify(hours));
}

/** True when `now` falls inside [start, end). Handles overnight windows (end < start). */
export function isInWorkingHours(now: Date = new Date(), hours: WorkingHours = loadWorkingHours()): boolean {
  const mins = now.getHours() * 60 + now.getMinutes();
  const s = toMinutes(hours.start);
  const e = toMinutes(hours.end);
  if (s === e) return false; // degenerate: no working hours
  return s < e ? mins >= s && mins < e : mins >= s || mins < e;
}

export function useWorkingHours(): WorkingHours {
  const [hours, setHours] = useState<WorkingHours>(() => loadWorkingHours());
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === WORKING_HOURS_KEY) setHours(loadWorkingHours());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  return hours;
}

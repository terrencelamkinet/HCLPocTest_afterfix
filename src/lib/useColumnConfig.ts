import { useState, useEffect, useCallback, useRef } from 'react';

export interface ColDef {
  key: string;
  label: string;
  minWidth?: number;
  defaultWidth?: number;
}

interface ColConfig {
  order: string[];
  widths: Record<string, number>;
}

const STORAGE_KEY = 'contacts-col-config';

const DEFAULTS: ColDef[] = [
  { key: 'name', label: 'Name', minWidth: 100, defaultWidth: 180 },
  { key: 'company', label: 'Company', minWidth: 80, defaultWidth: 140 },
  { key: 'email', label: 'Email', minWidth: 100, defaultWidth: 200 },
  { key: 'status', label: 'Status', minWidth: 60, defaultWidth: 90 },
  { key: 'last_touch', label: 'Last Touch', minWidth: 80, defaultWidth: 120 },
];

function load(): ColConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultConfig();
    const parsed = JSON.parse(raw);
    const allKeys = new Set(DEFAULTS.map(d => d.key));
    const missing = [...allKeys].filter(k => !parsed.order?.includes(k));
    if (missing.length > 0) {
      parsed.order = [...(parsed.order || []), ...missing];
      for (const d of DEFAULTS) {
        if (!parsed.widths[d.key]) parsed.widths[d.key] = d.defaultWidth!;
      }
    }
    return parsed;
  } catch {
    return defaultConfig();
  }
}

function defaultConfig(): ColConfig {
  return {
    order: DEFAULTS.map(d => d.key),
    widths: Object.fromEntries(DEFAULTS.map(d => [d.key, d.defaultWidth!])),
  };
}

function save(config: ColConfig) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)); } catch {}
}

export default function useColumnConfig() {
  const [config, setConfig] = useState<ColConfig>(load);
  const dragCol = useRef<string | null>(null);
  const resizeCol = useRef<string | null>(null);
  const resizeStart = useRef({ x: 0, w: 0 });

  useEffect(() => { save(config); }, [config]);

  const getColDef = useCallback((key: string) =>
    DEFAULTS.find(d => d.key === key)!, []);

  const getVisible = useCallback(() =>
    config.order.map(k => ({ ...getColDef(k), width: config.widths[k] || 0 })),
    [config, getColDef]);

  const moveColumn = useCallback((from: number, to: number) => {
    setConfig(prev => {
      const order = [...prev.order];
      const [moved] = order.splice(from, 1);
      order.splice(to, 0, moved);
      return { ...prev, order };
    });
  }, []);

  const resetColumns = useCallback(() => {
    setConfig(defaultConfig());
  }, []);

  // ---- Desktop drag reorder ----
  const onDragStart = useCallback((e: React.DragEvent, key: string) => {
    dragCol.current = key;
    e.dataTransfer.effectAllowed = 'move';
    (e.currentTarget as HTMLElement).style.opacity = '.5';
  }, []);

  const onDragOver = useCallback((e: React.DragEvent, key: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!dragCol.current || dragCol.current === key) return;
    const from = config.order.indexOf(dragCol.current);
    const to = config.order.indexOf(key);
    if (from === -1 || to === -1 || from === to) return;
    moveColumn(from, to);
    dragCol.current = key;
  }, [config.order, moveColumn]);

  const onDragEnd = useCallback(() => {
    dragCol.current = null;
  }, []);

  // ---- Desktop resize ----
  const onResizeStart = useCallback((e: React.MouseEvent, key: string) => {
    e.preventDefault();
    resizeCol.current = key;
    resizeStart.current = { x: e.clientX, w: config.widths[key] || 0 };
    const handler = (ev: MouseEvent) => {
      if (!resizeCol.current) return;
      const dx = ev.clientX - resizeStart.current.x;
      const def = DEFAULTS.find(d => d.key === resizeCol.current);
      const newW = Math.max(def?.minWidth || 60, resizeStart.current.w + dx);
      setConfig(prev => ({
        ...prev,
        widths: { ...prev.widths, [resizeCol.current!]: newW },
      }));
    };
    const cleanup = () => {
      resizeCol.current = null;
      window.removeEventListener('mousemove', handler);
      window.removeEventListener('mouseup', cleanup);
    };
    window.addEventListener('mousemove', handler);
    window.addEventListener('mouseup', cleanup);
  }, [config.widths]);

  // ---- Mobile bottom sheet ----
  const [mobileOpen, setMobileOpen] = useState(false);
  const openMobile = useCallback(() => setMobileOpen(true), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const moveMobile = useCallback((index: number, dir: -1 | 1) => {
    const to = index + dir;
    if (to < 0 || to >= config.order.length) return;
    moveColumn(index, to);
  }, [config.order.length, moveColumn]);

  return {
    config,
    getColDef,
    getVisible,
    moveColumn,
    resetColumns,
    onDragStart, onDragOver, onDragEnd,
    onResizeStart,
    mobileOpen, openMobile, closeMobile, moveMobile,
  };
}

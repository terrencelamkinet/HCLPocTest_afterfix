import { useState, useRef, useCallback, type ReactNode } from 'react';
import SvcIcon from '../components/SvcIcon';

interface Props<T extends string> {
  items: T[];
  onChange: (items: T[]) => void;
  children: (id: T) => ReactNode;
}

const MOVE_THRESHOLD = 6; // px before drag starts

export default function DnDSortableGroup<T extends string>({ items, onChange, children }: Props<T>) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const state = useRef<{
    dragId: string;
    el: HTMLElement;
    ghost: HTMLElement;
    startX: number;
    startY: number;
    moved: boolean;
    pointerId: number;
  } | null>(null);

  const commit = useCallback((fromIdx: number, toIdx: number) => {
    if (!state.current || fromIdx === toIdx) return;
    const next = [...items];
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, state.current.dragId as T);
    onChange(next);
  }, [items, onChange]);

  const getDropIndex = useCallback((cx: number, cy: number): number => {
    if (!containerRef.current) return 0;
    const els = containerRef.current.querySelectorAll<HTMLElement>('.dnd-item');
    let best = 0;
    let bestDist = Infinity;
    // Find closest item center
    els.forEach((el, i) => {
      const r = el.getBoundingClientRect();
      const d = Math.hypot(cx - (r.left + r.width / 2), cy - (r.top + r.height / 2));
      if (d < bestDist) { bestDist = d; best = i; }
    });
    // Then determine if we should go before or after based on vertical midpoint
    const target = els[best];
    if (!target) return 0;
    const r = target.getBoundingClientRect();
    // Also check adjacent gap distances
    let gapIdx = cy < r.top + r.height / 2 ? best : best + 1;
    // Clamp
    return Math.max(0, Math.min(gapIdx, items.length - 1));
  }, [items]);

  const cleanup = useCallback(() => {
    if (state.current) {
      try { document.body.removeChild(state.current.ghost); } catch {}
      state.current = null;
    }
    setDragging(null);
    setOverIdx(null);
  }, []);

  const onPointerMove = useCallback((ev: PointerEvent) => {
    if (!state.current) return;
    const s = state.current;
    const dx = ev.clientX - s.startX;
    const dy = ev.clientY - s.startY;

    if (!s.moved && Math.abs(dx) + Math.abs(dy) < MOVE_THRESHOLD) return;

    if (!s.moved) {
      s.moved = true;
      setDragging(s.dragId);
      // Create ghost on first move
      const ghost = s.el.cloneNode(true) as HTMLElement;
      const r = s.el.getBoundingClientRect();
      ghost.style.position = 'fixed';
      ghost.style.pointerEvents = 'none';
      ghost.style.zIndex = '9999';
      ghost.style.opacity = '0.85';
      ghost.style.width = `${r.width}px`;
      ghost.style.transform = 'scale(1.02)';
      ghost.style.boxShadow = '0 8px 24px rgba(0,0,0,.15)';
      ghost.style.borderRadius = 'var(--radius-lg)';
      ghost.style.overflow = 'hidden';
      ghost.style.left = `${r.left}px`;
      ghost.style.top = `${r.top}px`;
      document.body.appendChild(ghost);
      s.ghost = ghost;
      s.el.style.opacity = '0.35';
    }

    if (s.ghost) {
      s.ghost.style.transform = `translate(${dx}px, ${dy}px) scale(1.02)`;
    }

    const idx = getDropIndex(ev.clientX, ev.clientY);
    setOverIdx(idx);
  }, [getDropIndex]);

  const onPointerUp = useCallback((ev: PointerEvent) => {
    document.removeEventListener('pointermove', onPointerMove);
    document.removeEventListener('pointerup', onPointerUp);
    if (state.current && state.current.moved && state.current.ghost) {
      const fromIdx = items.indexOf(state.current.dragId as T);
      const idx = getDropIndex(ev.clientX, ev.clientY);
      if (fromIdx !== -1) commit(fromIdx, idx);
      if (state.current.el) state.current.el.style.opacity = '';
    }
    cleanup();
  }, [items, commit, getDropIndex, cleanup, onPointerMove]);

  const handlePointerDown = useCallback((e: React.PointerEvent, id: string) => {
    const el = (e.target as HTMLElement).closest('.dnd-item') as HTMLElement;
    if (!el) return;

    state.current = {
      dragId: id,
      el,
      ghost: null!,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
      pointerId: e.pointerId,
    };

    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
  }, [onPointerMove, onPointerUp]);

  return (
    <div className="dnd-group" ref={containerRef}>
      {items.map((id, idx) => (
        <div
          key={id}
          className={`dnd-item${dragging === id ? ' dragging' : ''}${overIdx === idx ? ' drop-target' : ''}`}
        >
          <div className="dnd-handle" onPointerDown={e => handlePointerDown(e, id)}>
            <SvcIcon name="grip-vertical" size={14} />
          </div>
          <div className="dnd-body">
            {children(id)}
          </div>
        </div>
      ))}
    </div>
  );
}

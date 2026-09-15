import { useEffect } from 'react';

/**
 * Close a popup/modal/drawer with the Escape key.
 * Listener is only active while `active` is true (default: always active).
 * Use for ALL overlay components so ESC behaves consistently across the app.
 */
export function useEscapeKey(onClose: () => void, active = true): void {
  useEffect(() => {
    if (!active) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, active]);
}

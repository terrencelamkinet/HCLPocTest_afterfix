import { useEffect, useState } from 'react'

/**
 * Detects whether a physical/hardware keyboard is likely attached,
 * even on a touch-primary device (iPad + Magic Keyboard / Smart
 * Keyboard, Android tablet/phone + Bluetooth keyboard).
 *
 * Heuristic (there is no official W3C API for this):
 * 1. If the device reports no touch support at all → definitely hardware kb.
 * 2. If a `keydown` fires for a key that virtual/software keyboards
 *    never dispatch (e.g. Escape, Tab, Arrow keys, or any keydown
 *    while no on-screen keyboard/input animation is in flight) →
 *    treat as hardware keyboard connected for the rest of the session.
 * 3. Resets to false if the viewport resize pattern matches an
 *    on-screen keyboard opening (visualViewport height shrinks a lot
 *    right after a keydown) — rare false-positive guard.
 */
export function useHardwareKeyboard(): boolean {
  const [hasHardwareKeyboard, setHasHardwareKeyboard] = useState(false)

  useEffect(() => {
    const noTouch = !('ontouchstart' in window) && navigator.maxTouchPoints === 0
    if (noTouch) { setHasHardwareKeyboard(true); return }

    const HARDWARE_ONLY_KEYS = ['Escape', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Meta', 'Control']

    const onKeydown = (e: KeyboardEvent) => {
      if (HARDWARE_ONLY_KEYS.includes(e.key) || e.metaKey || e.ctrlKey) {
        setHasHardwareKeyboard(true)
      }
    }
    window.addEventListener('keydown', onKeydown)
    return () => window.removeEventListener('keydown', onKeydown)
  }, [])

  return hasHardwareKeyboard
}

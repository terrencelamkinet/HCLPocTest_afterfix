import { useState, useLayoutEffect } from 'react'

/**
 * useMobile — detects viewport width and provides showFullTab state for stacked mobile layouts.
 *
 * Returns:
 *   isMobile:      boolean (true when window < 768px)
 *   showFullTab:   string | null — currently shown full tab id, or null for stacked view
 *   setShowFullTab: setter — pass a tab id to show that tab in full, or null to return to stacked
 *
 * Usage in a detail page:
 *   const { isMobile, showFullTab, setShowFullTab } = useMobile()
 *
 *   if (isMobile && showFullTab) {
 *     // render full single-tab view
 *   } else if (isMobile) {
 *     // render stacked sections with MobileSection wrappers
 *   } else {
 *     // render desktop tab layout
 *   }
 */
export function useMobile() {
  const [isMobile, setIsMobile] = useState(false)
  const [showFullTab, setShowFullTab] = useState<string | null>(null)

  useLayoutEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  return { isMobile, showFullTab, setShowFullTab }
}

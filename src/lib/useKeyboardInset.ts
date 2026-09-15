import { useEffect } from 'react'
import { bottomOffsetFor, keyboardInset } from './keyboardInset'

/**
 * 將「軟鍵盤佔咗幾高」寫入 CSS 變數（2026-09-13 mobile Notes P0-4）。
 *
 * 用 CSS 變數而唔用 React state：keyboard resize 事件喺 iOS 上會高頻 fire，
 * 每次 setState = 全頁 re-render。寫 `--kb-inset` 令 CSS 自己調整，
 * 底部固定元素（accessory bar／sheet）唔需要 re-render 就跟住鍵盤升。
 *
 * 用法：CSS `bottom: calc(var(--kb-inset, 0px) + env(safe-area-inset-bottom, 0px))`
 */
export const KB_INSET_VAR = '--kb-inset'

export function useKeyboardInsetVar(): void {
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return // 舊瀏覽器：唔支援就唔玩，唔好拋錯（fallback = 現有 fixed offset）

    const root = document.documentElement
    let raf = 0

    const apply = () => {
      raf = 0
      const layoutHeight = root.clientHeight || window.innerHeight
      const inset = keyboardInset({ height: vv.height, offsetTop: vv.offsetTop }, layoutHeight)
      root.style.setProperty(KB_INSET_VAR, `${bottomOffsetFor(inset, 0)}px`)
      root.dataset.kb = inset > 0 ? '1' : '0'
    }

    const schedule = () => {
      if (raf) return
      raf = window.requestAnimationFrame(apply)
    }

    apply()
    vv.addEventListener('resize', schedule)
    vv.addEventListener('scroll', schedule)
    return () => {
      vv.removeEventListener('resize', schedule)
      vv.removeEventListener('scroll', schedule)
      if (raf) window.cancelAnimationFrame(raf)
      root.style.removeProperty(KB_INSET_VAR)
      delete root.dataset.kb
    }
  }, [])
}

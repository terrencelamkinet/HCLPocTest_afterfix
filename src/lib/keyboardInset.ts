/**
 * 鍵盤感知（2026-09-13 mobile Notes P0-4）。
 *
 * iOS／Android 彈起軟鍵盤時：`100vh`／`100dvh` 唔會變（layout viewport 唔動），
 * 只有 `window.visualViewport.height` 縮。所以底部固定嘅 toolbar／sheet 一定要
 * 靠 visualViewport 計出「鍵盤佔咗幾多」，唔可以靠 fixed offset。
 */
export interface ViewportLike {
  height: number
  offsetTop: number
}

/**
 * 鍵盤（或其他被瀏覽器 chrome 蓋住嘅高度）佔咗幾多 px。
 * @param vv           window.visualViewport（舊瀏覽器可能係 undefined）
 * @param layoutHeight documentElement.clientHeight（layout viewport 高度）
 */
export function keyboardInset(vv: ViewportLike | null | undefined, layoutHeight: number): number {
  if (!vv || !Number.isFinite(layoutHeight) || layoutHeight <= 0) return 0
  const visible = vv.height + (Number.isFinite(vv.offsetTop) ? vv.offsetTop : 0)
  const inset = layoutHeight - visible
  // 細過 80px 當係瀏覽器 chrome 抖動（唔係鍵盤），避免 toolbar 無故跳
  return inset >= 80 ? Math.round(inset) : 0
}

/** 由 keyboard inset 決定底部固定元素嘅 bottom 值。 */
export function bottomOffsetFor(inset: number, safeAreaBottom: number, gap = 8): number {
  const gapValue = inset > 0 ? 0 : gap // 鍵盤升起時貼住鍵盤，唔好再留 gap
  return Math.round(Math.max(0, inset) + Math.max(0, safeAreaBottom) + gapValue)
}

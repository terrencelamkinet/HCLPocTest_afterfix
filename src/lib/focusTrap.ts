/**
 * Focus trap 嘅純邏輯（2026-09-13 mobile Notes P0-2 / P1）。
 *
 * 抽出嚟做 pure function 係為咗 unit test：DOM 層嘅 focus trap 要靠真瀏覽器
 * （Playwright）驗，但繞圈／邊界行為一定要有 test 鎖住。
 */

/**
 * 下一個應該 focus 嘅 index。
 * @param key     鍵盤事件 key（只有 Tab 會繞圈；其他一律 null = 唔理）
 * @param index   目前 focus 喺 focusable 清單嘅 index（-1 = 未入清單，例如 sheet 容器）
 * @param count   sheet 內 focusable 元素總數
 * @param shift   有冇撳 Shift
 */
export function nextFocusIndex(
  key: string,
  index: number,
  count: number,
  shift: boolean,
): number | null {
  if (key !== 'Tab') return null;
  if (count <= 0) return null; // 冇 focusable → 交返畀瀏覽器（唔好 preventDefault）
  if (index < 0) return shift ? count - 1 : 0; // 由 sheet 容器開始 Tab
  if (shift) return index === 0 ? count - 1 : index - 1;
  return index === count - 1 ? 0 : index + 1;
}

/** 呢個 index 係唔係一定要攔截（繞圈）？ */
export function shouldTrapFocus(
  key: string,
  index: number,
  count: number,
  shift: boolean,
): boolean {
  const next = nextFocusIndex(key, index, count, shift);
  if (next === null) return false;
  if (index < 0) return true;
  // 只有喺頭／尾再 Tab（會跳出 sheet）才需要攔
  return shift ? index === 0 : index === count - 1;
}

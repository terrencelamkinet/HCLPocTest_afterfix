import { describe, expect, it } from 'vitest';
import { nextFocusIndex, shouldTrapFocus } from './focusTrap';

describe('focus trap 繞圈（P1 focus management）', () => {
  it('向前 Tab：中間前進，最後一個繞返第一個', () => {
    expect(nextFocusIndex('Tab', 0, 3, false)).toBe(1);
    expect(nextFocusIndex('Tab', 1, 3, false)).toBe(2);
    expect(nextFocusIndex('Tab', 2, 3, false)).toBe(0);
  });

  it('向後 Shift+Tab：中間後退，第一個繞返最後', () => {
    expect(nextFocusIndex('Tab', 2, 3, true)).toBe(1);
    expect(nextFocusIndex('Tab', 1, 3, true)).toBe(0);
    expect(nextFocusIndex('Tab', 0, 3, true)).toBe(2);
  });

  it('由 sheet 容器（index -1）開始：Tab → 第一個，Shift+Tab → 最後', () => {
    expect(nextFocusIndex('Tab', -1, 3, false)).toBe(0);
    expect(nextFocusIndex('Tab', -1, 3, true)).toBe(2);
  });

  it('冇 focusable 元素 → null（唔攔截，交返畀瀏覽器）', () => {
    expect(nextFocusIndex('Tab', 0, 0, false)).toBeNull();
    expect(shouldTrapFocus('Tab', 0, 0, false)).toBe(false);
  });

  it('非 Tab 鍵（Escape／Enter）唔屬於 focus trap', () => {
    expect(nextFocusIndex('Escape', 0, 3, false)).toBeNull();
    expect(shouldTrapFocus('Enter', 1, 3, false)).toBe(false);
  });

  it('只有喺頭／尾才需要 preventDefault（中間唔應該攔）', () => {
    expect(shouldTrapFocus('Tab', 2, 3, false)).toBe(true);
    expect(shouldTrapFocus('Tab', 1, 3, false)).toBe(false);
    expect(shouldTrapFocus('Tab', 0, 3, true)).toBe(true);
    expect(shouldTrapFocus('Tab', 1, 3, true)).toBe(false);
  });

  it('單一元素：Tab 同 Shift+Tab 都留喺自己', () => {
    expect(nextFocusIndex('Tab', 0, 1, false)).toBe(0);
    expect(nextFocusIndex('Tab', 0, 1, true)).toBe(0);
  });
});

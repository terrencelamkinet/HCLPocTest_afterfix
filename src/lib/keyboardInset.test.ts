import { describe, expect, it } from 'vitest';
import { bottomOffsetFor, keyboardInset } from './keyboardInset';

describe('P0-4 鍵盤感知定位', () => {
  it('冇鍵盤（visual viewport = layout viewport）→ inset 0', () => {
    expect(keyboardInset({ height: 800, offsetTop: 0 }, 800)).toBe(0);
  });

  it('軟鍵盤彈起 300px → inset 300', () => {
    expect(keyboardInset({ height: 500, offsetTop: 0 }, 800)).toBe(300);
  });

  it('iOS 捲動時 offsetTop 要一齊計（唔可以只睇 height）', () => {
    // layout 800、visual top 60、height 440 → 底部被蓋 300
    expect(keyboardInset({ height: 440, offsetTop: 60 }, 800)).toBe(300);
  });

  it('visualViewport 未支援（undefined）→ 當冇鍵盤，唔會拋錯', () => {
    expect(keyboardInset(undefined, 800)).toBe(0);
    expect(keyboardInset(null, 800)).toBe(0);
  });

  it('瀏覽器 chrome 抖動（<80px）唔當鍵盤，避免 toolbar 無故跳', () => {
    expect(keyboardInset({ height: 760, offsetTop: 0 }, 800)).toBe(0);
    expect(keyboardInset({ height: 700, offsetTop: 0 }, 800)).toBe(100);
  });

  it('layoutHeight 無效值唔會產生負數 / NaN', () => {
    expect(keyboardInset({ height: 500, offsetTop: 0 }, 0)).toBe(0);
    expect(keyboardInset({ height: 500, offsetTop: 0 }, Number.NaN)).toBe(0);
  });

  it('bottom offset：鍵盤升起時貼住鍵盤（唔再加 gap），否則留 gap + safe area', () => {
    expect(bottomOffsetFor(0, 34, 8)).toBe(42);
    expect(bottomOffsetFor(300, 34, 8)).toBe(334);
    expect(bottomOffsetFor(-5, -5, 8)).toBe(8);
  });
});

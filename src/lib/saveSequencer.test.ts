import { describe, expect, it } from 'vitest';
import {
  SAVE_STATUS_FALLBACK,
  SAVE_STATUS_KEY,
  createSaveSequencer,
  saveStatusAfter,
} from './saveSequencer';

describe('P0-6 同一篇筆記嘅儲存唔會亂序', () => {
  it('兩個 request 疊住：第一個變 stale，第二個係最新', () => {
    const seq = createSaveSequencer();
    const g1 = seq.next('note-1');
    const g2 = seq.next('note-1');
    expect(g1).toBe(1);
    expect(g2).toBe(2);
    expect(seq.isLatest('note-1', g1)).toBe(false);
    expect(seq.isLatest('note-1', g2)).toBe(true);
  });

  it('舊 request 嘅回應（包括 error）一律掉棄', () => {
    const seq = createSaveSequencer();
    const stale = seq.next('n1');
    seq.next('n1');
    // 舊 request 返嚟：唔可以寫 version、唔可以蓋 UI 狀態
    expect(seq.isLatest('n1', stale)).toBe(false);
  });

  it('唔同 note 各自一條序列（互不影響）', () => {
    const seq = createSaveSequencer();
    const a = seq.next('a');
    const b = seq.next('b');
    expect(seq.isLatest('a', a)).toBe(true);
    expect(seq.isLatest('b', b)).toBe(true);
  });

  it('順序：舊 request 返嚟之後，最新嘅仍然有效', () => {
    const seq = createSaveSequencer();
    seq.next('n1');
    const latest = seq.next('n1');
    expect(seq.isLatest('n1', latest)).toBe(true);
    expect(seq.current('n1')).toBe(2);
  });

  it('forget 之後唔會再累積（刪筆記／離開）', () => {
    const seq = createSaveSequencer();
    seq.next('n1');
    seq.forget('n1');
    expect(seq.current('n1')).toBe(0);
    expect(seq.next('n1')).toBe(1);
  });
});

describe('P0-6 狀態顯示', () => {
  it('離線優先於其他狀態（離線時唔應該顯示「已儲存」）', () => {
    expect(saveStatusAfter({ ok: true, offline: true })).toBe('offline');
    expect(saveStatusAfter({ ok: false, offline: true })).toBe('offline');
  });

  it('成功 → saved；失敗 → error', () => {
    expect(saveStatusAfter({ ok: true })).toBe('saved');
    expect(saveStatusAfter({ ok: false })).toBe('error');
  });

  it('每個狀態都有 i18n key 同 fallback（spec P0-5：唔可以漏 locale）', () => {
    for (const s of ['idle', 'saving', 'saved', 'offline', 'error'] as const) {
      expect(SAVE_STATUS_KEY[s]).toMatch(/^notes\./);
      expect(typeof SAVE_STATUS_FALLBACK[s]).toBe('string');
    }
  });
});

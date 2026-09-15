/**
 * 2026-09-13 mobile-notes P0-2 — 「同一時間只有一層擁有 bottom 區域」同 back 行為。
 */
import { describe, expect, it } from 'vitest';
import {
  BOTTOM_LAYERS,
  assertSingleBottomOwner,
  backLeavesNotes,
  nextStateOnBack,
  openState,
  shellContextOf,
  shouldShowGlobalNav,
  type NotesMobileState,
} from './notesMobileState';

const ALL_STATES = Object.keys(BOTTOM_LAYERS) as NotesMobileState[];

describe('P0-2 每一層只可以有一個 bottom owner', () => {
  it('六個狀態全部恰好一個 owner（唔會出現 global nav + sheet 同時爭）', () => {
    for (const s of ALL_STATES) {
      expect(assertSingleBottomOwner(s), `state=${s}`).toBe(true);
    }
  });

  it('list：global nav 可見，其他兩層都唔可以', () => {
    expect(shouldShowGlobalNav('list')).toBe(true);
    expect(shouldShowGlobalNav('editor')).toBe(false);
  });

  it('drawer / create / sort / more：global nav 一定要收埋（唔可以喺 scrim 下邊仲撳得）', () => {
    for (const s of ['drawer', 'create', 'sort', 'more'] as NotesMobileState[]) {
      expect(shouldShowGlobalNav(s), `state=${s}`).toBe(false);
    }
  });

  it('editor：只有 editor bar，冇 blocking sheet', () => {
    expect(BOTTOM_LAYERS.editor).toEqual({ globalNav: false, editorBar: true, blockingSheet: false });
  });

  it('shell context attribute 令 CSS 可以隱藏 .mnav-bar', () => {
    expect(shellContextOf('editor')).toBe('notes-editor');
    expect(shellContextOf('list')).toBe('notes-list');
  });
});

describe('開啟 sheet／editor 唔會疊層', () => {
  it('list → 任何 sheet 都開得', () => {
    expect(openState('list', 'drawer')).toBe('drawer');
    expect(openState('list', 'create')).toBe('create');
    expect(openState('list', 'sort')).toBe('sort');
    expect(openState('list', 'editor')).toBe('editor');
  });

  it('已經有 blocking sheet 就唔會再疊第二個', () => {
    expect(openState('drawer', 'create')).toBe('drawer');
    expect(openState('create', 'sort')).toBe('create');
    expect(openState('sort', 'drawer')).toBe('sort');
  });

  it('editor 只可以開 more／sort（more 之後要返得到 editor）', () => {
    expect(openState('editor', 'more')).toBe('more');
    expect(openState('editor', 'sort')).toBe('sort');
    expect(openState('editor', 'create')).toBe('editor');
  });
});

describe('Back 關最頂層，最後才離開 Notes', () => {
  it('drawer / create / sort → list', () => {
    expect(nextStateOnBack('drawer')).toBe('list');
    expect(nextStateOnBack('create')).toBe('list');
    expect(nextStateOnBack('sort')).toBe('list');
  });

  it('editor 開嘅 more → 返 editor（唔係返 list）', () => {
    expect(nextStateOnBack('more', 'editor')).toBe('editor');
  });

  it('list 開嘅 more → 返 list', () => {
    expect(nextStateOnBack('more', 'list')).toBe('list');
  });

  it('editor → list（先 flush save 由 page 負責）', () => {
    expect(nextStateOnBack('editor')).toBe('list');
  });

  it('只有 list 狀態下 Back 才會離開 Notes', () => {
    expect(backLeavesNotes('list')).toBe(true);
    for (const s of ['drawer', 'create', 'editor', 'sort', 'more'] as NotesMobileState[]) {
      expect(backLeavesNotes(s), `state=${s}`).toBe(false);
    }
  });
});

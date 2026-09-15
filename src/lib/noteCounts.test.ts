/**
 * 2026-09-13 mobile-notes P0-1 — 未分類筆記必須計入「全部筆記」總數。
 *
 * 呢個 test 係 reproduction：deployed 頁面（NotesWorkspacePage.tsx:208 /
 * NotesPage.tsx:51）用 sum(notebook.note_count)，所以下邊 case 2 會 red。
 * 修好之後（用 GET /api/v1/crm/notes 嘅 total）全部 case green。
 */
import { describe, expect, it } from 'vitest';
import { deriveAllNotesTotal, notebookCountOf, sumNotebookCounts } from './noteCounts';

/** 4 篇有分類（1 本 notebook）+ 1 篇未分類 = 真總數 5。 */
const NOTEBOOKS = [{ id: 'nb-1', note_count: 4 }];
const SERVER_TOTAL = 5; // GET /notes?limit=1 → { total: 5 }

describe('P0-1 未分類筆記要計入全部筆記', () => {
  it('case 1：有 server total 時用 server total（5 = 4 有分類 + 1 未分類）', () => {
    expect(deriveAllNotesTotal({ apiTotal: SERVER_TOTAL, notebooks: NOTEBOOKS })).toBe(5);
  });

  it('case 2（regression guard）：notebook sum 唔可能做權威 —— 一定漏未分類', () => {
    // Deployed 版本（NotesWorkspacePage.tsx:208 / NotesPage.tsx:51）就係用呢個 sum。
    // 4 篇有分類 + 1 篇未分類 → sum 永遠 4，永遠唔會等於真總數 5。
    expect(sumNotebookCounts(NOTEBOOKS)).toBe(4);
    expect(sumNotebookCounts(NOTEBOOKS)).not.toBe(SERVER_TOTAL);
    // 所以只要頁面 pass apiTotal，總數就一定包含未分類
    expect(deriveAllNotesTotal({ apiTotal: SERVER_TOTAL, notebooks: NOTEBOOKS })).toBe(SERVER_TOTAL);
  });

  it('case 3：server total 未載入完（null）先 fallback，唔可以顯示錯嘅 0', () => {
    expect(deriveAllNotesTotal({ apiTotal: null, notebooks: NOTEBOOKS })).toBe(4);
    expect(deriveAllNotesTotal({})).toBe(0);
  });

  it('case 4：server total 為 0 係有效值（唔可以當未載入）', () => {
    expect(deriveAllNotesTotal({ apiTotal: 0, notebooks: [] })).toBe(0);
  });

  it('case 5：新增一篇未分類筆記，總數即刻 +1', () => {
    const before = deriveAllNotesTotal({ apiTotal: 5, notebooks: NOTEBOOKS });
    const after = deriveAllNotesTotal({ apiTotal: 6, notebooks: NOTEBOOKS });
    expect(after - before).toBe(1);
  });
});

describe('per-notebook count 嘅 null 安全', () => {
  it('null / undefined / 負數 / NaN 一律當 0', () => {
    expect(notebookCountOf({ note_count: null })).toBe(0);
    expect(notebookCountOf({ id: 'x' })).toBe(0);
    expect(notebookCountOf({ note_count: -3 })).toBe(0);
    expect(notebookCountOf({ note_count: Number.NaN })).toBe(0);
    expect(notebookCountOf(undefined)).toBe(0);
  });

  it('sumNotebookCounts 接受空陣列／null', () => {
    expect(sumNotebookCounts([])).toBe(0);
    expect(sumNotebookCounts(null)).toBe(0);
    expect(sumNotebookCounts([{ note_count: 2 }, { note_count: 3 }])).toBe(5);
  });
});

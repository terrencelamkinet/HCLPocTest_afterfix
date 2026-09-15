/**
 * Note-count derivation for the Notes module.
 *
 * 2026-09-13 mobile-notes P0-1：deployed 版本嘅「全部筆記」總數係將
 * /api/v1/crm/notebooks 回嘅 per-notebook `note_count` 加埋
 * （NotesWorkspacePage.tsx:208、NotesPage.tsx:51）。`notebook_id IS NULL` 嘅
 * 「未分類」筆記唔屬於任何 notebook，所以被靜默漏掉 —— 產品可以喺真有一篇
 * 未分類筆記嘅情況下顯示 0 篇。
 *
 * 權威來源係 GET /api/v1/crm/notes 嘅 `ListResponse.total`：佢 count 呼叫者
 * 自己寫、未刪除嘅全部筆記（有分類 + 未分類）。
 */

export type NotebookLike = {
  id?: string;
  note_count?: number | null;
};

/** Per-notebook count，null-safe（rail 每一行用）。 */
export function notebookCountOf(nb: NotebookLike | null | undefined): number {
  const n = nb?.note_count;
  return typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : 0;
}

/** 將 per-notebook count 加埋。**唔可以**用嚟做「全部筆記」總數 — 見檔頭。 */
export function sumNotebookCounts(notebooks: readonly NotebookLike[] | null | undefined): number {
  if (!notebooks?.length) return 0;
  return notebooks.reduce((sum, nb) => sum + notebookCountOf(nb), 0);
}

export type AllNotesTotalInput = {
  /** GET /api/v1/crm/notes 嘅 ListResponse.total（未載入完 = null/undefined）。 */
  apiTotal?: number | null;
  notebooks?: readonly NotebookLike[] | null;
};

/**
 * 「全部筆記」總數。
 * 有 server aggregate 就用佢（權威，包含未分類）；未載入完先用 notebook sum
 * 暫代 —— 唔會顯示「0 篇」而其實有未分類筆記。
 */
export function deriveAllNotesTotal({ apiTotal, notebooks }: AllNotesTotalInput = {}): number {
  if (typeof apiTotal === 'number' && Number.isFinite(apiTotal) && apiTotal >= 0) return apiTotal;
  return sumNotebookCounts(notebooks);
}

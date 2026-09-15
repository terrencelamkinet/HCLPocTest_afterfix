/**
 * 儲存排序（2026-09-13 mobile Notes P0-6）。
 *
 * 問題：NexusEditor 嘅 autosave 可能同時有兩個 request 喺飛（用戶打完字即刻又打）。
 * 舊 request 遲返嘅回應會蓋掉新 request 嘅 version → 之後就係假 409 衝突、
 * 或者「Saving…」永遠唔消失。
 *
 * 解法：每個 note 一條 generation 序列。只有「最新一個 request」嘅回應可以寫入
 * version／更新 UI；舊嘅一律當 stale 掉棄（連 error 都唔好蓋過新 request 嘅狀態）。
 */

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'offline' | 'error'

export interface SaveSequencer {
  /** 開一個新 request，回傳佢嘅 generation。 */
  next(id: string): number
  /** 呢個 generation 係唔係仲係最新（舊 request 嘅回應要掉棄）。 */
  isLatest(id: string, generation: number): boolean
  /** 測試／debug 用 */
  current(id: string): number
  /** 刪筆記之後清走，避免 memory 無限量長大。 */
  forget(id: string): void
}

export function createSaveSequencer(): SaveSequencer {
  const generations = new Map<string, number>()
  return {
    next(id) {
      const g = (generations.get(id) ?? 0) + 1
      generations.set(id, g)
      return g
    },
    isLatest(id, generation) {
      return generations.get(id) === generation
    },
    current(id) {
      return generations.get(id) ?? 0
    },
    forget(id) {
      generations.delete(id)
    },
  }
}

/** 由瀏覽器離線狀態 + 儲存結果決定要顯示嘅狀態。 */
export function saveStatusAfter(opts: {
  ok: boolean
  conflict?: boolean
  offline?: boolean
}): SaveStatus {
  if (opts.offline) return 'offline'
  if (opts.ok) return 'saved'
  return 'error'
}

/** i18n key（UI 一律用呢個，唔好散落 hardcode 字串）。 */
export const SAVE_STATUS_KEY: Record<SaveStatus, string> = {
  idle: 'notes.saveIdle',
  saving: 'notes.saving',
  saved: 'notes.saved',
  offline: 'notes.offlineChanges',
  error: 'notes.saveFailed',
}

/** 預設英文／繁中文字（i18n 未覆蓋時嘅 fallback，spec P0-5）。 */
export const SAVE_STATUS_FALLBACK: Record<SaveStatus, string> = {
  idle: '',
  saving: '儲存中…',
  saved: '已儲存',
  offline: '離線變更',
  error: '儲存失敗',
}

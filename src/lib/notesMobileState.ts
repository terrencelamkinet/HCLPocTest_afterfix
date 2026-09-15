/**
 * 2026-09-13 mobile-notes P0-2/P0-3 — mobile Notes UI 狀態機。
 *
 * 問題（deployed）：global Penguin bottom nav 一直留喺 notebook drawer、create
 * modal、editor、block sheet 下邊 → 同一時間有三層搶同一個 bottom 區域
 * （browser chrome + global nav + sheet/editor bar）。
 *
 * 修法：唔再靠 URL／散落嘅 boolean 去推斷 transient UI，改成一個明確狀態，
 * 由狀態決定邊一層「擁有」bottom 區域。任何時間**只能有一層**。
 */

export type NotesMobileState = 'list' | 'drawer' | 'create' | 'editor' | 'sort' | 'more';

export type BottomLayerOwnership = {
  /** 全域 Penguin bottom nav 可唔可以見／可唔可以撳 */
  globalNav: boolean;
  /** editor 專用 accessory bar（immersive mode） */
  editorBar: boolean;
  /** 一個 blocking sheet（drawer / create / sort / more）擁有 focus */
  blockingSheet: boolean;
};

/** 每個狀態只有一個 bottom owner（見 assertSingleBottomOwner）。 */
export const BOTTOM_LAYERS: Record<NotesMobileState, BottomLayerOwnership> = {
  list: { globalNav: true, editorBar: false, blockingSheet: false },
  drawer: { globalNav: false, editorBar: false, blockingSheet: true },
  create: { globalNav: false, editorBar: false, blockingSheet: true },
  editor: { globalNav: false, editorBar: true, blockingSheet: false },
  sort: { globalNav: false, editorBar: false, blockingSheet: true },
  more: { globalNav: false, editorBar: false, blockingSheet: true },
};

export function bottomLayersOf(state: NotesMobileState): BottomLayerOwnership {
  return BOTTOM_LAYERS[state] ?? BOTTOM_LAYERS.list;
}

/** Global nav 喺呢個狀態要唔要 render（MobileNavHost 用）。 */
export function shouldShowGlobalNav(state: NotesMobileState): boolean {
  return bottomLayersOf(state).globalNav;
}

/** Shell context attribute —— CSS 靠佢隱藏 .mnav-bar（唔使加第二個 modal manager）。 */
export function shellContextOf(state: NotesMobileState): string {
  return state === 'editor' ? 'notes-editor' : `notes-${state}`;
}

/** 任何時間一定要有**恰好一個** bottom owner。 */
export function assertSingleBottomOwner(state: NotesMobileState): boolean {
  const { globalNav, editorBar, blockingSheet } = bottomLayersOf(state);
  return [globalNav, editorBar, blockingSheet].filter(Boolean).length === 1;
}

/**
 * 開一個 sheet／入 editor。回傳新狀態（list 以外嘅狀態唔會被另一個 sheet 搶）。
 * 例外：more 可以由 editor 開（editor → more），close 之後返 editor。
 */
export function openState(
  current: NotesMobileState,
  next: Exclude<NotesMobileState, 'list'>,
): NotesMobileState {
  if (current === 'editor') return next === 'more' || next === 'sort' ? next : current;
  if (current !== 'list') return current; // 已經有 blocking sheet → 唔疊
  return next;
}

/**
 * Back（Android／browser back）關閉**最頂層** transient 狀態，最後才離開 Notes。
 * drawer/create/sort → list；more → 返擁有者（editor 開嘅 → editor，否則 list）。
 */
export function nextStateOnBack(current: NotesMobileState, openedFrom?: NotesMobileState): NotesMobileState {
  switch (current) {
    case 'drawer':
    case 'create':
    case 'sort':
      return 'list';
    case 'more':
      return openedFrom === 'editor' ? 'editor' : 'list';
    case 'editor':
      return 'list';
    default:
      return 'list';
  }
}

/** True = back 應該離開 Notes page（唔再有 transient 狀態可以關）。 */
export function backLeavesNotes(current: NotesMobileState): boolean {
  return current === 'list';
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderInput, History, Pin, Trash2 } from 'lucide-react'
import AppBottomSheet from './AppBottomSheet'

/**
 * Mobile editor「更多」sheet（2026-09-13 mobile Notes P1-⑪）。
 *
 * 之前手機 editor 頂欄直接放 native `<select>`（選 notebook）＋ 釘選／版本／刪除三粒 icon：
 *   - native select 係 OS chrome，會搶 app 嘅 bottom 區域（同 P0-3 排序一樣嘅問題）
 *   - 頂欄 390px 要塞 4 個控制，容易誤撳刪除（spec 要求 Delete 唔做 primary）
 * 改成：頂欄只留 ⋯，其他全部入呢個 sheet（pin／移動／版本／刪除）。
 *
 * Spec 仲有提 duplicate／export —— 呢兩個 app 根本冇對應 action，所以**唔造 UI**
 * （Terrence 鐵律 Less is more：唔為咗填 spec 而堆假功能）。
 */

export interface Props {
  pinned: boolean
  /** 現時 notebook（null = 未分類） */
  notebookId: string | null
  notebooks: Array<{ id: string; name: string }>
  onTogglePin: () => void
  onMove: (notebookId: string | null) => void
  onHistory: () => void
  onDelete: () => void
  onClose: () => void
}

export default function EditorMoreSheet({
  pinned,
  notebookId,
  notebooks,
  onTogglePin,
  onMove,
  onHistory,
  onDelete,
  onClose,
}: Props) {
  const { t } = useTranslation()
  const [moveOpen, setMoveOpen] = useState(false)
  const title = t('notes.more', { defaultValue: '更多' })
  const moveLabel = t('notes.moveTo', { defaultValue: '移動到 Notebook' })

  return (
    <AppBottomSheet title={title as string} onClose={onClose} testId="notes-more-sheet">
      <div className="nwbs-actions">
        <button
          type="button"
          className="nwbs-action"
          aria-pressed={pinned}
          onClick={() => { onTogglePin(); onClose() }}
        >
          <Pin size={16} strokeWidth={1.75} />
          <span>{pinned ? t('notes.unpin', { defaultValue: '取消釘選' }) : t('notes.pin', { defaultValue: '釘選' })}</span>
          <span className="nwbs-action-mark" aria-hidden="true">{pinned ? '✓' : ''}</span>
        </button>

        <button
          type="button"
          className="nwbs-action"
          aria-expanded={moveOpen}
          aria-controls="nwbs-move-list"
          onClick={() => setMoveOpen((v) => !v)}
        >
          <FolderInput size={16} strokeWidth={1.75} />
          <span>{moveLabel}</span>
          <span className="nwbs-action-mark" aria-hidden="true">{moveOpen ? '▾' : '▸'}</span>
        </button>

        {moveOpen && (
          /* 同排序 sheet 一樣用 radiogroup／radio：讀屏講得出「而家喺邊個 notebook」 */
          <div className="nwbs-radios" id="nwbs-move-list" role="radiogroup" aria-label={moveLabel as string}>
            <button
              type="button" role="radio" aria-checked={!notebookId}
              className={`nwbs-radio${!notebookId ? ' is-checked' : ''}`} data-notebook="none"
              onClick={() => { onMove(null); onClose() }}
            >
              <span className="nwbs-radio-label">{t('notes.uncategorized', { defaultValue: '未分類' })}</span>
              <span className="nwbs-radio-mark" aria-hidden="true">{!notebookId ? '✓' : ''}</span>
            </button>
            {notebooks.map((nb) => {
              const checked = notebookId === nb.id
              return (
                <button
                  key={nb.id} type="button" role="radio" aria-checked={checked}
                  className={`nwbs-radio${checked ? ' is-checked' : ''}`} data-notebook={nb.id}
                  onClick={() => { onMove(nb.id); onClose() }}
                >
                  <span className="nwbs-radio-label">{nb.name}</span>
                  <span className="nwbs-radio-mark" aria-hidden="true">{checked ? '✓' : ''}</span>
                </button>
              )
            })}
          </div>
        )}

        <button type="button" className="nwbs-action" onClick={() => { onClose(); onHistory() }}>
          <History size={16} strokeWidth={1.75} />
          <span>{t('notes.history', { defaultValue: '版本紀錄' })}</span>
        </button>

        {/* spec：Delete 唔做 primary —— 收埋入 sheet 尾，紅色但唔係第一眼見到嘅嘢 */}
        <button type="button" className="nwbs-action is-danger" onClick={() => { onClose(); onDelete() }}>
          <Trash2 size={16} strokeWidth={1.75} />
          <span>{t('common.delete', { defaultValue: '刪除' })}</span>
        </button>
      </div>
    </AppBottomSheet>
  )
}

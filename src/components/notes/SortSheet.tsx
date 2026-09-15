import { useTranslation } from 'react-i18next'
import AppBottomSheet from './AppBottomSheet'

/**
 * Mobile 排序（2026-09-13 mobile Notes P0-3）。
 *
 * 之前手機用 native `<select className="nw-meta-select">`：picker 係 OS chrome，
 * 會蓋住同搶 app 嘅 bottom 區域，亦唔跟 app 語言／主題。改用 app bottom sheet +
 * radio rows（role=radiogroup／radio + aria-checked），同 notebook drawer 同一套
 * bottom-layer 規則。
 */

export interface SortOption {
  value: string
  /** i18n key；translate 唔到就 fallback 顯示 value */
  key: string
}

export interface Props {
  value: string
  options: readonly SortOption[]
  onSelect: (value: string) => void
  onClose: () => void
}

export default function SortSheet({ value, options, onSelect, onClose }: Props) {
  const { t } = useTranslation()
  const title = t('notes.sortBy', { defaultValue: '排序' })

  return (
    <AppBottomSheet title={title as string} onClose={onClose} testId="notes-sort-sheet">
      <div className="nwbs-radios" role="radiogroup" aria-label={title as string}>
        {options.map((opt) => {
          const checked = opt.value === value
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={checked}
              className={`nwbs-radio${checked ? ' is-checked' : ''}`}
              data-sort={opt.value}
              onClick={() => onSelect(opt.value)}
            >
              <span className="nwbs-radio-label">{t(opt.key, { defaultValue: opt.value }) as string}</span>
              <span className="nwbs-radio-mark" aria-hidden="true">{checked ? '✓' : ''}</span>
            </button>
          )
        })}
      </div>
    </AppBottomSheet>
  )
}

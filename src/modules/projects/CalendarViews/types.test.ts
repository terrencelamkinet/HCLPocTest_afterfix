import { describe, expect, it } from 'vitest'
import { formatEvents } from './types'
import type { CalendarEvent } from './types'

/** 用戶報：calendar 月曆 event 排序由「早到晚」變成「晚到早」。 */
const ev = (id: string, start: string, allDay = false): CalendarEvent =>
  ({
    id,
    title: id,
    event_type: 'meeting',
    start,
    end: start,
    is_all_day: allDay,
  }) as CalendarEvent

describe('formatEvents — 一律排「早 → 晚」', () => {
  it('亂序輸入 → 按 start 升序輸出（唔可以晚到早）', () => {
    const out = formatEvents([
      ev('1700', '2026-09-13T17:00:00'),
      ev('0900', '2026-09-13T09:00:00'),
      ev('1230', '2026-09-13T12:30:00'),
      ev('0800', '2026-09-13T08:00:00'),
    ])
    expect(out.map((e) => e.id)).toEqual(['0800', '0900', '1230', '1700'])
  })

  it('跨日：早嘅日子排前面', () => {
    const out = formatEvents([ev('d3', '2026-09-15T10:00:00'), ev('d1', '2026-09-13T10:00:00'), ev('d2', '2026-09-14T10:00:00')])
    expect(out.map((e) => e.id)).toEqual(['d1', 'd2', 'd3'])
  })

  it('全日 event（00:00）排喺同日有時段嘅前面', () => {
    const out = formatEvents([ev('timed', '2026-09-13T09:00:00'), ev('allday', '2026-09-13', true)])
    expect(out.map((e) => e.id)).toEqual(['allday', 'timed'])
  })

  it('唔會改到原本 array（formatEvents 唔應該 mutate 輸入）', () => {
    const input = [ev('late', '2026-09-13T17:00:00'), ev('early', '2026-09-13T09:00:00')]
    formatEvents(input)
    expect(input.map((e) => e.id)).toEqual(['late', 'early'])
  })
})

import { describe, it, expect } from 'vitest'
import { computeGuide, orderTLTRBRBL, polyArea, runChecks, type QuadPt } from './detectQuad'

describe('computeGuide', () => {
  // 2026-09-13 Terrence「盡量貼外框」：可用寬 = min(cssW, cssH × CARD_ASPECT)，
  // guide = 可用寬 × 0.96（每邊 2%）⇒ 兩個方向都放到最大，唔會爆出 preview 框。
  it('landscape 16:10 frame — 貼外框（96% 可用寬）、aspect 1.67、完全置中', () => {
    const g = computeGuide(390, 244) // cam-frame landscape
    expect(g.w).toBeCloseTo(390 * 0.96, 1)
    expect(g.w / g.h).toBeCloseTo(1.67, 2)
    expect(g.h).toBeLessThanOrEqual(244) // 一定要放得入 frame
    expect(g.x).toBeCloseTo((390 - g.w) / 2, 1)
    expect(g.y).toBeCloseTo((244 - g.h) / 2, 1)
  })
  it('portrait frame — 同樣貼外框，唔會超出寬或高', () => {
    const gp = computeGuide(390, 700)
    expect(gp.w).toBeCloseTo(390 * 0.96, 1)
    expect(gp.w).toBeLessThanOrEqual(390)
    expect(gp.h).toBeLessThanOrEqual(700)
  })
  it('扁框（高度係限制）— 由高度決定（回歸：舊版只按長邊計會爆框）', () => {
    const g = computeGuide(800, 300)
    expect(g.h).toBeLessThanOrEqual(300)
    expect(g.w).toBeLessThanOrEqual(800)
    expect(g.w / g.h).toBeCloseTo(1.67, 2)
  })
})

describe('orderTLTRBRBL', () => {
  it('orders shuffled corners correctly', () => {
    const shuffled: QuadPt[] = [
      { x: 300, y: 100 }, // TR
      { x: 300, y: 300 }, // BR
      { x: 100, y: 300 }, // BL
      { x: 100, y: 100 }, // TL
    ]
    const ordered = orderTLTRBRBL(shuffled)
    expect(ordered[0]).toEqual({ x: 100, y: 100 }) // TL
    expect(ordered[1]).toEqual({ x: 300, y: 100 }) // TR
    expect(ordered[2]).toEqual({ x: 300, y: 300 }) // BR
    expect(ordered[3]).toEqual({ x: 100, y: 300 }) // BL
  })
})

describe('polyArea', () => {
  it('square area = side^2', () => {
    const sq: QuadPt[] = [
      { x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }, { x: 0, y: 100 },
    ]
    expect(polyArea(sq)).toBeCloseTo(10000, 5)
  })
})

describe('runChecks — green/gray gates (guide §3)', () => {
  // guide 100x59.88 (aspect 1.67) at (50, 50)
  const guide = { x: 50, y: 50, w: 100, h: 100 / 1.67 }

  const atCorner = (cx: number, cy: number): QuadPt => ({ x: 50 + cx, y: 50 + cy })

  it('perfectly aligned card (94% fill — card slightly inside guide) → ok (green)', () => {
    // 卡 inset 3% 每邊: w=94, h=94/1.67（area ratio ~0.88 → within 78-96%; corner dist ~3.5px < 7% gw）
    const k = 0.94
    const w = 100 * k
    const h = (100 / 1.67) * k
    const ox = (100 - w) / 2
    const oy = (100 / 1.67 - h) / 2
    const quad: QuadPt[] = [
      atCorner(ox, oy),
      atCorner(ox + w, oy),
      atCorner(ox + w, oy + h),
      atCorner(ox, oy + h),
    ]
    expect(runChecks(quad, guide, 180).ok).toBe(true)
  })

  it('card too small (area 60% of guide) → gray', () => {
    const w = 100 * 0.75 // 0.5625 area ratio — below 0.78
    const quad: QuadPt[] = [
      atCorner((100 - w) / 2, (100 / 1.67 - w / 1.67) / 2),
      atCorner((100 - w) / 2 + w, (100 / 1.67 - w / 1.67) / 2),
      atCorner((100 - w) / 2 + w, (100 / 1.67 - w / 1.67) / 2 + w / 1.67),
      atCorner((100 - w) / 2, (100 / 1.67 - w / 1.67) / 2 + w / 1.67),
    ]
    expect(runChecks(quad, guide, 180).ok).toBe(false)
  })

  it('card offset beyond 9% corner tol → gray', () => {
    const off = 100 * 0.12 // 12% shift > 9% tol（放寬後 7-9% 之間應該 green — 另測）
    const quad: QuadPt[] = [
      atCorner(off, off),
      atCorner(100 + off, off),
      atCorner(100 + off, 100 / 1.67 + off),
      atCorner(off, 100 / 1.67 + off),
    ]
    expect(runChecks(quad, guide, 180).ok).toBe(false)
  })

  it('slight offset 6% (card 94% fill — real aligned case) → green（放寬 regression）', () => {
    // 卡 94% 大細（area ~0.88）＋ 偏移 6% per axis → corner dist ≈ 8.5px:
    // old tol 7px → fail；new tol 9px → pass（area 0.88 亦喺 0.72-0.97 內）
    const w = 94
    const off = 100 * 0.06
    const quad: QuadPt[] = [
      atCorner(off, off),
      atCorner(off + w, off),
      atCorner(off + w, off + w / 1.67),
      atCorner(off, off + w / 1.67),
    ]
    expect(runChecks(quad, guide, 180).ok).toBe(true)
  })

  it('wrong aspect (tall card ~1.2) → gray', () => {
    const h = 100 / 1.2 // aspect 1.2 → below 1.42
    const quad: QuadPt[] = [
      atCorner(0, (100 / 1.67 - h) / 2),
      atCorner(100, (100 / 1.67 - h) / 2),
      atCorner(100, (100 / 1.67 - h) / 2 + h),
      atCorner(0, (100 / 1.67 - h) / 2 + h),
    ]
    expect(runChecks(quad, guide, 180).ok).toBe(false)
  })

  it('skewed (trapezoid, edge delta > 15%) → gray', () => {
    const quad: QuadPt[] = [
      atCorner(0, 0),
      atCorner(100, 0),
      atCorner(100, 100 / 1.67),
      atCorner(0, 100 / 1.67),
    ]
    quad[2] = atCorner(135, 100 / 1.67) // bottom-right pushed out → edge delta ~35/100 = 35% > 15%
    expect(runChecks(quad, guide, 180).ok).toBe(false)
  })

  it('dark frame (luma ≤ 40) → gray even if geometry passes', () => {
    const quad: QuadPt[] = [
      atCorner(0, 0),
      atCorner(100, 0),
      atCorner(100, 100 / 1.67),
      atCorner(0, 100 / 1.67),
    ]
    expect(runChecks(quad, guide, 35).ok).toBe(false)
  })
})

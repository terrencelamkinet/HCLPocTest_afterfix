/**
 * Cam-level 4-corner detection for name-card scan（SPEC:
 * docs/namecard-scan-cam-detect-SPEC.md + guide penguin-crm-namecard-scan-overlay-focus.md §2–§3）
 *
 * Two engines（Q4 決定 — 兩段式）:
 * - `analyzeLiteFrame` — 純 JS / canvas 2D（<50KB 即載 — T1 即時起動）
 * - `analyzeFrame` — OpenCV.js wasm（@techstark/opencv-js — T2 後台載入後自動升級）
 * 兩者輸出同一 FrameCheck — 引擎切換對 caller 無感。
 *
 * Zero-cost: 本地偵測 — 冇 paid scan SDK / vision API.
 */

export interface QuadPt { x: number; y: number }
export interface GuideRect { x: number; y: number; w: number; h: number }

export interface FrameCheck {
  ok: boolean
  reason?: string
  /** 4 corners（TL/TR/BR/BL）in CSS px — only when a quad was found */
  quad?: QuadPt[]
  luma?: number
  /** 每隻角達標未 [TL, TR, BR, BL] — 用嚟逐角變綠引導用戶（2026-09-10 Terrence） */
  cornerOk?: boolean[]
}

export const CARD_ASPECT = 1.67 // HK card ~90×54mm（ISO 7810 ID-1 family）
export const LUMA_MIN = 40

/** Guide rect: ~78% of the shorter side as card width, centered, aspect 1.67 */
export function computeGuide(cssW: number, cssH: number): GuideRect {
  // 2026-09-13 Terrence: 「盡量貼外框」→ 由長邊 88% 推到「兩個方向都放到最大」再留 2% 邊距。
  // 舊版只按長邊算，窄框（例如 16:10 preview）左右會剩好多空位。新版：
  //   可用寬 = min(cssW, cssH × CARD_ASPECT) ← 同時受兩邊限制
  //   guide = 可用寬 × 0.96（每邊 2%）→ 卡片盡量貼住 preview 外框
  const fitW = Math.min(cssW, cssH * CARD_ASPECT)
  const w = fitW * 0.96
  const h = w / CARD_ASPECT
  return { x: (cssW - w) / 2, y: (cssH - h) / 2, w, h }
}

/** Order 4 quad points TL → TR → BR → BL（classic sum/diff method） */
export function orderTLTRBRBL(pts: QuadPt[]): QuadPt[] {
  const s = pts.map((p, i) => ({ i, v: p.x + p.y }))
  const d = pts.map((p, i) => ({ i, v: p.x - p.y }))
  const tl = pts[s.reduce((a, b) => (b.v < a.v ? b : a)).i]
  const br = pts[s.reduce((a, b) => (b.v > a.v ? b : a)).i]
  const tr = pts[d.reduce((a, b) => (b.v > a.v ? b : a)).i]
  const bl = pts[d.reduce((a, b) => (b.v < a.v ? b : a)).i]
  return [tl, tr, br, bl]
}

/** Shoelace polygon area */
export function polyArea(pts: QuadPt[]): number {
  let a = 0
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length
    a += pts[i].x * pts[j].y - pts[j].x * pts[i].y
  }
  return Math.abs(a) / 2
}

function dist(a: QuadPt, b: QuadPt): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/**
 * Guide §3 checks — green ONLY if ALL pass（純幾何 — unit-testable）。
 * `luma` — mean frame luma（0-255）; ≤ LUMA_MIN → fail（太暗唔計）。
 */
export function runChecks(quad: QuadPt[], g: GuideRect, luma: number): FrameCheck {
  const gCorners: QuadPt[] = [
    { x: g.x, y: g.y },
    { x: g.x + g.w, y: g.y },
    { x: g.x + g.w, y: g.y + g.h },
    { x: g.x, y: g.y + g.h },
  ]
  const gw = g.w
  const tol = 0.13 * gw
  /* Per-corner 判定（2026-09-10 Terrence: 邊隻角到位就邊隻角綠 — 引導用戶遂隻
     角放入框，唔係一次過 4 角。整體 aligned 仍然要 4 角全綠。 */
  const errs = [0, 1, 2, 3].map(i => dist(quad[i], gCorners[i]))
  const cornerOk = errs.map(e => e <= tol)
  if (luma <= LUMA_MIN) return { ok: false, reason: `dark:${Math.round(luma)}`, quad, luma, cornerOk }
  const qArea = polyArea(quad)
  const gArea = g.w * g.h
  const areaRatio = qArea / gArea
  if (areaRatio < 0.65 || areaRatio > 0.985) {
    return { ok: false, reason: `area:${areaRatio.toFixed(2)}`, quad, luma, cornerOk }
  }
  const edges = [
    dist(quad[0], quad[1]), dist(quad[2], quad[3]), // top / bottom
    dist(quad[1], quad[2]), dist(quad[3], quad[0]), // right / left
  ]
  const wAvg = (edges[0] + edges[1]) / 2
  const hAvg = (edges[2] + edges[3]) / 2
  const aspect = Math.max(wAvg, hAvg) / Math.max(1, Math.min(wAvg, hAvg))
  if (aspect < 1.30 || aspect > 2.15) {
    return { ok: false, reason: `aspect:${aspect.toFixed(2)}`, quad, luma, cornerOk }
  }
  const horizDelta = Math.abs(edges[0] - edges[1]) / Math.max(1, wAvg)
  const vertDelta = Math.abs(edges[2] - edges[3]) / Math.max(1, hAvg)
  if (horizDelta > 0.20 || vertDelta > 0.20) {
    return { ok: false, reason: `skew:${Math.max(horizDelta, vertDelta).toFixed(2)}`, quad, luma, cornerOk }
  }
  const ok = cornerOk.every(Boolean)
  if (!ok) {
    const worst = errs.reduce((a, b, i) => (b > errs[a] ? i : a), 0)
    return { ok: false, reason: `corner${worst}:${Math.round(errs[worst])}px`, quad, luma, cornerOk }
  }
  return { ok: true, quad, luma, cornerOk }
}

/** Cover-crop draw — detection space maps 1:1 (uniform scale) to CSS overlay px */
function drawCoverFrame(video: HTMLVideoElement, dst: HTMLCanvasElement) {
  const vw = video.videoWidth || 1
  const vh = video.videoHeight || 1
  const asp = dst.width / dst.height
  let sw = vw
  let sh = vw / asp
  if (sh > vh) { sh = vh; sw = vh * asp }
  const sx = (vw - sw) / 2
  const sy = (vh - sh) / 2
  const ctx = dst.getContext('2d', { willReadFrequently: true })
  if (!ctx) return
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, dst.width, dst.height)
}

/** Detection-space size for a CSS viewport（cover aspect kept, long edge = target）。
 *  scale = cssW/dw — bbox/contour px × scale → CSS overlay px（x/y 同比例 — cover crop 保 aspect）。 */
function detSize(cssW: number, cssH: number, target: number): { dw: number; dh: number; scale: number } {
  if (cssW >= cssH) {
    const dw = target
    const dh = Math.max(2, Math.round(target / (cssW / cssH)))
    return { dw, dh, scale: cssW / dw }
  }
  const dh = target
  const dw = Math.max(2, Math.round(target / (cssH / cssW)))
  return { dw, dh, scale: cssW / dw }
}

// ============================================================================
// Engine 1 — 純 JS 輕量（T1）: 1D-gradient edge mask → 最大連通 component bbox
// ============================================================================

const LITE_DOWN = 240

/**
 * 輕量偵測 — 唔使 OpenCV。方法:
 * 1. cover-crop downscale（短邊 240）→ grayscale
 * 2. 1D gradient（|dx|+|dy|）→ edge mask（gradient > 25）
 * 3. 4-neighbour BFS → 最大連通 edge component（剔除貼 frame 邊）
 * 4. component bbox → quad（TL/TR/BR/BL — 輕量版用 bbox：斜卡會 fail checks — 啱 — 要對正先綠；
 *    OpenCV 引擎（T2）先做真 quad approx 容 tilt）
 * 5. runChecks（guide §3）
 */
export function analyzeLiteFrame(video: HTMLVideoElement, guideCss: GuideRect): FrameCheck {
  const cssW = guideCss.x * 2 + guideCss.w
  const cssH = guideCss.y * 2 + guideCss.h
  const { dw, dh, scale } = detSize(cssW, cssH, LITE_DOWN)

  const canvas = document.createElement('canvas')
  canvas.width = dw
  canvas.height = dh
  drawCoverFrame(video, canvas)
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return { ok: false, reason: 'no-ctx' }
  const img = ctx.getImageData(0, 0, dw, dh)
  const px = img.data

  // grayscale + luma
  const gray = new Uint8Array(dw * dh)
  let lumaSum = 0
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
    const v = (px[p] * 0.299 + px[p + 1] * 0.587 + px[p + 2] * 0.114) | 0
    gray[i] = v
    lumaSum += v
  }
  const luma = lumaSum / gray.length
  if (luma <= LUMA_MIN) return { ok: false, reason: `dark:${Math.round(luma)}` }

  // 1D gradient magnitude |dx| + |dy|
  const grad = new Uint8Array(dw * dh)
  for (let y = 0; y < dh; y++) {
    const row = y * dw
    for (let x = 0; x < dw; x++) {
      const i = row + x
      const dx = x + 1 < dw ? Math.abs(gray[i + 1] - gray[i]) : 0
      const dy = y + 1 < dh ? Math.abs(gray[i + dw] - gray[i]) : 0
      grad[i] = (dx + dy) > 255 ? 255 : dx + dy
    }
  }
  const EDGE_T = 25

  // BFS connected components over edge mask（4-neighbour）— collect top-3 by size（2026-09-07:
  // 清晰 frame 背景紋理/卡面文字 edges 會搶最大 component — 淨揀最大會 miss 卡框 → 攞 top-3 逐個 checks）
  const seen = new Uint8Array(dw * dh)
  const tops: { size: number; minX: number; minY: number; maxX: number; maxY: number }[] = []
  const MIN_SIZE = (dw * dh) * 0.008
  const pushTop = (c: { size: number; minX: number; minY: number; maxX: number; maxY: number }) => {
    tops.push(c)
    tops.sort((a, b) => b.size - a.size)
    if (tops.length > 3) tops.pop()
  }
  for (let y = 0; y < dh; y++) {
    for (let x = 0; x < dw; x++) {
      const start = y * dw + x
      if (seen[start] || grad[start] <= EDGE_T) continue
      // BFS
      let size = 0
      let minX = x, minY = y, maxX = x, maxY = y
      let touchesBorder = false
      const queue = [start]
      seen[start] = 1
      while (queue.length) {
        const cur = queue.pop()!
        const cx = cur % dw
        const cy = (cur / dw) | 0
        size++
        if (cx < minX) minX = cx
        if (cx > maxX) maxX = cx
        if (cy < minY) minY = cy
        if (cy > maxY) maxY = cy
        if (cx <= 0 || cy <= 0 || cx >= dw - 1 || cy >= dh - 1) touchesBorder = true
        // 4 neighbours
        if (cx > 0 && !seen[cur - 1] && grad[cur - 1] > EDGE_T) { seen[cur - 1] = 1; queue.push(cur - 1) }
        if (cx < dw - 1 && !seen[cur + 1] && grad[cur + 1] > EDGE_T) { seen[cur + 1] = 1; queue.push(cur + 1) }
        if (cy > 0 && !seen[cur - dw] && grad[cur - dw] > EDGE_T) { seen[cur - dw] = 1; queue.push(cur - dw) }
        if (cy < dh - 1 && !seen[cur + dw] && grad[cur + dw] > EDGE_T) { seen[cur + dw] = 1; queue.push(cur + dw) }
      }
      if (touchesBorder) continue
      if (size < MIN_SIZE) continue // too small（卡片 ring 喺 78% fill 時至少 ~5% of px）
      pushTop({ size, minX, minY, maxX, maxY })
    }
  }
  if (!tops.length) return { ok: false, reason: 'no-quad', luma }

  // top-3 逐個轉 quad → checks — 第一個 pass 就 green（垃圾 component 會 fail checks）
  let last: FrameCheck | null = null
  for (const b of tops) {
    const quad: QuadPt[] = [
      { x: b.minX * scale, y: b.minY * scale },
      { x: b.maxX * scale, y: b.minY * scale },
      { x: b.maxX * scale, y: b.maxY * scale },
      { x: b.minX * scale, y: b.maxY * scale },
    ]
    const chk = runChecks(quad, guideCss, luma)
    if (chk.ok) return chk
    if (!last) last = chk
  }
  return last ?? { ok: false, reason: 'no-quad', luma } // 全部 fail → 最大嗰個 reason（debug）
}

// ============================================================================
// Engine 2 — OpenCV.js（T2 — 後台載入後自動升級）
// ============================================================================

const OPENCV_DOWN = 480
const EDGE_LOW = 60
const EDGE_HIGH = 160

/**
 * OpenCV 偵測 — caller 保證 cv 已 ready（@techstark/opencv-js）。
 * Canny → dilate → 最大 convex 4-point contour（剔除貼 frame 邊）→ order → checks。
 */
export function analyzeFrame(
  cv: any,
  video: HTMLVideoElement,
  guideCss: GuideRect,
): FrameCheck {
  const cssW = guideCss.x * 2 + guideCss.w
  const cssH = guideCss.y * 2 + guideCss.h
  const { dw, dh, scale } = detSize(cssW, cssH, OPENCV_DOWN)

  const canvas = document.createElement('canvas')
  canvas.width = dw
  canvas.height = dh
  drawCoverFrame(video, canvas)

  const src = cv.imread(canvas)
  const gray = new cv.Mat()
  const blur = new cv.Mat()
  const edges = new cv.Mat()
  try {
    cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY)
    const luma = meanLuma(gray, cv)
    if (luma <= LUMA_MIN) return { ok: false, reason: `dark:${Math.round(luma)}` }

    cv.GaussianBlur(gray, blur, { width: 5, height: 5 }, 0)
    cv.Canny(blur, edges, EDGE_LOW, EDGE_HIGH)
    const kernel = cv.getStructuringElement(cv.MORPH_RECT, { width: 3, height: 3 })
    cv.dilate(edges, edges, kernel)
    kernel.delete()

    const contours = new cv.MatVector()
    const hierarchy = new cv.Mat()
    cv.findContours(edges, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    // 2026-09-07: top-3 approx 4-point contours（淨揀最大會 miss — 背景 contour 搶位）→ 逐個 checks
    const cands: { pts: QuadPt[]; area: number; mat: any }[] = []
    const pushCand = (c: { pts: QuadPt[]; area: number; mat: any }) => {
      cands.push(c)
      cands.sort((a, b) => b.area - a.area)
      if (cands.length > 3) cands.pop()!.mat.delete()
    }
    for (let i = 0; i < contours.size(); i++) {
      const c = contours.get(i)
      const area = cv.contourArea(c)
      if (area < (dw * dh) * 0.06) continue
      let touches = false
      const len = c.data32S.length / 2
      for (let k = 0; k < len && !touches; k++) {
        const px = c.data32S[k * 2]
        const py = c.data32S[k * 2 + 1]
        if (px <= 1 || py <= 1 || px >= dw - 2 || py >= dh - 2) touches = true
      }
      if (touches) continue
      const peri = cv.arcLength(c, true)
      const approx = new cv.Mat()
      cv.approxPolyDP(c, approx, 0.02 * peri, true)
      if (approx.rows === 4) {
        const pts: QuadPt[] = []
        for (let k = 0; k < 4; k++) {
          pts.push({ x: approx.data32S[k * 2] * scale, y: approx.data32S[k * 2 + 1] * scale })
        }
        pushCand({ pts: orderTLTRBRBL(pts), area, mat: approx })
      } else {
        approx.delete()
      }
    }
    if (!cands.length) { contours.delete(); hierarchy.delete(); return { ok: false, reason: 'no-quad', luma } }
    // 逐個 checks — 第一個 pass 就 green
    let lastRes: FrameCheck | null = null
    for (const cd of cands) {
      const chk = runChecks(cd.pts, guideCss, luma)
      if (chk.ok) {
        cd.mat.delete()
        cands.forEach(x => { if (x !== cd) x.mat.delete() })
        contours.delete()
        hierarchy.delete()
        return chk
      }
      if (!lastRes) lastRes = chk
    }
    cands.forEach(x => x.mat.delete())
    contours.delete()
    hierarchy.delete()
    return lastRes ?? { ok: false, reason: 'no-quad', luma }
  } finally {
    src.delete()
    gray.delete()
    blur.delete()
    edges.delete()
  }
}

function meanLuma(gray: any, cv: any): number {
  const m = new cv.Mat()
  cv.meanStdDev(gray, m)
  const v = m.data64F ? m.data64F[0] : (m.data as any)?.[0] ?? 0
  m.delete()
  return v
}

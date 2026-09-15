// ═══════════════════════════════════════════════════════
// cropCard.ts — OpenCV.js perspective crop（名片自動裁切）
// Microsoft Lens 式：auto-detect 四角 → 用戶微調 → warp 出 flat 名片
// ═══════════════════════════════════════════════════════
import type { QuadPt } from './detectQuad'

/** 名片目標尺寸 — 保持 detect 到嘅 aspect（clamp 1.3–2.2），長邊 ≤1400（OCR 解像度夠） */
export function dstSizeFor(quadPx: QuadPt[]): { w: number; h: number } {
  const [tl, tr, br, bl] = quadPx
  const top = Math.hypot(tr.x - tl.x, tr.y - tl.y)
  const bottom = Math.hypot(br.x - bl.x, br.y - bl.y)
  const left = Math.hypot(bl.x - tl.x, bl.y - tl.y)
  const right = Math.hypot(br.x - tr.x, br.y - tr.y)
  const longEdge = Math.max(top, bottom, left, right)
  const shortEdge = Math.max(10, Math.min(top, bottom, left, right))
  const aspect = Math.min(2.2, Math.max(1.3, longEdge / shortEdge))
  // 橫卡（top+bottom 係長邊）→ w>h；直卡 → h>w（用 aspect 決定）
  const landscape = top + bottom >= left + right
  const long = 1200
  const short = Math.round(long / aspect)
  return landscape ? { w: long, h: short } : { w: short, h: long }
}

/**
 * OpenCV.js warpPerspective：source 全圖 + 4 角（圖像 px，TL/TR/BR/BL）→ 裁出名片。
 * cv 必須已 ready（caller 保證）。返回 output canvas。
 */
export function warpQuad(cv: any, src: HTMLCanvasElement | HTMLImageElement, quadPx: QuadPt[]): HTMLCanvasElement {
  const { w: dstW, h: dstH } = dstSizeFor(quadPx)
  const srcMat = cv.imread(src)
  try {
    const srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
      quadPx[0].x, quadPx[0].y, // TL
      quadPx[1].x, quadPx[1].y, // TR
      quadPx[2].x, quadPx[2].y, // BR
      quadPx[3].x, quadPx[3].y, // BL
    ])
    const dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
      0, 0,
      dstW - 1, 0,
      dstW - 1, dstH - 1,
      0, dstH - 1,
    ])
    try {
      const M = cv.getPerspectiveTransform(srcPts, dstPts)
      try {
        const dst = new cv.Mat()
        cv.warpPerspective(srcMat, dst, M, new cv.Size(dstW, dstH), cv.INTER_LINEAR)
        try {
          const out = document.createElement('canvas')
          out.width = dstW
          out.height = dstH
          cv.imshow(out, dst)
          return out
        } finally { dst.delete() }
      } finally { M.delete() }
    } finally { srcPts.delete(); dstPts.delete() }
  } finally { srcMat.delete() }
}

/**
 * Crop helper：由原圖 dataUrl + 4 角（圖像 px）→ crop dataUrl（jpeg 0.9）。
 * cv 未 ready / warp fail → 返回 null（caller fallback 原圖）。
 */
/**
 * Canvas fallback：OpenCV 唔可用時，至少做 bounding-box 裁剪裁走背景
 * （冇透視矯正，但用戶一定見到「修剪咗」嘅效果 — 2026-09-10 Terrence:
 * 見唔到修剪版本就唔知 confirm 咩）。
 */
function bboxCropDataUrl(img: HTMLImageElement, quadPx: QuadPt[]): string | null {
  try {
    const xs = quadPx.map(p => p.x), ys = quadPx.map(p => p.y)
    const x0 = Math.max(0, Math.floor(Math.min(...xs)))
    const y0 = Math.max(0, Math.floor(Math.min(...ys)))
    const x1 = Math.min(img.naturalWidth, Math.ceil(Math.max(...xs)))
    const y1 = Math.min(img.naturalHeight, Math.ceil(Math.max(...ys)))
    const w = x1 - x0, h = y1 - y0
    if (w < 24 || h < 24) return null
    const c = document.createElement('canvas')
    c.width = w; c.height = h
    const ctx = c.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(img, x0, y0, w, h, 0, 0, w, h)
    const d = c.toDataURL('image/jpeg', 0.9)
    return d && d.length > 200 ? d : null
  } catch {
    return null
  }
}

export async function cropCardDataUrl(
  cv: any | null,
  srcDataUrl: string,
  quadPx: QuadPt[],
): Promise<string | null> {
  // 1. 讀圖（兩個 path 都用）
  let img: HTMLImageElement
  try {
    img = new Image()
    img.src = srcDataUrl
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej })
    if (!img.naturalWidth) img = null as unknown as HTMLImageElement
  } catch {
    return null
  }
  if (!img) return null
  // 2. OpenCV warp（透視矯正 — 最佳）；唔可用／失敗 → canvas bbox fallback
  if (cv && cv.Mat) {
    try {
      /* iOS Safari 對大圖 raw imread（iPhone 12MP = 4032×3024）會爆 canvas
         記憶體 → warp 靜靜失敗 → 顯示原圖。先 downscale 到長邊 ≤2000 再
         imread，四角座標同步縮放（輸出 1200 長邊，2000 來源質素足夠）。 */
      const MAX = 2000
      const iw = img.naturalWidth, ih = img.naturalHeight
      const k = Math.min(1, MAX / Math.max(iw || 1, ih || 1))
      let source: HTMLImageElement | HTMLCanvasElement = img
      let quad = quadPx
      if (k < 1) {
        const scaled = document.createElement('canvas')
        scaled.width = Math.max(1, Math.round(iw * k))
        scaled.height = Math.max(1, Math.round(ih * k))
        const sctx = scaled.getContext('2d')
        if (sctx) {
          sctx.drawImage(img, 0, 0, scaled.width, scaled.height)
          source = scaled
          quad = quadPx.map(p => ({ x: p.x * k, y: p.y * k }))
        }
      }
      const out = warpQuad(cv, source, quad)
      const durl = out.toDataURL('image/jpeg', 0.9)
      if (durl && durl.length > 200) return durl
      console.warn('[crop-card] toDataURL empty — trying bbox fallback')
    } catch (e) {
      console.warn('[crop-card] warp failed — trying bbox fallback', e)
    }
  }
  return bboxCropDataUrl(img, quadPx)
}

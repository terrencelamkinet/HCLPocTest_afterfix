// ═══════════════════════════════════════════════════════
// ManualCorners.tsx — 名片裁剪微調（Microsoft Lens 式）
// Auto-detect 四角後顯示 4 個可拖動 handles — 用戶微調 → 確認先 crop
// 座標系統：全部用「圖像像素 px」（img natural size）— 顯示時 scale 去容器
//
// 2026-09-10 Terrence 真機反饋:
//  - 加放大鏡（iPhone select-text 式）— 拉角時睇到亞像素級位置
//  - confirm button 之前 className="save" 冇 CSS（要 .cam-actions .save 父層）
//    → 完全冇樣式，用戶以為冇確認制。改 mc-confirm + 專用 CSS。
// ═══════════════════════════════════════════════════════
import { useState, useRef, useCallback } from 'react'
import type { QuadPt } from './detectQuad'

interface Props {
  imageUrl: string        // 原圖（未 crop）
  imgW: number            // 圖像 natural width
  imgH: number            // 圖像 natural height
  initial: QuadPt[] | null // auto-detect 四角（圖像 px — TL/TR/BR/BL；null = 全圖）
  onChange?: (cornersPx: QuadPt[]) => void
  onConfirm?: (cornersPx: QuadPt[]) => void
  busy?: boolean
  confirmLabel?: string
}

const HANDLE_COLORS = ['#22C55E', '#22C55E', '#22C55E', '#22C55E'] // 全部綠 — 可拖
const MAG_R = 58        // 放大鏡半徑（px）
const MAG_ZOOM = 3      // 放大倍數
const MAG_GAP = 64      // 放大鏡喺手指上方幾遠

export default function ManualCorners({ imageUrl, imgW, imgH, initial, onChange, onConfirm, busy, confirmLabel }: Props) {
  // corners 存圖像 px — 初始：auto quad 或者全圖邊緣（±2% margin）
  const fullQuad = (): QuadPt[] => [
    { x: imgW * 0.02, y: imgH * 0.02 },
    { x: imgW * 0.98, y: imgH * 0.02 },
    { x: imgW * 0.98, y: imgH * 0.98 },
    { x: imgW * 0.02, y: imgH * 0.98 },
  ]
  const [corners, setCorners] = useState<QuadPt[]>(() => {
    if (initial && initial.length === 4) return initial
    return fullQuad()
  })
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  /* 放大鏡：跟手指（container 相對座標）+ 對應圖像 px */
  const [mag, setMag] = useState<{ cx: number; cy: number; px: number; py: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const scaleRef = useRef(1) // CSS px → 圖像 px 比例（顯示座標 = 圖像 px / scale）
  const cornersRef = useRef(corners)
  cornersRef.current = corners

  // 計算顯示 scale（fit container — 留 padding 俾 handles）
  const layoutRef = useRef({ w: 1, h: 1 })
  const [scale, setScale] = useState(1)
  const [box, setBox] = useState({ w: 1, h: 1 })
  const [cont, setCont] = useState({ w: 1, h: 1 })

  const measure = useCallback(() => {
    const el = boxRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setCont({ w: r.width, h: r.height })
    const pad = 24 // handles 一半 + 邊界
    const availW = Math.max(50, r.width - pad * 2)
    const availH = Math.max(50, r.height - pad * 2)
    const s = Math.min(availW / imgW, availH / imgH)
    scaleRef.current = s
    setScale(s)
    setBox({ w: imgW * s, h: imgH * s })
    layoutRef.current = { w: imgW * s, h: imgH * s }
  }, [imgW, imgH])

  const onPointerDown = (e: React.PointerEvent, idx: number) => {
    e.preventDefault()
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    setDragIdx(idx)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragIdx === null) return
    const el = boxRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // overlay 左上角 = box 中心偏移（圖片置中）
    const ox = r.left + (r.width - layoutRef.current.w) / 2
    const oy = r.top + (r.height - layoutRef.current.h) / 2
    const s = scaleRef.current
    const px = Math.min(imgW, Math.max(0, (e.clientX - ox) / s))
    const py = Math.min(imgH, Math.max(0, (e.clientY - oy) / s))
    const next = cornersRef.current.map((c, i) => (i === dragIdx ? { x: Math.round(px), y: Math.round(py) } : c)) as QuadPt[]
    setCorners(next)
    onChange?.(next)
    /* 放大鏡跟手（container 相對座標） */
    setMag({ cx: e.clientX - r.left, cy: e.clientY - r.top, px, py })
  }
  const onPointerUp = () => { setDragIdx(null); setMag(null) }

  // img 載入後 measure
  const [loaded, setLoaded] = useState(false)

  return (
    <div
      ref={boxRef}
      className="mc-wrap"
      style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', touchAction: 'none' }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <img
        src={imageUrl}
        alt="名片"
        onLoad={() => { setLoaded(true); requestAnimationFrame(measure) }}
        style={{
          position: 'absolute', left: '50%', top: '50%',
          transform: `translate(-50%, -50%) scale(${1})`,
          width: box.w || 'auto', height: box.h || 'auto',
          maxWidth: 'none',
        }}
        draggable={false}
      />
      {loaded && (
        <svg
          width="100%" height="100%"
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
        >
          {/* overlay 原點 = 圖片左上角（置中後） */}
          <g transform={`translate(${(cont.w - box.w) / 2}, ${(cont.h - box.h) / 2})`}>
            <polygon
              points={corners.map(c => `${c.x * scale},${c.y * scale}`).join(' ')}
              fill="rgba(34,197,94,0.08)" stroke="#22C55E" strokeWidth={2}
              strokeDasharray="6 3"
            />
            {corners.map((c, i) => (
              <g
                key={i}
                transform={`translate(${c.x * scale}, ${c.y * scale})`}
                style={{ pointerEvents: 'auto', cursor: dragIdx === i ? 'grabbing' : 'grab' }}
                onPointerDown={e => onPointerDown(e, i)}
              >
                <circle r={14} fill="rgba(255,255,255,0.9)" stroke={HANDLE_COLORS[i]} strokeWidth={2} />
                <circle r={5} fill={HANDLE_COLORS[i]} />
              </g>
            ))}
          </g>
        </svg>
      )}
      {/* 放大鏡 — iPhone select-text 式：拉角時浮喺手指上方 */}
      {mag && dragIdx !== null && (
        <div
          className="mc-mag"
          style={{
            position: 'absolute',
            left: mag.cx - MAG_R,
            top: mag.cy - MAG_R - MAG_GAP,
            width: MAG_R * 2, height: MAG_R * 2,
            borderRadius: '50%',
            overflow: 'hidden',
            border: '2px solid rgba(255,255,255,.9)',
            boxShadow: '0 6px 20px rgba(0,0,0,.55)',
            pointerEvents: 'none',
            zIndex: 5,
            background: '#111',
          }}
        >
          <img
            src={imageUrl}
            alt=""
            draggable={false}
            style={{
              position: 'absolute',
              width: imgW * scale * MAG_ZOOM,
              height: imgH * scale * MAG_ZOOM,
              left: MAG_R - mag.px * scale * MAG_ZOOM,
              top: MAG_R - mag.py * scale * MAG_ZOOM,
              maxWidth: 'none',
            }}
          />
          {/* 十字準星 */}
          <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: 'rgba(34,197,94,.85)' }} />
          <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 1, background: 'rgba(34,197,94,.85)' }} />
        </div>
      )}
      <div className="mc-hint" style={{ position: 'absolute', left: 12, top: 8, fontSize: 12, color: 'rgba(255,255,255,0.9)', background: 'rgba(0,0,0,0.45)', padding: '4px 10px', borderRadius: 999, pointerEvents: 'none' }}>
        自動對位完成 — 拖動 4 個角微調（如需要）
      </div>
      {onConfirm && (
        <div className="mc-actions" style={{ position: 'absolute', bottom: 12, left: 0, right: 0, display: 'flex', justifyContent: 'center' }}>
          <button
            type="button"
            className="mc-confirm"
            onClick={() => onConfirm?.(cornersRef.current)}
            disabled={busy}
          >
            {busy ? '裁剪中…' : (confirmLabel || '✓ 確認裁剪')}
          </button>
        </div>
      )}
    </div>
  )
}

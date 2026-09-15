import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import SvcIcon from '../../components/SvcIcon';
import { apiClient } from '../../lib/api';
import { useTranslation } from 'react-i18next';
import { computeGuide, analyzeLiteFrame, analyzeFrame, type GuideRect, type FrameCheck, type QuadPt } from './scan/detectQuad';
import ManualCorners from './scan/ManualCorners';
import { cropCardDataUrl } from './scan/cropCard';
import { loadOpenCv } from '../../lib/opencvLoader';

/**
 * 拍卡片 → AI OCR → 自動入庫（v6.69）
 * - getUserMedia 開後置鏡頭 → canvas capture → FormData
 * - POST /api/v1/crm/name-cards/upload（既有 backend：OCR + 自動建立/連結 Contact）
 * - 顯示 OCR 結果；「儲存為聯絡人」= 關閉（backend 已寫入），「重拍」= 再影
 *
 * Cam-level 四角 detection（SPEC docs/namecard-scan-cam-detect-SPEC.md）:
 * - preview 即時偵測卡片 → guide 4 角 灰（searching）/ 綠（aligned）
 * - 綠先可以影（普通撳）；灰 frame 長撳 1 秒 = 強制影（bypass）
 * - green-enter → haptic；capture 前嘗試對焦文字區（iOS Safari 冇 API → 自動 skip）
 */

interface NameCardResult {
  status?: string;
  contact_id?: string | null;
  duplicate_candidate?: { contact_id?: string; reason?: string } | null;
  parsed_data?: Record<string, any> | null;
  /* SPEC namecard-scan A+B: 影後 preview + crop 圖顯示 */
  image_url?: string;
  cropped_image_url?: string;
  display_image?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (label: string) => void;
  /** 'upload'（default）: 掃完 → name-cards/upload（入庫 + 背景識別）；'fill' : 掃完 → scan-name-card（AI 填 form） */
  mode?: 'upload' | 'fill';
  /** mode='fill' — OCR 完成（fields/relations 填 form） */
  onFilled?: (data: any) => void;
  /** fill mode 用嘅 module 名（scan-name-card 要 module=contact 等） */
  fillModule?: string;
  /** 有值 = image mode（唔開 camera — 直接用呢張圖入 adjust/crop flow — desktop 上載用） */
  initialImage?: string | null;
}

export default function CameraScanSheet({ open, onClose, onSaved, mode = 'upload', onFilled, fillModule = 'contact', initialImage = null }: Props) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<NameCardResult | null>(null);
  const [closing, setClosing] = useState(false);
  /* SPEC namecard-scan B: 影後 preview — 用戶確認先用（唔好朦相直接 upload 等 15 秒先發現） */
  const [captured, setCaptured] = useState<string | null>(null);
  const blobRef = useRef<Blob | null>(null);
  /* Lens 式裁剪: cropPreview null = adjust 階段（ManualCorners）；有 = 已 crop 顯示 */
  const [cropPreview, setCropPreview] = useState<string | null>(null);
  const [adjustCorners, setAdjustCorners] = useState<QuadPt[] | null>(null);
  const [imgSize, setImgSize] = useState({ w: 1, h: 1 });
  const quadPxRef = useRef<QuadPt[] | null>(null); // 最後 detect 到嘅 quad（圖像 px）

  /* ── Cam-level 四角 detection（SPEC docs/namecard-scan-cam-detect-SPEC.md） ── */
  const [alignState, setAlignState] = useState<'searching' | 'aligned'>('searching');
  /* 每隻角達標未 [TL, TR, BR, BL] — 逐隻角變綠引導用戶放入框（2026-09-10） */
  const [cornerOk, setCornerOk] = useState<boolean[]>([false, false, false, false]);
  const [guideRect, setGuideRect] = useState<GuideRect | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const alignStateRef = useRef<'searching' | 'aligned'>('searching');
  const guideRectRef = useRef<GuideRect | null>(null);
  const passStreakRef = useRef(0);
  /** OpenCV frame 連續錯誤計數（≥8 先降級 lite — 唔可以一次就清 cvRef） */
  const cvFailStreakRef = useRef(0);
  const failStreakRef = useRef(0);

  /* ── T2: OpenCV.js 兩段式引擎 — 後台載入（dynamic import — 唔入主 bundle）→ ready 自動切換 ── */
  const cvRef = useRef<any>(null);
  const [engine, setEngine] = useState<'lite' | 'opencv'>('lite');
  const [engineStatus, setEngineStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [lastReason, setLastReason] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setEngineStatus('loading');
    (async () => {
      try {
        const cv: any = await loadOpenCv();
        if (cancelled) return;
        cvRef.current = cv;
        setEngine('opencv');
        setEngineStatus('ready');
        console.log('[namecard-cam] OpenCV engine ready');
      } catch (e) {
        if (!cancelled) {
          setEngineStatus('failed');
          console.warn('[namecard-cam] OpenCV load failed — staying on lite engine', e);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  /* Guide rect — video mount 後計（78% 短邊, aspect 1.67, 置中） */
  useEffect(() => {
    if (!open || captured || result) return;
    const raf = requestAnimationFrame(() => {
      const v = videoRef.current;
      if (!v) return;
      const cw = v.clientWidth, ch = v.clientHeight;
      if (cw > 0 && ch > 0) {
        const g = computeGuide(cw, ch);
        guideRectRef.current = g;
        setGuideRect(g);
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [open, captured, result]);

  /* Detection loop — 每 ~110ms 一 frame；hysteresis: 3 連綠入 / 2 連灰出 */
  useEffect(() => {
    if (!open || captured || result || !guideRect) return;
    passStreakRef.current = 0;
    failStreakRef.current = 0;
    setCornerOk([false, false, false, false]);
    setAlignState('searching');
    setHint(null);
    alignStateRef.current = 'searching';
    const timer = window.setInterval(() => {
      const v = videoRef.current;
      const g = guideRectRef.current;
      if (!v || !v.videoWidth || !g) return;
      let check: FrameCheck;
      try {
        // T2: OpenCV ready → 自動用 OpenCV（更穩 — 容 tilt/複雜背景）；未 ready → lite
        const cv = cvRef.current;
        check = cv ? analyzeFrame(cv, v, g) : analyzeLiteFrame(v, g);
      } catch (e) {
        // 2026-09-07 fix: OpenCV crash → fallback lite（唔好成個 detect 死）
        // 2026-09-10 fix: 唔可以一次 crash 就將 cvRef 清走 —— 之前會令之後嘅
        // crop（confirmCrop 用 cvRef）永遠攞唔到 cv → 「剪完顯示原圖」。改為
        // 連續多次失敗先降級，成功一次即 reset。
        console.warn('[namecard-cam] engine frame error', e);
        cvFailStreakRef.current += 1;
        if (cvFailStreakRef.current >= 8) {
          setEngine('lite');
        }
        try { check = analyzeLiteFrame(v, g); } catch { return; }
      }
      cvFailStreakRef.current = 0;
      /* 每 frame 更新逐角狀態（有 quad 就報）— 等用戶睇到邊隻角入咗框 */
      setCornerOk(check.cornerOk && check.cornerOk.length === 4 ? check.cornerOk : [false, false, false, false]);
      if (check.ok) {
        passStreakRef.current += 1;
        failStreakRef.current = 0;
        setLastReason(null);
        // 儲低 quad corners（CSS px — 顯示比例）→ capture 時轉圖像 px 做 crop
        if (check.quad?.length === 4 && v.videoWidth) {
          // CSS overlay px -> video frame px。
          // Video 用 object-fit:cover（同 drawCoverFrame 一致）— 必須計 cover
          // scale + 置中裁切 offset，否則 y 偏差（舊 code 淨係乘一個 sx —
          // 真機症狀「4 點完全唔係所拍嘅位置」就係呢個 bug）。
          const cw = v.clientWidth, ch = v.clientHeight;
          const vw = v.videoWidth, vh = v.videoHeight;
          const cover = Math.max(cw / vw, ch / vh) || 1;
          const offX = (vw * cover - cw) / 2;
          const offY = (vh * cover - ch) / 2;
          quadPxRef.current = check.quad.map(p => ({
            x: Math.round((p.x + offX) / cover),
            y: Math.round((p.y + offY) / cover),
          }));
        }
        if (passStreakRef.current >= 3 && alignStateRef.current !== 'aligned') {
          alignStateRef.current = 'aligned';
          setAlignState('aligned');
          try { navigator.vibrate?.(30); } catch { /* haptic optional */ }
        }
      } else {
        failStreakRef.current += 1;
        passStreakRef.current = 0;
        // debug 可見性: 灰 frame 顯示 detect reason（用戶報「綠唔到」時一眼睇到邊個 check fail）
        setLastReason(check.reason || 'fail');
        if (failStreakRef.current >= 2 && alignStateRef.current !== 'searching') {
          alignStateRef.current = 'searching';
          setAlignState('searching');
        }
      }
    }, 110);
    return () => window.clearInterval(timer);
  }, [open, captured, result, guideRect]);

  /* 綠區穩定 3 秒 → 自動拍攝（動畫倒數 — 無數字）
     Browser 唔支援長撳（iOS context menu / text selection）→ 取消長撳強制，
     綠區停留 3s 自動影；任何時候亦可人手按下拍攝。 */
  const [autoProgress, setAutoProgress] = useState(0);
  const autoRafRef = useRef<number | null>(null);
  useEffect(() => {
    if (!open || captured || result || busy || alignState !== 'aligned') {
      setAutoProgress(0);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / 3000);
      setAutoProgress(p);
      if (p >= 1) {
        autoRafRef.current = null;
        void capture(false);
      } else {
        autoRafRef.current = requestAnimationFrame(tick);
      }
    };
    autoRafRef.current = requestAnimationFrame(tick);
    return () => {
      if (autoRafRef.current !== null) { cancelAnimationFrame(autoRafRef.current); autoRafRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, alignState, captured, result, busy]);

  /* 人手按下 = 立即拍攝（唔理灰/綠 — 用戶決定） */
  const handleShutter = useCallback(() => {
    void capture(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!open) return;
    setError(null); setResult(null); setBusy(false); setCaptured(null); setCropPreview(null); blobRef.current = null;
    quadPxRef.current = null;
    if (initialImage) {
      // image mode（desktop 上載）: 唔開 camera — 直接入 adjust/crop flow
      const img = new Image();
      img.onload = () => {
        setImgSize({ w: img.naturalWidth, h: img.naturalHeight });
        setAdjustCorners(null); // 全圖 corners — 用戶拖 4 角微調
        setCaptured(initialImage);
      };
      img.onerror = () => { setError('圖片讀取失敗'); };
      img.src = initialImage;
      return;
    }
    startCamera();
    return () => {
      streamRef.current?.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /* 鏡頭控制 — 分開 function 等 retake 可以重新開（iOS capture 後 stream 會 freeze） */
  const stopCamera = () => {
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  };

  const startCamera = async () => {
    stopCamera();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
    } catch {
      setError('無法開啟鏡頭 — 請檢查瀏覽器權限');
    }
  };

  const handleClose = () => {
    if (closing) return;
    setClosing(true);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    setTimeout(() => { setClosing(false); onClose(); }, 200);
  };

  const capture = async (force = false) => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) { setError('鏡頭未就緒，再試一次'); return; }
    if (!force && alignStateRef.current !== 'aligned') {
      setHint('尚未對準 — 已為您拍攝，建議重新對齊可提升辨識率');
    }
    setError(null);
    setHint(null);
    try {
      /* Cam-level: capture 前嘗試對焦文字區（guide §4.3 — Chrome/Android POI；iOS Safari 冇 API → skip 照影） */
      try {
        const track = streamRef.current?.getVideoTracks()[0] as any;
        if (track?.getCapabilities) {
          const caps = track.getCapabilities() || {};
          const adv: Record<string, unknown>[] = [];
          if (Array.isArray(caps.focusMode) && caps.focusMode.includes('single-shot')) adv.push({ focusMode: 'single-shot' });
          else if (Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) adv.push({ focusMode: 'continuous' });
          if (caps.pointsOfInterest) adv.push({ pointsOfInterest: [{ x: 0.5, y: 0.4 }] });
          if (adv.length && track.applyConstraints) {
            await track.applyConstraints({ advanced: adv });
            await new Promise(r => setTimeout(r, 280)); // lens settle
          }
        }
      } catch { /* 照影 — 唔 block */ }
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d')?.drawImage(video, 0, 0);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
      const blob = await new Promise<Blob | null>(res => canvas.toBlob(res, 'image/jpeg', 0.85));
      if (!blob) throw new Error('capture failed');
      blobRef.current = blob;
      setImgSize({ w: canvas.width, h: canvas.height });
      // Lens 式: capture 後先顯示 adjust（四角 handles）— cropPreview null = 未 crop
      setAdjustCorners(quadPxRef.current);   // auto-detect quad（可能 null → ManualCorners 用全圖）
      setCropPreview(null);
      setCaptured(dataUrl);   // preview 階段 = 微調四角
      stopCamera();           // bug fix: preview 期間熄鏡頭 — retake 先重新開（iOS stream freeze 問題）
    } catch (e: any) {
      setError(e?.message || '拍攝失敗，請再試一次');
    }
  };

  /* Lens 式: 用戶確認微調 → OpenCV warpPerspective 裁出名片 → 顯示 crop → 先 OCR */
  const confirmCrop = async (cornersPx: QuadPt[]) => {
    const orig = captured;
    if (!orig) return;
    setBusy(true); setError(null);
    try {
      let cv = cvRef.current;
      if (!cv) {
        // detection 期間 engine 降級過都唔應該影響裁剪 — 直接向 loader 攞
        try { cv = await loadOpenCv(); } catch { cv = null; }
      }
      const cropped = await cropCardDataUrl(cv, orig, cornersPx);
      if (cropped && cropped !== orig) {
        // crop 成功 → 用 crop 圖做 OCR 源（blobRef 換 crop 版）
        const cblob = await new Promise<Blob | null>(res => {
          const img = new Image();
          img.onload = () => {
            const c = document.createElement('canvas');
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            c.getContext('2d')?.drawImage(img, 0, 0);
            c.toBlob(res, 'image/jpeg', 0.9);
          };
          img.onerror = () => res(null);
          img.src = cropped;
        });
        if (cblob) blobRef.current = cblob;
        setCropPreview(cropped);
      } else {
        setCropPreview(orig); // OpenCV 未 ready / fail → 原圖照用
        setHint('未能自動裁剪（已用原圖）— 可直接識別');
      }
    } catch (e: any) {
      setError(e?.message || '裁剪失敗 — 用原圖繼續');
      setCropPreview(orig);
    } finally {
      setBusy(false);
    }
  };

  const runOcr = async () => {
    const blob = blobRef.current;
    if (!blob) { setError('影像未就緒'); return; }
    setBusy(true); setError(null);
    try {
        const fd = new FormData();
      fd.append('file', blob, 'namecard.jpg');
      /* 用戶喺微調頁確認過嘅裁剪版本 = 最終顯示圖（唔好再由 backend 自動
         crop 覆蓋）— 2026-09-10 Terrence: 「剪完要見剪輯效果」 */
      if (cropPreview && cropPreview !== captured) fd.append('cropped', '1');
      if (mode === 'fill') {
        /* fill mode: Add modal — scan-name-card → AI 填 form（用戶 review 先 save） */
        fd.append('module', fillModule);
        const data = await apiClient.postForm<any>('/api/v1/ai/scan-name-card', fd);
        if (data?.fields || data?.result) {
          handleClose();
          onFilled?.(data);
          return;
        }
        setResult(data || {});
        return;
      }
      /* upload mode: name-cards/upload（既有 backend：OCR + 自動建立/連結 Contact） */
      const data = await apiClient.postForm<any>('/api/v1/crm/name-cards/upload', fd);
      if (data?.status === 'processing' || data?.ok) {
        handleClose();
        onSaved('名片已收到 — 背景識別緊');
        return;
      }
      setResult(data || {});
    } catch (e: any) {
      setError(e?.message || 'OCR 失敗，請再試一次');
    } finally {
      setBusy(false);
    }
  };

  const retake = () => { setResult(null); setCaptured(null); setCropPreview(null); blobRef.current = null; setError(null); quadPxRef.current = null; startCamera(); };

  /* v6.82: lock background scroll while camera sheet is open */
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  if (!open) return null;

  const parsed = result?.parsed_data || {};
  const personName =
    parsed?.name || parsed?.person_name || parsed?.full_name ||
    (result?.duplicate_candidate ? '重複聯絡人' : '已識別名片');

  const saveLabel = result?.duplicate_candidate
    ? `⚠️ 可能重複：${result.duplicate_candidate.reason || '同名/同 email'} — 已連結現有聯絡人`
    : '聯絡人已建立';

  return createPortal(
    <div className={`cam-overlay ${closing ? 'closing' : ''}`} onClick={handleClose}>
      <div className={`cam-panel ${closing ? 'closing' : ''}`} onClick={e => e.stopPropagation()}>
        <div className="cam-handle" />
        <div className="cam-head">
          <h3>{t('nameCard.scanCardAi', { defaultValue: '拍卡片 · AI 自動識別' })}</h3>
          <button type="button" className="cam-close" onClick={handleClose} aria-label="Close"><SvcIcon name="x" /></button>
        </div>
        <div className="cam-body">
          {!result && !captured ? (
            <>
              {/* SPEC namecard-scan A: 鏡頭 live — 4 角 guide 框（cam-level detect 綠/灰）+ 對準提示 */}
              <div className="cam-frame">
                <video ref={videoRef} playsInline muted />
                <div
                  className={`cam-card-outline ${alignState === 'aligned' ? 'aligned' : ''}`}
                  style={guideRect ? { left: guideRect.x, top: guideRect.y, width: guideRect.w, height: guideRect.h } : undefined}
                >
                  <span className={`cam-corner tl${cornerOk[0] ? ' ok' : ''}`} />
                  <span className={`cam-corner tr${cornerOk[1] ? ' ok' : ''}`} />
                  <span className={`cam-corner bl${cornerOk[3] ? ' ok' : ''}`} />
                  <span className={`cam-corner br${cornerOk[2] ? ' ok' : ''}`} />
                  {/* 埋邊對位（2026-09-13）: 內縮安全框 — 卡邊入到框內、留約 8% 邊距 */}
                  <div className="cam-safe-inner" />
                  <div className="cam-size-chip">{t('nameCard.cardSizeHk', { defaultValue: '香港卡 90×54mm' })}</div>
                  {alignState !== 'aligned' && <div className="cam-scan-line" />}
                </div>
                {alignState === 'aligned' && (
                  <div className="cam-ok-pill">
                    <svg className="cam-count-ring" viewBox="0 0 36 36" aria-hidden="true">
                      <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,.28)" strokeWidth="3.4" />
                      <circle cx="18" cy="18" r="15" fill="none" stroke="#22c55e" strokeWidth="3.4"
                        strokeDasharray={94.25}
                        strokeDashoffset={94.25 * (1 - autoProgress)}
                        strokeLinecap="round" transform="rotate(-90 18 18)" />
                    </svg>
                    ✓ 已對齊 — 自動拍攝中，亦可隨時按下
                  </div>
                )}
                <div className="cam-hint">
                  {hint || (alignState === 'aligned'
                    ? '已對準 — 3 秒後自動拍攝'
                    : (() => {
                        const n = cornerOk.filter(Boolean).length;
                        const base = n === 0
                          ? '將名片四角放入框內 — 每隻角到位會變綠'
                          : n === 4
                            ? '四角已就位 — 稍微穩定一下就綠'
                            : `已對準 ${n}/4 角 — 繼續調整其餘 ${4 - n} 隻角`;
                        return lastReason && import.meta.env.DEV ? `${base} · ${lastReason}` : base;
                      })())}
                </div>
                {engine === 'lite' && alignState !== 'aligned' && engineStatus === 'loading' && (
                  <div className="cam-engine-tag">AI 視覺引擎首次載入中（約 10 秒）— 可先按下拍攝，或稍等更準確對位</div>
                )}
                {engine === 'lite' && engineStatus === 'failed' && (
                  <div className="cam-engine-tag">基礎偵測模式</div>
                )}
              </div>
              {error && <div className="aisp-error">{error}</div>}
              <button
                type="button"
                className={`cam-shutter ${alignState === 'aligned' ? 'ready' : ''}`}
                onClick={handleShutter}
                disabled={busy}
              >
                {busy ? '識別中…' : (alignState === 'aligned' ? '📸 立即拍攝' : '📸 拍攝名片')}
              </button>
            </>
          ) : !result && captured && !cropPreview ? (
            <>
              {/* Lens 式（2026-09-07 spec）: 自動對位 → 拖 4 角微調 → 確認裁剪先 OCR */}
              <div className="cam-frame">
                <ManualCorners
                  imageUrl={captured}
                  imgW={imgSize.w}
                  imgH={imgSize.h}
                  initial={adjustCorners}
                  onConfirm={c => { void confirmCrop(c) }}
                  busy={busy}
                  confirmLabel="✓ 確認裁剪 — 開始識別"
                />
                <div className="cam-hint" style={{ bottom: 8, top: 'auto' }}>拖動角位微調（如需要）— 確認後自動裁正名片</div>
              </div>
              {error && <div className="aisp-error">{error}</div>}
              <div className="cam-actions" style={{ marginTop: 0, justifyContent: 'center' }}>
                <button type="button" className="retake" onClick={retake} disabled={busy}><SvcIcon name="rotate-ccw" />{t('nameCard.retake', { defaultValue: '重拍' })}</button>
              </div>
            </>
          ) : !result && captured && cropPreview ? (
            <>
              {/* SPEC namecard-scan B: 已 crop — preview 確認先 OCR（Lens 式最後一步） */}
              <div className="cam-frame">
                <img src={cropPreview} alt="名片預覽" className="cam-preview-img" />
                <div className="cam-hint">裁剪完成 — 用呢張識別？</div>
              </div>
              {error && <div className="aisp-error">{error}</div>}
              <div className="cam-actions" style={{ marginTop: 0 }}>
                <button type="button" className="retake" onClick={retake} disabled={busy}><SvcIcon name="rotate-ccw" />{t('nameCard.retake', { defaultValue: '重拍' })}</button>
                <button type="button" className="save" onClick={runOcr} disabled={busy}>
                  {busy ? (mode === 'fill' ? '識別中…' : '上載中…') : t('nameCard.useThis', { defaultValue: '用呢張識別' })}
                </button>
              </div>
            </>
          ) : (
            <>
              {/* SPEC namecard-scan B: result — 顯示 crop 圖（backend verified crop）+ 欄位 */}
              {(result?.display_image || result?.cropped_image_url || result?.image_url) && (
                <div className="cam-result" style={{ padding: 0, overflow: 'hidden', marginBottom: 10 }}>
                  <img
                    src={result?.display_image || result?.cropped_image_url || result?.image_url}
                    alt="名片"
                    className="cam-result-img"
                  />
                </div>
              )}
              <div className="cam-result">
                <div className="cam-result-head">
                  <SvcIcon name="check-circle-2" /><span>{saveLabel}</span>
                </div>
                {[
                  ['姓名', parsed?.name || parsed?.person_name],
                  ['職位', parsed?.title || parsed?.position],
                  ['公司', parsed?.company || parsed?.organization],
                  ['電話', parsed?.phone || parsed?.mobile],
                  ['Email', parsed?.email],
                ].filter(([, v]) => v).map(([k, v]) => (
                  <div key={k as string} className="cam-field">
                    <span>{k}</span><span>{v}</span>
                  </div>
                ))}
                {!Object.keys(parsed).length && (
                  <div className="cam-field"><span>{t('nameCard.ocrRaw', { defaultValue: 'OCR 原文' })}</span><span>{(result as any).raw_ocr_text || '—'}</span></div>
                )}
              </div>
              <div className="cam-actions">
                <button type="button" className="retake" onClick={retake}><SvcIcon name="rotate-ccw" />{t('nameCard.retake', { defaultValue: '重拍' })}</button>
                <button type="button" className="save" onClick={() => { handleClose(); onSaved(personName); }}>{t('nameCard.saveAsContact', { defaultValue: '儲存為聯絡人' })}</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

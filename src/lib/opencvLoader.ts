/**
 * opencvLoader.ts — 名片掃描用嘅 OpenCV.js 載入器（shared）
 *
 * 背景（2026-09-10 Terrence 真機）:
 *  - 13MB UMD opencv.js 用 dynamic import() 會被 bundler interop 撞爆
 *    ("Promise.prototype.then called on incompatible receiver")
 *  - @techstark 5.x 嘅 window.cv 本身係 Promise — 唔 await 就永遠未 ready
 *  - 首次載入 ~10s（下載 + wasm init）→ 開掃描先載會乾等
 *
 * 對策:
 *  1. <script> tag 載入（繞過 bundler）
 *  2. await window.cv（Promise）
 *  3. App idle 時預載（preloadOpenCv）— 用戶開掃描時通常已 ready
 *  4. Cache API 存一份（唔靠 HTTP cache 過期/revalidate，第二次開 instant）
 */
const SCRIPT_URL = '/vendor/opencv.js';
const CACHE_NAME = 'pcrm-opencv-v1';
const CACHE_KEY = '/__opencv_cache__/opencv.js';

let inflight: Promise<any> | null = null;

/** 由 Cache API 攞（有就即用，冇就 network → 寫 cache） */
async function fetchScriptToBlobUrl(): Promise<string> {
  try {
    const cache = await caches.open(CACHE_NAME);
    const hit = await cache.match(CACHE_KEY);
    if (hit) return URL.createObjectURL(await hit.blob());
    const res = await fetch(SCRIPT_URL, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('opencv fetch ' + res.status);
    const clone = res.clone();
    const buf = await res.arrayBuffer();
    // 寫 cache（背景，唔阻載入）
    cache.put(CACHE_KEY, new Response(clone.body ?? buf, {
      headers: { 'Content-Type': 'text/javascript' },
    })).catch(() => { /* cache 寫入失敗唔緊要 */ });
    return URL.createObjectURL(new Blob([buf], { type: 'text/javascript' }));
  } catch {
    return SCRIPT_URL; // fallback：直接用原 URL（browser HTTP cache）
  }
}

function injectScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-opencv]') as HTMLScriptElement | null;
    if (existing) { resolve(); return; }
    const sc = document.createElement('script');
    sc.src = src;
    sc.async = true;
    sc.dataset.opencv = '1';
    sc.onload = () => resolve();
    sc.onerror = () => reject(new Error('opencv.js script load failed'));
    document.head.appendChild(sc);
  });
}

async function settle(): Promise<any> {
  const w = window as any;
  let cv = w.cv;
  if (!cv) throw new Error('window.cv missing');
  if (cv instanceof Promise || typeof cv.then === 'function') cv = await cv;
  if (cv?.Mat) return cv;
  if (cv && typeof cv.onRuntimeInitialized !== 'undefined') {
    await new Promise<void>(res => {
      const orig = cv.onRuntimeInitialized;
      cv.onRuntimeInitialized = () => { try { orig?.() } catch { /* ignore */ } res(); };
      setTimeout(res, 20000);
    });
  }
  if (cv?.Mat) return cv;
  throw new Error('cv init failed');
}

/** 載入 + 初始化 OpenCV（重複 call 會共用同一個 promise） */
export function loadOpenCv(): Promise<any> {
  if (inflight) return inflight;
  inflight = (async () => {
    const w = window as any;
    if (w.cv) return settle();
    const src = await fetchScriptToBlobUrl();
    await injectScript(src);
    return settle();
  })().catch(e => { inflight = null; throw e; });
  return inflight;
}

/** App 啟動後背景預載 — 唔會 throw，失敗靜靜哋（開掃描時再試） */
export function preloadOpenCv(): void {
  const w = window as any;
  if (w.cv?.Mat || inflight) return;
  const run = () => { loadOpenCv().catch(() => { /* silent */ }); };
  const idle = (window as any).requestIdleCallback;
  if (typeof idle === 'function') idle(run, { timeout: 6000 });
  else setTimeout(run, 2500);
}

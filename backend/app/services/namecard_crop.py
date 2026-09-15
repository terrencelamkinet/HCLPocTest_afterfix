"""Smart namecard cropping with LLM verification loop (max 5 attempts).

v2: baseline-aware verification. First read ALL fields from the full image
(ground truth of what the card contains), then try crops; a crop is complete
only if it preserves every baseline field. Missing field = widen → re-verify.

This fixes v1's flaw: asking the LLM "is anything missing?" is unreliable,
but "does this crop still contain the email that the full image had?" is
concrete and stable.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

_KEY_FIELDS = ["name", "title", "company", "email", "phone", "website", "address", "phone2"]


def _sf_vision(img_bgr: Any, prompt: str, max_tokens: int = 400, timeout: int = 90,
               usage_out: list | None = None) -> str:
    # G08 獨立 key 儲存：provider_credentials cache → env fallback
    from app.services.provider_keys import cached_provider_key

    key = cached_provider_key("siliconflow") or os.environ.get("SILICONFLOW_API_KEY", "")
    if not key:
        return ""
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    b64 = base64.b64encode(buf.tobytes()).decode()
    payload = {
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        r = json.loads(resp.read())
    # Core rule G08: collect SiliconFlow usage for central tracking.
    if usage_out is not None:
        u = r.get("usage") or {}
        usage_out.append({
            "provider": "siliconflow",
            "model": "Qwen/Qwen3-VL-8B-Instruct",
            "input_tokens": int(u.get("prompt_tokens") or 0),
            "output_tokens": int(u.get("completion_tokens") or 0),
            "cost_usd": 0,  # SiliconFlow pricing not in cost cards
        })
    return r["choices"][0]["message"]["content"]


def _read_fields(img_bgr: Any, usage_out: list | None = None) -> dict[str, str]:
    """Read concrete field values from an image (empty string = missing)."""
    prompt = (
        "Read this business card. Return ONLY JSON with these keys (empty string "
        'if absent): {"name":"", "title":"", "company":"", "email":"", '
        '"phone":"", "website":"", "address":"", "phone2":""}'
    )
    try:
        text = _sf_vision(img_bgr, prompt, usage_out=usage_out)
        start, end = text.find("{"), text.rfind("}") + 1
        data = json.loads(text[start:end])
        return {k: str(data.get(k, "")).strip() for k in _KEY_FIELDS}
    except Exception:
        return {}


def _bbox_from_vision(img: Any, usage_out: list | None = None) -> tuple[int, int, int, int] | None:
    prompt = 'Find the business card bounding box. Return ONLY JSON {"bbox": [x1,y1,x2,y2]}.'
    try:
        text = _sf_vision(img, prompt, max_tokens=100, usage_out=usage_out)
        start, end = text.find("{"), text.rfind("}") + 1
        bbox = json.loads(text[start:end])["bbox"]
        x1, y1, x2, y2 = (int(v) for v in bbox)
        if x2 > x1 and y2 > y1:
            return x1, y1, x2, y2
    except Exception:
        pass
    return None


def _opencv_quad(img: Any) -> np.ndarray | None:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for lo, hi in ((50, 150), (30, 90), (20, 60)):
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), lo, hi)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 0.05 * h * w:
            continue
        peri = cv2.arcLength(largest, True)
        approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype("float32")
            s = pts.sum(axis=1)
            d = np.diff(pts, axis=1).ravel()
            return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                             pts[np.argmax(s)], pts[np.argmax(d)]])
    return None


def _warp_crop(img: Any, corners: np.ndarray, pad: float = 0.0) -> Any:
    tl, tr, br, bl = corners[0], corners[1], corners[2], corners[3]
    cw = max(int(np.linalg.norm(tr - tl)), int(np.linalg.norm(br - bl)))
    ch = max(int(np.linalg.norm(bl - tl)), int(np.linalg.norm(br - tr)))
    px, py = int(cw * pad), int(ch * pad)
    dst = np.array([[0, 0], [cw - 1, 0], [cw - 1, ch - 1], [0, ch - 1]], dtype="float32")
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(corners, dst), (cw, ch))
    if pad > 0:
        warped = cv2.copyMakeBorder(warped, py, py, px, px, cv2.BORDER_REPLICATE)
    return warped


def crop_namecard(image_path: str | Path, max_attempts: int = 5,
                  usage_out: list | None = None) -> dict[str, Any]:
    """Crop → LLM verify against full-image baseline → widen if fields lost."""
    img = cv2.imread(str(image_path))
    if img is None:
        return {"error": "cannot read image", "crop": None, "baseline": {}, "attempts": 0}
    h, w = img.shape[:2]

    # Baseline: every field the card has, read from the full frame.
    baseline = _read_fields(img, usage_out=usage_out)
    baseline_present = {k for k, v in baseline.items() if v}
    if not baseline_present:
        return {"error": "no fields readable", "crop": img, "baseline": baseline,
                "attempts": 0, "strategy": "full_image"}

    bbox = _bbox_from_vision(img, usage_out=usage_out)
    quad = _opencv_quad(img)

    strategies: list[tuple[str, Any]] = []
    if quad is not None:
        strategies.append(("opencv_quad", _warp_crop(img, quad, 0.0)))
        strategies.append(("opencv_quad+15%", _warp_crop(img, quad, 0.15)))
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        strategies.append(("vision_bbox", img[y1:y2, x1:x2]))
        for pad in (0.15, 0.40):
            px, py = int((x2 - x1) * pad), int((y2 - y1) * pad)
            x1p, y1p = max(0, x1 - px), max(0, y1 - py)
            x2p, y2p = min(w, x2 + px), min(h, y2 + py)
            strategies.append((f"vision_bbox+{int(pad*100)}%", img[y1p:y2p, x1p:x2p]))
    strategies.append(("full_image", img))

    log = []
    best = (-1, img, baseline, "full_image")
    for i, (name, crop) in enumerate(strategies[:max_attempts]):
        fields = _read_fields(crop, usage_out=usage_out)
        present = {k for k, v in fields.items() if v}
        lost = sorted(baseline_present - present)
        gained = sorted(present - baseline_present)
        score = len(present & baseline_present) - len(lost)
        log.append({"attempt": i + 1, "strategy": name, "score": score,
                    "lost": lost, "gained": gained})
        if score > best[0]:
            best = (score, crop, fields, name)
        if not lost:  # every baseline field preserved → complete
            return {"crop": crop, "fields": fields, "strategy": name,
                    "attempts": i + 1, "score": score, "baseline": baseline,
                    "log": log, "complete": True}
    return {"crop": best[1], "fields": best[2], "strategy": best[3],
            "attempts": len(log), "score": best[0], "baseline": baseline,
            "log": log, "complete": False}

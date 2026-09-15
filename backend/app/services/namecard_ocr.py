"""NameCard OCR — tesseract-based text extraction + structured field parsing.

Fully self-contained in G08 (no link to GG Fighter / Hermes pipelines):
  1. tesseract OCR (chi_tra + eng) → raw text
  2. regex/heuristic parsing → structured fields
     (name, chinese_name, title, company, phone, office_phone, email,
      website, address, linkedin)
  3. Downstream (crm router) creates/links a Contact from the parsed fields.

SOC 2: image files are stored under backend/uploads/namecards/ and served
through an authenticated endpoint — no public static mount.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.services.provider_keys import cached_provider_key  # noqa: E402  (G08 independent key store)

import numpy as np


def _detect_card_region(img: Any) -> Any:
    """Detect the business-card quadrilateral → perspective-cropped copy.

    Real photos have the card lying on a desk/background: background text
    pollutes OCR. This finds the largest 4-corner contour, warp-corrects it
    and returns only the card. Falls back to the original image when no
    confident card boundary exists (card fills the frame, or clean edges
    missing) so we never degrade the current behaviour.
    """
    h, w = img.shape[:2]
    if h * w < 20000:
        return img  # too small to bother
    import cv2  # lazy import — matches ocr_image() style (module loads without cv2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 0.10 * h * w:
        return img  # card too small in frame — nothing confident to crop
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        return img  # not a clean quadrilateral

    pts = approx.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    src = np.array([
        pts[np.argmin(s)],    # top-left
        pts[np.argmin(diff)], # top-right
        pts[np.argmax(s)],    # bottom-right
        pts[np.argmax(diff)], # bottom-left
    ], dtype="float32")
    card_w = max(int(np.linalg.norm(src[1] - src[0])), int(np.linalg.norm(src[2] - src[3])))
    card_h = max(int(np.linalg.norm(src[3] - src[0])), int(np.linalg.norm(src[2] - src[1])))
    if card_w < 50 or card_h < 30:
        return img
    # Business cards are ~1.4–2.2 : 1. Reject wildly off-ratio crops
    # (e.g. an internal graphic boundary caught by Canny) — safer to skip crop.
    ratio = max(card_w, card_h) / max(1, min(card_w, card_h))
    if not (1.2 <= ratio <= 2.5):
        return img

    dst = np.array([[0, 0], [card_w - 1, 0], [card_w - 1, card_h - 1], [0, card_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (card_w, card_h))


def _detect_card_region_vision(image_path: str | Path,
                               usage_out: list | None = None) -> Any | None:
    """Vision-AI fallback: ask Qwen3-VL (SiliconFlow) for exact card corners.

    Used only when OpenCV contour detection finds no confident quadrilateral —
    messy desks / shadows / low contrast where edges fail but a vision model
    still understands "that is a business card". Returns the warped crop, or
    None on any failure (no key, API error, bad response) — callers fall back
    to the original image, so this never breaks OCR.
    """
    import base64
    import json
    import os
    import urllib.request

    key = cached_provider_key("siliconflow") or os.environ.get("SILICONFLOW_API_KEY", "")
    if not key:
        return None
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError:
        return None

    prompt = (
        "A business card lies in this photo. Find the exact four corners of "
        "the card (the card only, not the desk/background). Return ONLY JSON: "
        '{"corners": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]} ordered top-left, '
        "top-right, bottom-right, bottom-left, in pixel coordinates. Be precise."
    )
    payload = {
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"]
        # Core rule G08: collect SiliconFlow usage for central tracking.
        if usage_out is not None:
            u = result.get("usage") or {}
            inp = int(u.get("prompt_tokens") or 0)
            out = int(u.get("completion_tokens") or 0)
            usage_out.append({
                "provider": "siliconflow",
                "model": "Qwen/Qwen3-VL-8B-Instruct",
                "input_tokens": inp,
                "output_tokens": out,
                "cost_usd": 0,  # SiliconFlow pricing not in cost cards
            })
        start, end = text.find("{"), text.rfind("}") + 1
        corners = json.loads(text[start:end])["corners"]
        if len(corners) != 4:
            return None
        import cv2
        src = np.array(corners, dtype="float32")
        tl, tr, br, bl = src[0], src[1], src[2], src[3]
        cw = max(int(np.linalg.norm(tr - tl)), int(np.linalg.norm(br - bl)))
        ch = max(int(np.linalg.norm(bl - tl)), int(np.linalg.norm(br - tr)))
        if cw < 50 or ch < 30:
            return None
        dst = np.array([[0, 0], [cw - 1, 0], [cw - 1, ch - 1], [0, ch - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(src, dst)
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        return cv2.warpPerspective(img, M, (cw, ch))
    except Exception:
        return None


def ocr_image(image_path: str | Path, langs: str = "chi_tra+eng",
              usage_out: list | None = None) -> str:
    """OCR an image → text. RapidOCR (ONNX CPU) primary; tesseract fallback.

    Real photos are noisy: RapidOCR handles phone photos of HK cards well
    (email/phone/address accuracy — verified against tesseract on real cards).
    If RapidOCR returns signal-rich text (email/phone/URL) we use it directly;
    otherwise fall back to the tesseract multi-pass (PSM 6 + 11 on enhanced
    and raw image) with signal scoring.
    """
    image_path = str(image_path)

    # 0) RapidOCR primary（zero-cost local ONNX — namecard_scan study guide）
    rapid = _ocr_rapid(image_path)
    if rapid and (_EMAIL_RE.search(rapid) or _PHONE_RE.search(rapid) or _URL_RE.search(rapid)):
        return rapid

    import cv2  # opencv-python-headless
    # 1) Auto-crop card boundary (perspective-correct), then enhance:
    # landscape-orient fix + CLAHE + denoise + 2x upscale
    img = cv2.imread(image_path)
    enhanced_path = None
    if img is not None:
        cropped = _detect_card_region(img)
        if cropped is img:
            # OpenCV found no confident card boundary → vision-AI fallback
            # (Qwen3-VL via SiliconFlow). None on failure = keep original.
            vision_crop = _detect_card_region_vision(image_path, usage_out=usage_out)
            if vision_crop is not None:
                img = vision_crop
        else:
            img = cropped
        h, w = img.shape[:2]
        if h > w * 1.2:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        denoised = cv2.fastNlMeansDenoising(clahe.apply(gray), None, 10, 7, 21)
        blur = cv2.GaussianBlur(denoised, (0, 0), 2.0)
        sharp = cv2.addWeighted(denoised, 1.6, blur, -0.6, 0)
        big = cv2.resize(sharp, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        import tempfile
        enhanced_path = Path(tempfile.mkdtemp()) / "nc_enhanced.png"
        cv2.imwrite(str(enhanced_path), big)

    def _run(path: str, psm: str, lang: str) -> str:
        try:
            r = subprocess.run(
                ["tesseract", path, "stdout", "-l", lang, "--psm", psm],
                capture_output=True, text=True, timeout=60,
            )
            return (r.stdout or "").strip()
        except Exception:
            return ""

    candidates: list[str] = []
    sources = [enhanced_path] if enhanced_path else []
    sources.append(image_path)
    for path in sources:
        for psm in ("6", "11"):
            candidates.append(_run(path, psm, "chi_tra+eng"))
            candidates.append(_run(path, psm, "eng"))

    if enhanced_path is not None:
        try:
            import shutil
            shutil.rmtree(str(enhanced_path.parent))
        except OSError:
            pass

    def score(txt: str) -> float:
        return signal_score(txt)

    ranked = sorted(candidates, key=score, reverse=True)
    if not ranked or not ranked[0]:
        return ""
    merged: list[str] = []
    seen: set[str] = set()
    for txt in ranked:
        if score(txt) < 200 and txt != ranked[0]:
            continue
        for ln in txt.splitlines():
            ln_clean = re.sub(r"\s+", " ", ln).strip()
            if ln_clean and ln_clean not in seen:
                seen.add(ln_clean)
                merged.append(ln_clean)
    return "\n".join(merged)


def _ocr_rapid(image_path: str) -> str:
    """RapidOCR (ONNX, local CPU, Apache-2.0) — primary OCR for name cards."""
    global _RAPID_ENGINE
    try:
        if _RAPID_ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID_ENGINE = RapidOCR()
        result, _elapse = _RAPID_ENGINE(image_path)
        if not result:
            return ""
        lines: list[str] = []
        seen: set[str] = set()
        for _box, text, _score in result:
            t = re.sub(r"\s+", " ", str(text)).strip()
            if t and t not in seen:
                seen.add(t)
                lines.append(t)
        return "\n".join(lines)
    except Exception:
        return ""


_RAPID_ENGINE = None


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?)?\d{3,4}[ -]?\d{3,4}(?:[ -]?\d{2,4})?")
_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+\.(?:com|hk|cn|net|org|io|co|tw)(?:/[^\s]*)?", re.I)
_LINKEDIN_RE = re.compile(r"(?:linkedin\.com|領英)[^\s]*", re.I)
_TITLE_KEYWORDS = (
    "director", "manager", "engineer", "sales", "marketing", "consultant",
    "officer", "president", "founder", "ceo", "cto", "cfo", "vp", "head",
    "lead", "specialist", "analyst", "executive", "architect", "developer",
    "總監", "經理", "工程師", "銷售", "市場", "顧問", "主任", "總裁", "創辦人",
    "主席", "主管", "專員", "分析師", "行銷", "業務", "採購", "財務", "人事",
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().strip("|·•-–—")


def _is_title(line: str) -> bool:
    low = line.lower()
    if any(k in low for k in _TITLE_KEYWORDS):
        return True
    # 3-6 chars, mostly CJK, no digits — typical Chinese job titles
    cjk = sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")
    if cjk >= 2 and cjk == len(line) and len(line) <= 8:
        return True
    return False


_COMPANY_HINTS = (
    "ltd", "inc", "corp", "corporation", "co.", "co ", "group", "holdings",
    "limited", "company", "bank", "systex", "tech", "technology", "systems",
    "有限公司", "公司", "集團", "企業", "銀行", "科技", "國際", "控股",
)


def _is_company(line: str) -> bool:
    low = line.lower()
    return any(h in low for h in _COMPANY_HINTS) and len(line) <= 50


def signal_score(text: str) -> float:
    """Signal-richness score of OCR text — email/phone/domain/title signals.

    Shared by ocr_image() candidate ranking and verify_crop() baseline check.
    """
    s = len(text) * 0.05
    if re.search(r"@", text):
        s += 300
    if re.search(r"\b\+?\d{8,}\b", text):
        s += 150
    if re.search(r"\.com|\.hk|www\.", text):
        s += 100
    if re.search(r"\b(manager|director|sales|engineer|consultant|officer|account)\b", text, re.I):
        s += 50
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    total_alpha = sum(1 for ch in text if ch.isalpha())
    if total_alpha and cjk / total_alpha > 0.4:
        s -= 400
    s -= sum(1 for ch in text if ch in "|\\/=-_~*#@&%^") * 0.5
    return s


def verify_crop(original_path: str | Path, cropped_path: str | Path,
                min_ratio: float = 0.85,
                usage_out: list | None = None) -> bool:
    """OCR-based crop completeness check — did the crop cut anything off?

    Baseline = signal score of the full original photo; the crop passes only
    if it preserves >= min_ratio of that signal. A crop that clipped part of
    the card (missing email / phone / name) scores lower and is rejected, so
    the caller falls back to the original instead of storing a damaged crop.
    """
    orig_text = ocr_image(original_path, usage_out=usage_out)
    crop_text = ocr_image(cropped_path, usage_out=usage_out)
    base = signal_score(orig_text)
    crop = signal_score(crop_text)
    if base <= 0:
        return crop > 0  # original unreadable → any readable crop is an improvement
    return crop >= base * min_ratio


def parse_namecard(raw_text: str) -> dict[str, Any]:
    """Parse raw OCR text into structured namecard fields."""
    lines = [_clean(l) for l in raw_text.splitlines() if _clean(l)]
    if not lines:
        return {}

    # Multi-line text → single string for regex scans
    blob = "\n".join(lines)

    emails = list(dict.fromkeys(_EMAIL_RE.findall(blob)))
    urls = [u for u in _URL_RE.findall(blob) if "linkedin" not in u.lower()]
    linkedin = _LINKEDIN_RE.search(blob)
    phones = []
    for m in _PHONE_RE.finditer(blob):
        p = m.group(0)
        if len(re.sub(r"\D", "", p)) >= 7 and p not in phones:
            phones.append(p)

    # Classify lines: contact-ish (skip), title, company, name
    title = None
    company = None
    name_line = None
    skip_patterns = (_EMAIL_RE, _URL_RE, _PHONE_RE)

    # Pass 0: strong name signal — exactly 2..4 capitalized words (e.g. "Marco Chan"),
    # no digits/symbols. Real names; OCR garbage rarely forms this pattern.
    _CAP_WORD = re.compile(r"^[A-Z][a-zA-Z'’-]+$")
    for line in lines:
        if not (1 <= len(line) <= 30) or any(p.search(line) for p in skip_patterns):
            continue
        words = line.split()
        if not (2 <= len(words) <= 4):
            continue
        if all(_CAP_WORD.match(w) for w in words):
            name_line = line
            break

    for line in lines:
        if line == name_line:
            continue
        if len(line) > 40:
            continue
        if any(p.search(line) for p in skip_patterns):
            continue
        if _is_title(line):
            if title is None:
                title = line
            continue
        if _is_company(line):
            if company is None:
                company = line
            continue
        if name_line is None and len(line) >= 2:
            name_line = line

    # Name heuristic: first remaining line with 2+ words (or 2+ CJK chars),
    # not a title / company / contact line
    if name_line is None:
        for line in lines:
            words = line.split()
            cjk_count = sum(1 for ch in line if "\u4e00" <= ch <= "\u9fff")
            if 0 < len(line) <= 30 and not any(p.search(line) for p in skip_patterns) \
                    and not _is_title(line) and not _is_company(line) \
                    and (len(words) >= 2 or cjk_count >= 2):
                name_line = line
                break

    # Chinese name detection — extract CJK run(s) from the name line
    chinese_name = None
    if name_line:
        cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,5}", name_line)
        if cjk_runs:
            chinese_name = "".join(cjk_runs)

    # Split phone into mobile vs office by count of digits / common prefixes
    mobile, office = None, None
    for p in phones:
        digits = re.sub(r"\D", "", p)
        if mobile is None and (digits.startswith(("6", "9", "5")) or len(digits) == 8):
            mobile = p
        elif office is None:
            office = p

    return {
        "name": name_line or "",
        "chinese_name": chinese_name or "",
        "title": title or "",
        "company": company or "",
        "phone": mobile or (phones[0] if phones else ""),
        "office_phone": office or "",
        "email": emails[0] if emails else "",
        "emails": emails,
        "website": urls[0] if urls else "",
        "address": "",
        "linkedin": linkedin.group(0) if linkedin else "",
        "raw_lines": lines,
    }

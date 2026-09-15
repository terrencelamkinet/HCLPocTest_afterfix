"""Document-scanner-style namecard crop: 5-param-set retry ladder +
morphological closing + cornerSubPix sub-pixel refinement + GrabCut fallback.
Reference: LearnOpenCV automatic document scanner pattern (per Terrence)."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]      # top-left
    rect[2] = pts[np.argmax(s)]      # bottom-right
    rect[1] = pts[np.argmin(diff)]   # top-right
    rect[3] = pts[np.argmax(diff)]   # bottom-left
    return rect


def four_point_transform(image: Any, pts: np.ndarray) -> Any:
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = int(max(width_a, width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = int(max(height_a, height_b))
    dst = np.array([[0, 0], [max_width - 1, 0],
                    [max_width - 1, max_height - 1], [0, max_height - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_width, max_height))


def find_card_contour(image: Any, canny_lo: int, canny_hi: int,
                      blur_ksize: int, close_ksize: int, epsilon_ratio: float) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (blur_ksize, blur_ksize), 0)
    edged = cv2.Canny(blur, canny_lo, canny_hi)
    kernel = np.ones((close_ksize, close_ksize), np.uint8)
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:5]

    for c in cnts:
        area = cv2.contourArea(c)
        if area < 0.15 * image.shape[0] * image.shape[1]:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon_ratio * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32")
    return None


def _grabcut_fallback(image: Any) -> np.ndarray | None:
    """GrabCut foreground segmentation → largest 4-corner contour."""
    mask = np.zeros(image.shape[:2], np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    h, w = image.shape[:2]
    rect = (int(w * 0.05), int(h * 0.05), int(w * 0.9), int(h * 0.9))
    try:
        cv2.grabCut(image, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    mask2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    cnts, _ = cv2.findContours(mask2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    largest = max(cnts, key=cv2.contourArea)
    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)
    if len(approx) != 4:
        # fall back to min-area rect of the largest blob
        rect = cv2.minAreaRect(largest)
        return cv2.boxPoints(rect).astype("float32")
    return approx.reshape(4, 2).astype("float32")


def crop_card(image_path: str, max_attempts: int = 5) -> tuple[Any | None, int, str]:
    """Retry ladder over 5 parameter sets; GrabCut as final fallback.
    Returns (warped, attempt_used, method)."""
    image = cv2.imread(image_path)
    if image is None:
        return None, 0, "read_error"
    orig = image.copy()
    h, w = image.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(image, (int(w * scale), int(h * scale)))

    param_sets = [
        dict(canny_lo=75,  canny_hi=200, blur_ksize=5, close_ksize=5,  epsilon_ratio=0.02),
        dict(canny_lo=50,  canny_hi=150, blur_ksize=5, close_ksize=7,  epsilon_ratio=0.02),
        dict(canny_lo=30,  canny_hi=100, blur_ksize=7, close_ksize=9,  epsilon_ratio=0.015),
        dict(canny_lo=100, canny_hi=250, blur_ksize=3, close_ksize=5,  epsilon_ratio=0.03),
        dict(canny_lo=20,  canny_hi=80,  blur_ksize=9, close_ksize=11, epsilon_ratio=0.01),
    ]

    for attempt, params in enumerate(param_sets[:max_attempts], 1):
        pts = find_card_contour(small, **params)
        if pts is not None:
            # Card-shape sanity: business cards are ~1.2–2.5:1 — reject quads
            # that absorbed desk area beside the card.
            _cw = max(float(np.linalg.norm(pts[1] - pts[0])), float(np.linalg.norm(pts[3] - pts[2])))
            _ch = max(float(np.linalg.norm(pts[3] - pts[0])), float(np.linalg.norm(pts[2] - pts[1])))
            _ratio = max(_cw, _ch) / max(1.0, min(_cw, _ch))
            if not (1.2 <= _ratio <= 2.5):
                continue
            try:
                pts_refined = cv2.cornerSubPix(
                    cv2.cvtColor(small, cv2.COLOR_BGR2GRAY),
                    pts.reshape(-1, 1, 2).astype("float32"),
                    winSize=(5, 5), zeroZone=(-1, -1),
                    criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
                ).reshape(4, 2)
            except cv2.error:
                pts_refined = pts
            pts_original = pts_refined / scale
            warped = four_point_transform(orig, pts_original)
            return warped, attempt, f"opencv_params_{attempt}"

    # Final fallback: GrabCut
    pts = _grabcut_fallback(image)
    if pts is not None:
        warped = four_point_transform(orig, pts)
        return warped, max_attempts + 1, "grabcut"
    return None, max_attempts, "all_failed"

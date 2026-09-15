"""Color-based crop v2: seed-connected mask (flood fill from click point).
Fixes v1 flaw: threshold-only mask absorbs desk highlights; connectivity
constraint keeps only the region connected to the sampled card pixel."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
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


def crop_card_color_seeded(image_path: str, click_point: tuple[int, int] | None = None,
                           max_attempts: int = 5) -> tuple[Any | None, int, dict]:
    image = cv2.imread(image_path)
    if image is None:
        return None, 0, {"error": "read_error"}
    h, w = image.shape[:2]

    # 1) find seed: click point, or auto = brightest spot in upper 60% (cards usually there)
    if click_point is None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (15, 15), 0)
        top = blur[:int(h * 0.8)]
        thr = top.max() * 0.90
        ys, xs = np.where(top > thr)
        click_point = (int(np.median(xs)), int(np.median(ys))) if len(xs) > 100 else (w // 2, h // 4)

    # 2) color distance mask relative to seed color (LAB, robust to lighting)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    seed_lab = lab[click_point[1], click_point[0]]
    dist = np.linalg.norm(lab - seed_lab, axis=2)
    color_mask = (dist < 45).astype(np.uint8) * 255  # LAB distance threshold

    # 3) connectivity: keep only the component touching the seed
    num, labels, stats, _ = cv2.connectedComponentsWithStats(color_mask, connectivity=8)
    seed_label = labels[click_point[1], click_point[0]]
    comp_mask = np.where(labels == seed_label, 255, 0).astype(np.uint8)

    # 4) morphology to seal card edges
    for k in (15, 21, 27):
        closed = cv2.morphologyEx(comp_mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        biggest = max(cnts, key=cv2.contourArea)
        area_ratio = cv2.contourArea(biggest) / (h * w)
        if not (0.05 <= area_ratio <= 0.90):
            continue
        hull = cv2.convexHull(biggest)
        peri = cv2.arcLength(hull, True)
        approx = cv2.approxPolyDP(hull, 0.02 * peri, True)
        pts = approx.reshape(4, 2).astype("float32") if len(approx) == 4 \
            else cv2.boxPoints(cv2.minAreaRect(hull)).astype("float32")
        # Card-shape sanity: business cards are ~1.2–2.5:1. A wider quad means
        # the mask absorbed desk/highlight area beside the card → try next kernel.
        _cw = max(float(np.linalg.norm(pts[1] - pts[0])), float(np.linalg.norm(pts[3] - pts[2])))
        _ch = max(float(np.linalg.norm(pts[3] - pts[0])), float(np.linalg.norm(pts[2] - pts[1])))
        _ratio = max(_cw, _ch) / max(1.0, min(_cw, _ch))
        if not (1.2 <= _ratio <= 2.5):
            continue
        try:
            pts_refined = cv2.cornerSubPix(
                cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                pts.reshape(-1, 1, 2).astype("float32"),
                winSize=(11, 11), zeroZone=(-1, -1),
                criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001),
            ).reshape(4, 2)
        except cv2.error:
            pts_refined = pts
        warped = four_point_transform(image, pts_refined)
        return warped, 1, {"seed": click_point, "corners": pts_refined.tolist(),
                           "k": k, "area_ratio": round(area_ratio, 3)}
    return None, max_attempts, {"seed": click_point}

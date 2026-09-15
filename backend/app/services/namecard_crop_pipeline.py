"""NameCard crop pipeline — best-effort three-stage crop with OCR verification.

Stages (fast → slow, each returns a perspective-corrected card image):
  1. color_seeded  — LAB seed-connected mask (0.25s, robust to desk highlights)
  2. scanner       — Canny retry ladder + GrabCut fallback
  3. vision        — Qwen3-VL (SiliconFlow) four-corner detection

The caller (crm router) then runs verify_crop() from namecard_ocr: OCR of the
full original vs OCR of the crop. A crop that clipped card content loses
signal and is rejected — the original photo is kept instead.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2


def crop_card_best(image_path: str | Path,
                   usage_out: list | None = None) -> dict[str, Any]:
    """Run crop stages in order. Returns:
    {"crop": ndarray | None, "method": str, "meta": dict}
    """
    image_path = str(image_path)
    meta: dict[str, Any] = {}

    # Stage 1 — color-seeded (fast, usually sufficient)
    try:
        from app.services.namecard_color_crop import crop_card_color_seeded
        warped, attempts, m = crop_card_color_seeded(image_path)
        meta["color_seeded"] = {"attempts": attempts, **m}
        if warped is not None:
            return {"crop": warped, "method": "color_seeded", "meta": meta}
    except Exception as e:  # noqa: BLE001 — stage must never kill the pipeline
        meta["color_seeded_error"] = str(e)

    # Stage 2 — Canny scanner ladder + GrabCut
    try:
        from app.services.namecard_scanner_crop import crop_card
        warped, attempts, method = crop_card(image_path)
        meta["scanner"] = {"attempts": attempts, "method": method}
        if warped is not None:
            return {"crop": warped, "method": f"scanner:{method}", "meta": meta}
    except Exception as e:  # noqa: BLE001
        meta["scanner_error"] = str(e)

    # Stage 3 — vision-AI corners (SiliconFlow; no-op without API key)
    try:
        from app.services.namecard_ocr import _detect_card_region_vision
        warped = _detect_card_region_vision(image_path, usage_out=usage_out)
        meta["vision"] = {"attempted": True}
        if warped is not None:
            return {"crop": warped, "method": "vision", "meta": meta}
    except Exception as e:  # noqa: BLE001
        meta["vision_error"] = str(e)

    return {"crop": None, "method": "none", "meta": meta}


def save_crop(crop_img: Any, original_path: str | Path) -> Path:
    """Save the crop next to the original as {stem}_crop{ext}. Returns path."""
    original_path = Path(original_path)
    crop_path = original_path.with_name(f"{original_path.stem}_crop{original_path.suffix}")
    ok, buf = cv2.imencode(
        ".jpg" if original_path.suffix.lower() not in (".png", ".webp") else original_path.suffix,
        crop_img,
        [cv2.IMWRITE_JPEG_QUALITY, 92],
    )
    if not ok:
        raise OSError(f"imencode failed for {crop_path}")
    crop_path.write_bytes(buf.tobytes())
    return crop_path

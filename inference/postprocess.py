"""
inference/postprocess.py

Turn the model-size mask into what the visitor sees: optional removal of tiny
blobs, the mask at the input's own size, a red overlay and a summary dict.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from . import DISCLAIMER

DEFAULT_MIN_BLOB_PIXELS = 20
OVERLAY_COLOR_RGB = (255, 0, 0)
OVERLAY_ALPHA = 0.45


def remove_small_blobs(mask: np.ndarray, min_pixels: int = DEFAULT_MIN_BLOB_PIXELS) -> np.ndarray:
    """
    Drop connected components (8-connectivity) with fewer than `min_pixels`
    pixels. `min_pixels <= 0` disables the step. Returns a bool array.
    """
    mask = np.asarray(mask).astype(bool)
    if min_pixels <= 0 or not mask.any():
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= int(min_pixels)
    return keep[labels]


def resize_mask(mask: np.ndarray, size_hw: Tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize of a bool mask to (height, width)."""
    mask = np.asarray(mask).astype(bool)
    h, w = int(size_hw[0]), int(size_hw[1])
    if mask.shape == (h, w):
        return mask
    out = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    return out.astype(bool)


def mask_to_png_array(mask: np.ndarray) -> np.ndarray:
    """bool mask -> uint8 0/255, the layout of the training masks."""
    return np.asarray(mask).astype(np.uint8) * 255


def make_overlay(
    image_u8: np.ndarray,
    mask: np.ndarray,
    color_rgb: Tuple[int, int, int] = OVERLAY_COLOR_RGB,
    alpha: float = OVERLAY_ALPHA,
) -> np.ndarray:
    """Gray uint8 image (H, W) + bool mask (H, W) -> RGB uint8 with the mask tinted red."""
    if image_u8.ndim != 2:
        raise ValueError(f"expected a gray image, got shape {image_u8.shape}")
    mask = np.asarray(mask).astype(bool)
    if mask.shape != image_u8.shape:
        raise ValueError(f"mask shape {mask.shape} != image shape {image_u8.shape}")
    rgb = np.stack([image_u8] * 3, axis=-1).astype(np.float32)
    color = np.array(color_rgb, dtype=np.float32)
    rgb[mask] = (1.0 - alpha) * rgb[mask] + alpha * color
    out = np.clip(rgb, 0, 255).astype(np.uint8)
    # Solid outline so small or faint regions stay visible.
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.ascontiguousarray(out)
    cv2.drawContours(out, contours, -1, tuple(int(c) for c in color_rgb), 1)
    return out


def build_summary(
    mask: np.ndarray,
    *,
    model_key: str,
    fold: int,
    threshold: float,
    run_seconds: float,
    min_blob_pixels: int = DEFAULT_MIN_BLOB_PIXELS,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """JSON-safe summary of one predicted mask (at the input's size)."""
    mask = np.asarray(mask).astype(bool)
    tumor_pixels = int(mask.sum())
    total = int(mask.size)
    summary: Dict[str, Any] = {
        "tumor_pixels":    tumor_pixels,
        "total_pixels":    total,
        "tumor_share":     (tumor_pixels / total) if total else 0.0,
        "tumor_found":     tumor_pixels > 0,
        "model_key":       model_key,
        "fold":            int(fold),
        "threshold":       float(threshold),
        "min_blob_pixels": int(min_blob_pixels),
        "run_seconds":     round(float(run_seconds), 4),
        "mask_height":     int(mask.shape[0]),
        "mask_width":      int(mask.shape[1]),
        "disclaimer":      DISCLAIMER,
    }
    if extra:
        summary.update(extra)
    return summary

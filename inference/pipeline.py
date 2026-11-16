"""
inference/pipeline.py

File in, result out. Used by the command-line tool and (Phase 3) the Django
views, so both run exactly the same code.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import numpy as np

from .loaders import LoadedScan, load_scan
from .postprocess import (
    DEFAULT_MIN_BLOB_PIXELS,
    build_summary,
    make_overlay,
    mask_to_png_array,
    remove_small_blobs,
    resize_mask,
)
from .predictor import DEFAULT_BATCH_SIZE, predict_masks
from .preprocess import preprocess_slices
from .registry import ModelRegistry, default_registry

PathLike = Union[str, Path]

MASK_FILENAME = "mask.png"
OVERLAY_FILENAME = "overlay.png"
SUMMARY_FILENAME = "summary.json"


@dataclass
class SliceResult:
    index: int
    image_u8: np.ndarray        # (H, W) uint8, input at its own size
    mask: np.ndarray            # (H, W) bool, at the input's size
    overlay: np.ndarray         # (H, W, 3) uint8 RGB
    summary: Dict[str, Any]


@dataclass
class InferenceResult:
    model_key: str
    fold: int
    threshold: float
    run_seconds: float
    slices: List[SliceResult] = field(default_factory=list)

    @property
    def n_slices(self) -> int:
        return len(self.slices)

    def default_slice_index(self) -> int:
        """The only slice, or for several the one with the most tumor pixels (middle if none)."""
        if self.n_slices == 1:
            return 0
        counts = [s.summary["tumor_pixels"] for s in self.slices]
        if max(counts) > 0:
            return int(np.argmax(counts))
        return self.n_slices // 2


def run_scan(
    scan: LoadedScan,
    model_key: str,
    *,
    registry: Optional[ModelRegistry] = None,
    min_blob_pixels: int = DEFAULT_MIN_BLOB_PIXELS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> InferenceResult:
    """Preprocess, predict and post-process every slice of an already loaded scan."""
    registry = registry or default_registry()
    entry = registry.get(model_key)
    model = registry.load(model_key)

    t0 = time.perf_counter()
    batch, images_u8 = preprocess_slices(
        scan.slices,
        intensity=scan.meta.get("intensity", "raw"),
        image_size=entry.image_size,
        preprocessing=entry.preprocessing,
    )
    masks, _ = predict_masks(model, batch, threshold=entry.threshold, batch_size=batch_size)

    native_masks = []
    for image_u8, mask in zip(images_u8, masks):
        mask = remove_small_blobs(mask, min_blob_pixels)
        native_masks.append(resize_mask(mask, image_u8.shape))
    run_seconds = time.perf_counter() - t0

    result = InferenceResult(
        model_key=entry.key, fold=entry.fold, threshold=entry.threshold,
        run_seconds=run_seconds,
    )
    extra = {
        "model_label":     entry.display_label,
        "model_scan_type": entry.scan_type,
        "best_score":      entry.best_score,
        "preprocessing":   entry.preprocessing,
        "image_size":      entry.image_size,
        "input_format":    scan.meta.get("format"),
        "input_intensity": scan.meta.get("intensity"),
        "n_slices":        len(scan.slices),
    }
    for i, (image_u8, mask) in enumerate(zip(images_u8, native_masks)):
        summary = build_summary(
            mask, model_key=entry.key, fold=entry.fold, threshold=entry.threshold,
            run_seconds=run_seconds, min_blob_pixels=min_blob_pixels,
            extra={**extra, "slice_index": i},
        )
        result.slices.append(SliceResult(
            index=i, image_u8=image_u8, mask=mask,
            overlay=make_overlay(image_u8, mask), summary=summary,
        ))
    return result


def run_file(path: PathLike, model_key: str, **kwargs: Any) -> InferenceResult:
    """Load a scan file (format detected from content) and run `run_scan`."""
    return run_scan(load_scan(path), model_key, **kwargs)


def write_png(path: PathLike, array: np.ndarray) -> None:
    """Write a gray (H, W) or RGB (H, W, 3) uint8 array as PNG."""
    if array.ndim == 3:
        array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", array)
    if not ok:
        raise RuntimeError(f"could not encode {path}")
    Path(path).write_bytes(buf.tobytes())


def save_slice_result(slice_result: SliceResult, out_dir: PathLike) -> Dict[str, Path]:
    """Write mask.png, overlay.png and summary.json for one slice into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "mask":    out_dir / MASK_FILENAME,
        "overlay": out_dir / OVERLAY_FILENAME,
        "summary": out_dir / SUMMARY_FILENAME,
    }
    write_png(paths["mask"], mask_to_png_array(slice_result.mask))
    write_png(paths["overlay"], slice_result.overlay)
    with open(paths["summary"], "w", encoding="utf-8") as f:
        json.dump(slice_result.summary, f, indent=2)
        f.write("\n")
    return paths

"""
inference/preprocess.py

The training preprocessing, copied from the training repo. Do not "improve"
anything here: the models only know images produced by exactly these steps.

Training path of one slice:

  src/preprocess_utils.py (NB01, raw scanner data -> PNG on disk)
    1. `_normalize_image_to_uint8(method="percentile")`: clip to the 1st-99th
       percentile, scale to uint8.
    2. `_resize_image_uint8`: cv2.resize to 256x256, INTER_LINEAR.
    (saved as a lossless grayscale PNG)

  src/sg_data_utils.py (dataset + build_eval_transform, PNG -> tensor)
    3. cv2.imread(..., IMREAD_GRAYSCALE) then cv2.cvtColor(GRAY2RGB):
       three identical channels.
    4. A.Resize(image_size, image_size)
    5. A.CLAHE(clip_limit=2.0, tile_grid_size=(8, 8), p=1.0) only when
       preprocessing == "clahe"
    6. A.Normalize(ImageNet mean/std), ToTensorV2

Known quirk, kept on purpose: albumentations treats `clip_limit=2.0` as the
range (1.0, 2.0) and draws a value per call, so step 5 is slightly random for
"clahe" models here exactly as it was in training and evaluation.

Step 1 converts raw intensities to 8-bit. An upload that is already an 8-bit
image (`intensity == "uint8"`, e.g. one of the training PNGs) is in that state
already and skips step 1, which is what makes a training PNG reproduce its
training-time prediction. Everything else (FigShare .mat, BraTS .h5, DICOM,
16-bit images) goes through step 1.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import albumentations as A
import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

INTENSITY_UINT8 = "uint8"
INTENSITY_RAW = "raw"


# --------------------------------------------------------------------------- #
# Copied from src/preprocess_utils.py
# --------------------------------------------------------------------------- #
def _normalize_image_to_uint8(
    image: np.ndarray,
    method: str = "percentile",
) -> np.ndarray:
    """Convert a float/int array to uint8 [0, 255] via percentile or minmax."""
    img = image.astype(np.float32)
    if method == "percentile":
        lo, hi = np.percentile(img, [1.0, 99.0])
        if hi <= lo:
            hi = lo + 1.0
        img = np.clip((img - lo) / (hi - lo), 0.0, 1.0)
        return (img * 255.0).astype(np.uint8)
    if method == "minmax":
        return cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    raise ValueError(f"unknown normalization method: {method!r}")


def _resize_to(
    arr: np.ndarray,
    target_size: Tuple[int, int],
    interp: int = cv2.INTER_LINEAR,
    is_mask: bool = False,
) -> np.ndarray:
    th, tw = target_size
    out = cv2.resize(arr, (tw, th), interpolation=interp)
    if is_mask:
        return ((out > 127).astype(np.uint8)) * 255
    return out


def _resize_image_uint8(image: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
    return _resize_to(image, target_size, cv2.INTER_LINEAR, is_mask=False)


# --------------------------------------------------------------------------- #
# Copied from src/sg_data_utils.py
# --------------------------------------------------------------------------- #
def _preprocessing_block(name: Optional[str]) -> list:
    """Returns the preprocessing portion of the augmentation pipeline."""
    name = (name or "original").lower()
    if name in ("original", "none", ""):
        return []
    if name == "clahe":
        return [A.CLAHE(clip_limit=2.0, tile_grid_size=(8, 8), p=1.0)]
    raise ValueError(f"unknown preprocessing name: {name!r}")


def build_eval_transform(
    image_size: int = 256,
    preprocessing: str = "original",
) -> A.Compose:
    """Validation/test pipeline: preprocessing + normalize. No random aug."""
    pre = _preprocessing_block(preprocessing)
    return A.Compose([
        A.Resize(image_size, image_size),
        *pre,
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


# --------------------------------------------------------------------------- #
# Web-app entry points
# --------------------------------------------------------------------------- #
def to_uint8_slice(slice_2d: np.ndarray, intensity: str = INTENSITY_RAW) -> np.ndarray:
    """
    Native-size 8-bit version of one slice (step 1). Also the image the overlay
    is drawn on.
    """
    if slice_2d.ndim != 2:
        raise ValueError(f"expected a 2D slice, got shape {slice_2d.shape}")
    if intensity == INTENSITY_UINT8:
        return np.clip(slice_2d, 0, 255).astype(np.uint8)
    if intensity == INTENSITY_RAW:
        return _normalize_image_to_uint8(slice_2d, method="percentile")
    raise ValueError(f"unknown intensity kind: {intensity!r}")


def to_training_png(image_u8: np.ndarray, image_size: int = 256) -> np.ndarray:
    """Step 2: what NB01 wrote to disk, a (image_size, image_size) uint8 image."""
    if image_u8.shape[:2] == (image_size, image_size):
        return image_u8
    return _resize_image_uint8(image_u8, (image_size, image_size))


def preprocess_slice(
    slice_2d: np.ndarray,
    *,
    intensity: str = INTENSITY_RAW,
    image_size: int = 256,
    preprocessing: str = "original",
    transform: Optional[A.Compose] = None,
) -> Tuple[torch.Tensor, np.ndarray]:
    """
    One raw 2D slice -> (model input tensor (3, S, S) float32, native-size uint8 image).
    """
    image_u8 = to_uint8_slice(slice_2d, intensity)
    png = to_training_png(image_u8, image_size)
    rgb = cv2.cvtColor(png, cv2.COLOR_GRAY2RGB)                  # step 3
    if transform is None:
        transform = build_eval_transform(image_size, preprocessing)
    tensor = transform(image=rgb)["image"]                        # steps 4-6
    return tensor.float(), image_u8


def preprocess_slices(
    slices: Sequence[np.ndarray],
    *,
    intensity: str = INTENSITY_RAW,
    image_size: int = 256,
    preprocessing: str = "original",
) -> Tuple[torch.Tensor, List[np.ndarray]]:
    """All slices -> (batch tensor (N, 3, S, S), list of native-size uint8 images)."""
    if not slices:
        raise ValueError("no slices to preprocess")
    transform = build_eval_transform(image_size, preprocessing)
    tensors, images = [], []
    for sl in slices:
        t, u8 = preprocess_slice(sl, intensity=intensity, image_size=image_size,
                                 preprocessing=preprocessing, transform=transform)
        tensors.append(t)
        images.append(u8)
    return torch.stack(tensors, dim=0), images

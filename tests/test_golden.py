"""
Golden test against real checkpoints. Skipped when tests/golden/ holds no pairs.

Layout:
    tests/golden/<model_key>/<name>.png        256x256 preprocessed image from the
                                               training data (data/<ds>/processed/images/)
    tests/golden/<model_key>/<name>_mask.png   the mask that model predicted for it in
                                               the training repo (NB05 prediction PNG)

Each pair is run through the full pipeline with blob removal off and must
reach Dice >= 0.99 against the stored prediction. The matching checkpoint has
to be in model_store/<model_key>/.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from inference.pipeline import run_file
from inference.registry import ModelRegistry

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
MIN_DICE = 0.99
MASK_SUFFIX = "_mask"


def _golden_pairs():
    pairs = []
    if not GOLDEN_DIR.is_dir():
        return pairs
    for key_dir in sorted(p for p in GOLDEN_DIR.iterdir() if p.is_dir()):
        for image in sorted(key_dir.glob("*.png")):
            if image.stem.endswith(MASK_SUFFIX):
                continue
            mask = image.with_name(f"{image.stem}{MASK_SUFFIX}.png")
            if mask.is_file():
                pairs.append(pytest.param(key_dir.name, image, mask,
                                          id=f"{key_dir.name}/{image.stem}"))
    return pairs


def dice(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(bool), b.astype(bool)
    total = a.sum() + b.sum()
    return 1.0 if total == 0 else float(2.0 * (a & b).sum() / total)


_PAIRS = _golden_pairs()


@pytest.fixture(scope="module")
def real_registry():
    return ModelRegistry()


@pytest.mark.skipif(not _PAIRS, reason="tests/golden/ has no <name>.png + <name>_mask.png pairs")
@pytest.mark.parametrize("model_key,image_path,mask_path", _PAIRS or [("", None, None)])
def test_golden_prediction(real_registry, model_key, image_path, mask_path):
    if model_key not in real_registry.keys():
        pytest.fail(f"golden files exist for {model_key!r} but model_store/ has no such model "
                    f"(found: {real_registry.keys()})")
    expected = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    assert expected is not None, f"cannot read {mask_path}"
    result = run_file(image_path, model_key, registry=real_registry, min_blob_pixels=0)
    predicted = result.slices[0].mask
    assert predicted.shape == expected.shape, (
        f"{image_path.name}: predicted {predicted.shape}, golden mask {expected.shape}")
    score = dice(predicted, expected > 127)
    assert score >= MIN_DICE, f"{model_key}/{image_path.name}: Dice {score:.4f} < {MIN_DICE}"


def test_dice_helper():
    a = np.zeros((4, 4), bool)
    assert dice(a, a) == 1.0
    b = a.copy(); b[0, :2] = True
    c = a.copy(); c[0, 1:3] = True
    assert dice(b, c) == pytest.approx(0.5)

"""Preprocessing: output shape, value range, and the copied training steps."""

from __future__ import annotations

import albumentations as A
import cv2
import numpy as np
import pytest
import torch

from inference import preprocess
from inference.preprocess import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    build_eval_transform,
    preprocess_slice,
    preprocess_slices,
    to_uint8_slice,
)

LOW = min((0.0 - m) / s for m, s in zip(IMAGENET_MEAN, IMAGENET_STD))
HIGH = max((1.0 - m) / s for m, s in zip(IMAGENET_MEAN, IMAGENET_STD))


def test_constants_match_training_repo():
    assert IMAGENET_MEAN == (0.485, 0.456, 0.406)
    assert IMAGENET_STD == (0.229, 0.224, 0.225)


@pytest.mark.parametrize("preprocessing", ["original", "clahe"])
def test_output_shape_dtype_and_range(raw_slice, preprocessing):
    tensor, image_u8 = preprocess_slice(raw_slice, intensity="raw", preprocessing=preprocessing)
    assert isinstance(tensor, torch.Tensor)
    assert tensor.shape == (3, 256, 256) and tensor.dtype == torch.float32
    assert torch.isfinite(tensor).all()
    assert tensor.min().item() >= LOW - 1e-4 and tensor.max().item() <= HIGH + 1e-4
    # Native-size 8-bit image for the overlay.
    assert image_u8.shape == raw_slice.shape and image_u8.dtype == np.uint8


def test_three_channels_are_the_same_gray_image(raw_slice):
    tensor, _ = preprocess_slice(raw_slice, intensity="raw")
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    unnorm = tensor * std + mean
    assert torch.allclose(unnorm[0], unnorm[1], atol=1e-5)
    assert torch.allclose(unnorm[0], unnorm[2], atol=1e-5)


def test_percentile_clip_matches_training_formula(raw_slice):
    lo, hi = np.percentile(raw_slice.astype(np.float32), [1.0, 99.0])
    expected = (np.clip((raw_slice - lo) / (hi - lo), 0.0, 1.0) * 255.0).astype(np.uint8)
    np.testing.assert_array_equal(to_uint8_slice(raw_slice, "raw"), expected)
    assert expected.min() == 0 and expected.max() == 255


def test_constant_image_does_not_divide_by_zero():
    out = to_uint8_slice(np.full((32, 32), 7.0, dtype=np.float32), "raw")
    assert out.dtype == np.uint8 and (out == 0).all()


def test_uint8_input_is_not_renormalised():
    u8 = np.random.default_rng(1).integers(40, 180, size=(256, 256)).astype(np.uint8)
    out = to_uint8_slice(u8.astype(np.float32), "uint8")
    np.testing.assert_array_equal(out, u8)


def test_training_png_reproduces_dataset_path(tmp_path):
    """A 256x256 8-bit PNG must give the tensor BrainTumorDataset + eval transform gave."""
    u8 = np.random.default_rng(2).integers(0, 256, size=(256, 256)).astype(np.uint8)
    path = tmp_path / "train.png"
    cv2.imwrite(str(path), u8)

    # The training dataset's path, written out by hand.
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    expected = build_eval_transform(256, "original")(image=rgb)["image"]

    from inference.loaders import load_scan

    scan = load_scan(path)
    tensor, _ = preprocess_slice(scan.slices[0], intensity=scan.meta["intensity"])
    assert torch.equal(tensor, expected.float())


def test_raw_slice_is_resized_with_inter_linear(raw_slice):
    u8 = to_uint8_slice(raw_slice, "raw")
    expected_png = cv2.resize(u8, (256, 256), interpolation=cv2.INTER_LINEAR)
    np.testing.assert_array_equal(preprocess.to_training_png(u8, 256), expected_png)


def test_eval_transform_layout():
    plain = build_eval_transform(256, "original").transforms
    assert [type(t) for t in plain] == [A.Resize, A.Normalize, preprocess.ToTensorV2]
    clahe = build_eval_transform(256, "clahe").transforms
    assert [type(t) for t in clahe] == [A.Resize, A.CLAHE, A.Normalize, preprocess.ToTensorV2]
    c = clahe[1]
    # Albumentations reads a scalar clip_limit as the UPPER bound of a range it
    # samples from on every call: (1.0, 2.0). The training repo has the same
    # call, so its CLAHE step is random at evaluation time too. Copied as is.
    assert tuple(c.clip_limit) == (1.0, 2.0)
    assert tuple(c.tile_grid_size) == (8, 8) and c.p == 1.0
    with pytest.raises(ValueError):
        build_eval_transform(256, "does_not_exist")


def test_batch_of_slices(raw_slice):
    batch, images = preprocess_slices([raw_slice, raw_slice * 0.5, raw_slice[:64, :64]])
    assert batch.shape == (3, 3, 256, 256)
    assert [im.shape for im in images] == [raw_slice.shape, raw_slice.shape, (64, 64)]
    with pytest.raises(ValueError):
        preprocess_slices([])

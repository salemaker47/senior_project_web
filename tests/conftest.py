"""Shared fixtures: synthetic scan files and a fake model store (random weights)."""

from __future__ import annotations

import cv2
import h5py
import numpy as np
import pytest

from inference.registry import ModelRegistry
from tests.fake_checkpoint import make_fake_model_store

FAKE_KEY = "fake_unet_image_level"


def synthetic_slice(height: int = 96, width: int = 128, seed: int = 0) -> np.ndarray:
    """A smooth 'brain' blob on a dark background, float32 with scanner-like range."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cy, cx = height / 2.0, width / 2.0
    r = np.sqrt(((yy - cy) / (height * 0.4)) ** 2 + ((xx - cx) / (width * 0.4)) ** 2)
    img = np.clip(1.0 - r, 0.0, 1.0) * 3000.0
    img += rng.normal(0.0, 30.0, size=img.shape).astype(np.float32) * (img > 0)
    return np.clip(img, 0.0, None).astype(np.float32)


@pytest.fixture(scope="session")
def fake_store(tmp_path_factory):
    """model_store with one key and three folds; fold 2 has the highest best_score."""
    root = tmp_path_factory.mktemp("model_store")
    make_fake_model_store(
        root, key=FAKE_KEY, fold_scores={1: 0.40, 2: 0.70, 3: 0.60},
        extra_state_keys=True,
    )
    return root


@pytest.fixture(scope="session")
def fake_registry(fake_store):
    return ModelRegistry(fake_store)


@pytest.fixture
def raw_slice():
    return synthetic_slice()


@pytest.fixture
def png_file(tmp_path, raw_slice):
    u8 = (raw_slice / raw_slice.max() * 255).astype(np.uint8)
    # Deliberately misleading extension: detection must use the content.
    path = tmp_path / "scan.dat"
    ok, buf = cv2.imencode(".png", u8)
    assert ok
    path.write_bytes(buf.tobytes())
    return path, u8


@pytest.fixture
def figshare_mat_file(tmp_path, raw_slice):
    """HDF5 with cjdata/image stored transposed, behind a 512-byte MATLAB header."""
    path = tmp_path / "figshare_like.bin"
    stored = raw_slice.astype(np.int16).T
    with h5py.File(path, "w", userblock_size=512) as f:
        g = f.create_group("cjdata")
        g.create_dataset("image", data=stored)
        g.create_dataset("tumorMask", data=np.zeros_like(stored, dtype=np.uint8))
        g.create_dataset("label", data=np.array([[1.0]]))
        g.create_dataset("PID", data=np.array([[49], [50]], dtype=np.uint16))
    with open(path, "r+b") as f:
        f.write(b"MATLAB 7.3 MAT-file, synthetic test file".ljust(116) + b"\x00" * 8 + b"\x00\x02IM")
    return path, raw_slice.astype(np.int16).astype(np.float32)


@pytest.fixture
def brats_h5_file(tmp_path, raw_slice):
    path = tmp_path / "volume_1_slice_70.bin"
    image = np.zeros(raw_slice.shape + (4,), dtype=np.float64)
    for c in range(4):
        image[..., c] = raw_slice * (c + 1)
    mask = np.zeros(raw_slice.shape + (3,), dtype=np.uint8)
    with h5py.File(path, "w") as f:
        f.create_dataset("image", data=image)
        f.create_dataset("mask", data=mask)
    return path, (raw_slice * 4).astype(np.float32)

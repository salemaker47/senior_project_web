"""Predictor, post-processing and a full run with the fake checkpoint."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from inference import DISCLAIMER
from inference.cli import main as cli_main
from inference.pipeline import run_file, save_slice_result
from inference.postprocess import (
    build_summary,
    make_overlay,
    remove_small_blobs,
    resize_mask,
)
from inference.predictor import predict_masks, predict_probabilities
from tests.conftest import FAKE_KEY

REPO_ROOT = Path(__file__).resolve().parent.parent


# ----- predictor ----------------------------------------------------------- #
class _CountingModel(torch.nn.Module):
    """Logit = mean of the input; records batch sizes and the inference-mode flag."""

    def __init__(self):
        super().__init__()
        self.batch_sizes = []
        self.inference_flags = []

    def forward(self, x):
        self.batch_sizes.append(x.shape[0])
        self.inference_flags.append(torch.is_inference_mode_enabled())
        return x.mean(dim=1, keepdim=True)


def test_predictor_batches_and_uses_inference_mode():
    model = _CountingModel()
    batch = torch.zeros(5, 3, 8, 8)
    batch[1] += 4.0                                   # sigmoid(4) ~ 0.98
    batch[3] -= 4.0
    masks, probs = predict_masks(model, batch, threshold=0.5, batch_size=2)
    assert model.batch_sizes == [2, 2, 1]
    assert all(model.inference_flags)
    assert probs.shape == (5, 8, 8) and probs.dtype == np.float32
    assert masks.dtype == bool
    assert masks[1].all() and not masks[3].any()
    assert not masks[0].any()                          # sigmoid(0) = 0.5 is not > 0.5
    with pytest.raises(ValueError):
        predict_probabilities(model, torch.zeros(3, 8, 8))


# ----- postprocess --------------------------------------------------------- #
def _mask_with_blobs():
    mask = np.zeros((64, 64), dtype=bool)
    mask[5:15, 5:15] = True         # 100 px
    mask[40:44, 40:44] = True       # 16 px
    mask[60, 60] = True             # 1 px
    return mask


def test_remove_small_blobs_default_and_disabled():
    mask = _mask_with_blobs()
    cleaned = remove_small_blobs(mask)                 # default 20
    assert cleaned.sum() == 100 and cleaned[5:15, 5:15].all()
    assert remove_small_blobs(mask, 0).sum() == mask.sum()
    assert remove_small_blobs(mask, 16).sum() == 116   # exactly min_pixels is kept
    assert remove_small_blobs(mask, 1000).sum() == 0
    assert remove_small_blobs(np.zeros((4, 4), bool)).sum() == 0


def test_resize_mask_is_nearest_neighbour():
    mask = np.zeros((256, 256), dtype=bool)
    mask[64:128, 64:192] = True
    out = resize_mask(mask, (512, 384))
    assert out.shape == (512, 384) and out.dtype == bool
    assert out.sum() == pytest.approx(mask.sum() * 2 * 1.5, rel=0.02)
    assert resize_mask(mask, (256, 256)) is not None


def test_overlay_is_red_inside_and_unchanged_outside():
    image = np.full((32, 32), 100, dtype=np.uint8)
    mask = np.zeros((32, 32), dtype=bool)
    mask[8:24, 8:24] = True
    overlay = make_overlay(image, mask)
    assert overlay.shape == (32, 32, 3) and overlay.dtype == np.uint8
    assert (overlay[0, 0] == 100).all()
    r, g, b = overlay[16, 16]
    assert r > 150 and g < 100 and b < 100
    assert tuple(overlay[8, 8]) == (255, 0, 0)         # contour pixel


def test_summary_fields():
    mask = np.zeros((10, 20), dtype=bool)
    mask[:2, :5] = True
    s = build_summary(mask, model_key="k", fold=3, threshold=0.5, run_seconds=1.23456,
                      min_blob_pixels=20)
    assert s["tumor_pixels"] == 10 and s["tumor_share"] == pytest.approx(0.05)
    assert s["model_key"] == "k" and s["fold"] == 3 and s["threshold"] == 0.5
    assert s["run_seconds"] == pytest.approx(1.2346)
    assert s["disclaimer"] == DISCLAIMER
    json.dumps(s)


# ----- full run with the fake checkpoint ----------------------------------- #
def _check_outputs(out_dir, shape):
    mask = cv2.imread(str(out_dir / "mask.png"), cv2.IMREAD_UNCHANGED)
    overlay = cv2.imread(str(out_dir / "overlay.png"), cv2.IMREAD_UNCHANGED)
    summary = json.loads((out_dir / "summary.json").read_text())
    assert mask.shape == shape and mask.dtype == np.uint8
    assert set(np.unique(mask)) <= {0, 255}
    assert overlay.shape == shape + (3,)
    assert summary["tumor_pixels"] == int((mask > 0).sum())
    assert summary["tumor_share"] == pytest.approx((mask > 0).mean())
    assert summary["model_key"] == FAKE_KEY and summary["fold"] == 2
    assert summary["threshold"] == 0.5 and summary["run_seconds"] > 0
    assert summary["disclaimer"] == DISCLAIMER
    return summary


def test_full_run_on_each_format(fake_registry, tmp_path, png_file, figshare_mat_file,
                                 brats_h5_file):
    for name, (path, expected) in {
        "png": png_file, "figshare_mat": figshare_mat_file, "brats_h5": brats_h5_file,
    }.items():
        result = run_file(path, FAKE_KEY, registry=fake_registry)
        assert result.n_slices == 1 and result.fold == 2
        sl = result.slices[0]
        assert sl.mask.shape == expected.shape == sl.image_u8.shape
        assert sl.overlay.shape == expected.shape + (3,)
        save_slice_result(sl, tmp_path / name)
        summary = _check_outputs(tmp_path / name, expected.shape)
        assert summary["input_format"] == name


def test_full_run_is_deterministic_and_blob_removal_only_removes(fake_registry, png_file):
    path, _ = png_file
    a = run_file(path, FAKE_KEY, registry=fake_registry, min_blob_pixels=0).slices[0].mask
    b = run_file(path, FAKE_KEY, registry=fake_registry, min_blob_pixels=0).slices[0].mask
    np.testing.assert_array_equal(a, b)
    cleaned = run_file(path, FAKE_KEY, registry=fake_registry, min_blob_pixels=20).slices[0].mask
    assert not (cleaned & ~a).any()


def test_cli_writes_three_files(fake_store, tmp_path, png_file, capsys):
    path, u8 = png_file
    out = tmp_path / "out"
    code = cli_main(["--model-store", str(fake_store), "predict", str(path),
                     "--model", FAKE_KEY, "--out", str(out)])
    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["mask.png", "overlay.png", "summary.json"]
    _check_outputs(out, u8.shape)
    assert DISCLAIMER in capsys.readouterr().out


def test_cli_as_module(fake_store, tmp_path, png_file):
    path, u8 = png_file
    out = tmp_path / "out_module"
    proc = subprocess.run(
        [sys.executable, "-m", "inference", "--model-store", str(fake_store),
         "predict", str(path), "--model", FAKE_KEY, "--out", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    _check_outputs(out, u8.shape)


def test_cli_errors(fake_store, tmp_path, png_file, capsys):
    path, _ = png_file
    base = ["--model-store", str(fake_store)]
    assert cli_main(base + ["predict", str(path), "--model", "nope", "--out", str(tmp_path)]) == 2
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image" * 50)
    assert cli_main(base + ["predict", str(bad), "--model", FAKE_KEY, "--out", str(tmp_path)]) == 2
    assert cli_main(base + ["predict", str(path), "--model", FAKE_KEY, "--out", str(tmp_path),
                            "--slice", "5"]) == 2
    assert cli_main(base + ["list"]) == 0
    assert FAKE_KEY in capsys.readouterr().out


# ----- package rule -------------------------------------------------------- #
def test_inference_package_does_not_import_django():
    for py in sorted((REPO_ROOT / "inference").glob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "django" for n in names), py.name

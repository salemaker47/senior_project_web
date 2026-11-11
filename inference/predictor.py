"""
inference/predictor.py

Run a segmentation model on CPU. The model returns logits (N, 1, H, W); the
mask is `sigmoid(logits) > threshold`, as in the training repo.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import torch

DEVICE = torch.device("cpu")
DEFAULT_BATCH_SIZE = 8


def predict_probabilities(
    model: torch.nn.Module,
    batch: torch.Tensor,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> np.ndarray:
    """(N, 3, H, W) float tensor -> (N, H, W) float32 probabilities, batched over slices."""
    if batch.ndim != 4 or batch.shape[1] != 3:
        raise ValueError(f"expected a (N, 3, H, W) tensor, got {tuple(batch.shape)}")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    model = model.to(DEVICE).eval()
    out = []
    with torch.inference_mode():
        for start in range(0, batch.shape[0], batch_size):
            x = batch[start:start + batch_size].to(DEVICE, dtype=torch.float32)
            logits = model(x)
            if logits.ndim != 4 or logits.shape[1] != 1:
                raise RuntimeError(f"model returned shape {tuple(logits.shape)}, expected (N, 1, H, W)")
            out.append(torch.sigmoid(logits)[:, 0].cpu())
    return torch.cat(out, dim=0).numpy().astype(np.float32)


def predict_masks(
    model: torch.nn.Module,
    batch: torch.Tensor,
    threshold: float = 0.5,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (masks (N, H, W) bool, probabilities (N, H, W) float32)."""
    probs = predict_probabilities(model, batch, batch_size=batch_size)
    return probs > float(threshold), probs

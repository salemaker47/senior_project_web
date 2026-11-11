"""
Build a tiny random-weight checkpoint in the exact dict layout the training
repo writes (`train_utils.export_plain_state_dict` + NB03's extra_meta and
experiment_config.json), so tests and the CLI demo run without real models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import torch

from inference.models import build_model

FAKE_MODEL_NAME = "smp_unet_resnet34"


def fake_experiment(
    *,
    key: str = "fake_unet_image_level",
    dataset: str = "figshare",
    preprocessing: str = "original",
    fold: int = 1,
    threshold: float = 0.5,
    image_size: int = 256,
    model_name: str = FAKE_MODEL_NAME,
) -> Dict[str, Any]:
    """Same keys as configs/seg/reference_experiments.BASE_EXPERIMENT + per-call fields."""
    return {
        "task": "segmentation",
        "image_size": image_size,
        "batch_size": 8,
        "num_workers": 2,
        "preprocessing": preprocessing,
        "augmentation_strength": "reference",
        "model_name": model_name,
        "encoder_weights": "imagenet",
        "optimizer_name": "adam",
        "optimizer_kwargs": {"lr": 1e-4},
        "scheduler_name": "reduce_on_plateau",
        "scheduler_kwargs": {"mode": "min", "factor": 0.1, "patience": 5, "min_lr": 1e-7},
        "scheduler_monitor": "val_loss",
        "metric_kind": "micro",
        "max_epochs": 100,
        "patience": 15,
        "threshold": threshold,
        "seed": 42,
        "loss_name": "dice_bce",
        "loss_kwargs": {"bce_weight": 1.0, "dice_weight": 1.0},
        "dataset": dataset,
        "split_scheme": "image_level",
        "fold": fold,
        "recipe": "03_dicebce",
        "name": key,
    }


def write_fake_fold(
    fold_dir: Path,
    experiment: Dict[str, Any],
    *,
    best_score: Optional[float] = 0.5,
    seed: int = 0,
    write_config: bool = True,
    extra_state_keys: bool = False,
    state_dict: Optional[Dict[str, torch.Tensor]] = None,
) -> Path:
    """
    Write fold_dir/best_model.pt (+ experiment_config.json). Returns the .pt path.

    `extra_state_keys=True` adds a `loss_fn.pos_weight` buffer, which the
    registry must drop before the strict load.
    """
    fold_dir = Path(fold_dir)
    fold_dir.mkdir(parents=True, exist_ok=True)
    if state_dict is None:
        torch.manual_seed(seed)
        model = build_model(experiment["model_name"], encoder_weights=None)
        state_dict = {k: v.detach().clone() for k, v in model.state_dict().items()}
    sd = dict(state_dict)
    if extra_state_keys:
        sd["loss_fn.pos_weight"] = torch.tensor([1.0])

    blob = {
        "state_dict": sd,
        "epoch": 3,
        "best_score": best_score,
        "extra_meta": {
            "experiment": dict(experiment),
            "model_name": experiment["model_name"],
            "encoder_weights": experiment["encoder_weights"],
        },
    }
    pt_path = fold_dir / "best_model.pt"
    torch.save(blob, pt_path)

    if write_config:
        cfg = {
            "EXPERIMENT": dict(experiment),
            "training_meta": {
                "fold": experiment.get("fold", 1),
                "best_epoch": 3,
                "best_val_dice": best_score,
                "test_dice": None,
                "test_iou": None,
                "total_epochs_trained": 4,
                "train_seconds": 1.0,
                "params_count": sum(int(v.numel()) for v in sd.values()),
                "peak_gpu_mem_mb": None,
                "best_ckpt_path": "fake",
            },
            "repro_metadata": {"lib_versions": {"torch": torch.__version__}},
        }
        with open(fold_dir / "experiment_config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    return pt_path


def make_fake_model_store(
    root: Path,
    *,
    key: str = "fake_unet_image_level",
    fold_scores: Optional[Dict[int, Optional[float]]] = None,
    dataset: str = "figshare",
    preprocessing: str = "original",
    threshold: float = 0.5,
    **fold_kwargs: Any,
) -> Path:
    """Create root/<key>/fold_<k>/... for each fold in fold_scores. Returns root."""
    root = Path(root)
    if fold_scores is None:
        fold_scores = {1: 0.5}
    # One random model shared by all folds keeps the fixture fast.
    torch.manual_seed(0)
    base = build_model(FAKE_MODEL_NAME, encoder_weights=None)
    sd = {k: v.detach().clone() for k, v in base.state_dict().items()}
    for fold, score in fold_scores.items():
        exp = fake_experiment(key=key, dataset=dataset, preprocessing=preprocessing,
                              fold=fold, threshold=threshold)
        write_fake_fold(root / key / f"fold_{fold}", exp, best_score=score,
                        state_dict=sd, **fold_kwargs)
    return root

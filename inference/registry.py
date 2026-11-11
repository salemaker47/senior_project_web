"""
inference/registry.py

Finds trained models under `model_store/`, picks the best fold per model key
and loads the weights on demand (cached).

Expected layout (model_store/ is git-ignored):

    model_store/<model_key>/fold_<k>/best_model.pt
    model_store/<model_key>/fold_<k>/experiment_config.json   (optional but expected)

`best_model.pt` is the plain checkpoint written by the training repo:
    {"state_dict": {...}, "epoch": int, "best_score": float|None, "extra_meta": {...}}
with `extra_meta = {"experiment": EXPERIMENT, "model_name": ..., "encoder_weights": ...}`.

`experiment_config.json` holds {"EXPERIMENT": {...}, "training_meta": {...},
"repro_metadata": {...}}.

Fold selection: the fold with the highest `best_score` in `best_model.pt`.
`best_score` is the best validation Dice, identical to
`training_meta.best_val_dice` in the JSON; the JSON is read first because it is
cheap, and `best_model.pt` is only opened for folds whose JSON lacks the value.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from .models import ARCH_LABELS, build_model

PT_FILENAME = "best_model.pt"
CONFIG_FILENAME = "experiment_config.json"
MODEL_STORE_ENV = "MODEL_STORE_DIR"
DEFAULT_MODEL_STORE = Path(__file__).resolve().parent.parent / "model_store"

# State-dict key handling, same as train_utils.select_model_state_dict.
MODEL_PREFIX = "model."
NON_MODEL_PREFIXES = ("loss_fn.",)

_FOLD_DIR_RE = re.compile(r"^fold_(\d+)$")

DATASET_LABELS = {
    "figshare":  "FigShare (T1 contrast-enhanced)",
    "brats2020": "BraTS 2020 (FLAIR, skull-stripped)",
}
SCAN_TYPES = {
    "figshare":  "T1ce",
    "brats2020": "FLAIR",
}
SCAN_TYPE_LABELS = {
    "figshare":  "T1 contrast-enhanced slice",
    "brats2020": "Skull-stripped FLAIR slice",
}


class RegistryError(RuntimeError):
    """Raised for a missing model key, an unreadable checkpoint or a mismatch."""


def select_model_state_dict(sd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Copy of train_utils.select_model_state_dict: keep only the model's own
    weights, ready for `load_state_dict(..., strict=True)`.
    """
    if any(k.startswith(MODEL_PREFIX) for k in sd):
        return {k[len(MODEL_PREFIX):]: v for k, v in sd.items() if k.startswith(MODEL_PREFIX)}
    return {k: v for k, v in sd.items() if not k.startswith(NON_MODEL_PREFIXES)}


@dataclass
class FoldEntry:
    fold: int
    pt_path: Path
    config_path: Optional[Path]
    best_score: Optional[float]


@dataclass
class ModelEntry:
    """Everything the web app needs to describe and run one model key."""
    key: str
    display_label: str
    scan_type: str
    scan_type_label: str
    dataset: str
    model_name: str
    fold: int
    best_score: Optional[float]
    threshold: float
    image_size: int
    preprocessing: str
    pt_path: Path
    config_path: Optional[Path]
    config: Dict[str, Any] = field(default_factory=dict)      # the EXPERIMENT dict
    folds: Dict[int, Optional[float]] = field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        """JSON-safe description without filesystem paths."""
        return {
            "key":             self.key,
            "display_label":   self.display_label,
            "scan_type":       self.scan_type,
            "scan_type_label": self.scan_type_label,
            "dataset":         self.dataset,
            "model_name":      self.model_name,
            "fold":            self.fold,
            "best_score":      self.best_score,
            "threshold":       self.threshold,
            "image_size":      self.image_size,
            "preprocessing":   self.preprocessing,
            "folds":           {str(k): v for k, v in sorted(self.folds.items())},
        }


# --------------------------------------------------------------------------- #
# Checkpoint reading
# --------------------------------------------------------------------------- #
def load_checkpoint(pt_path: Path) -> Dict[str, Any]:
    """
    torch.load with weights_only=True. The plain checkpoint holds only tensors
    and primitive containers, so the safe loader is sufficient. If a real file
    fails here, report it rather than relaxing the flag.
    """
    try:
        blob = torch.load(pt_path, map_location="cpu", weights_only=True)
    except Exception as exc:  # noqa: BLE001 - we re-raise with context
        raise RegistryError(
            f"torch.load(weights_only=True) failed for {pt_path}: {exc}"
        ) from exc
    if not isinstance(blob, dict) or "state_dict" not in blob:
        raise RegistryError(f"{pt_path} is not a plain checkpoint dict with 'state_dict'")
    return blob


def _read_config_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _experiment_from_config_json(saved: Dict[str, Any]) -> Dict[str, Any]:
    exp = saved.get("EXPERIMENT") or saved.get("experiment") or {}
    return dict(exp) if isinstance(exp, dict) else {}


def _best_score_from_config_json(saved: Dict[str, Any]) -> Optional[float]:
    tm = saved.get("training_meta") or {}
    v = tm.get("best_val_dice") if isinstance(tm, dict) else None
    return float(v) if v is not None else None


def _display_label(model_name: str, experiment: Dict[str, Any], key: str) -> str:
    arch = ARCH_LABELS.get(model_name.lower(), model_name)
    dataset = str(experiment.get("dataset", ""))
    ds = DATASET_LABELS.get(dataset, dataset)
    loss = str(experiment.get("loss_name", "")).replace("_", "+").upper()
    scheme = str(experiment.get("split_scheme", "")).replace("_", "-")
    parts = [arch]
    if loss:
        parts.append(loss)
    if ds:
        parts.append(ds)
    if scheme:
        parts.append(f"{scheme} split")
    return " · ".join(parts) if parts else key


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class ModelRegistry:
    """
    Scans a model store once (lazily) and caches loaded models.

        reg = ModelRegistry()                 # uses $MODEL_STORE_DIR or ./model_store
        reg.list()                            # [ModelEntry, ...] sorted by key
        entry = reg.get("07_unetpp_effb4_dicebce_image_level")
        model = reg.load(entry.key)           # cached nn.Module in eval mode, CPU
    """

    def __init__(self, model_store: Optional[os.PathLike] = None):
        if model_store is None:
            model_store = os.environ.get(MODEL_STORE_ENV) or DEFAULT_MODEL_STORE
        self.model_store = Path(model_store)
        self._entries: Optional[Dict[str, ModelEntry]] = None
        self._models: Dict[str, torch.nn.Module] = {}

    # ----- scanning -------------------------------------------------------- #
    def refresh(self) -> Dict[str, ModelEntry]:
        """Re-scan the store. Loaded models stay cached by key."""
        self._entries = scan_model_store(self.model_store)
        return self._entries

    @property
    def entries(self) -> Dict[str, ModelEntry]:
        if self._entries is None:
            self.refresh()
        return self._entries  # type: ignore[return-value]

    def list(self) -> List[ModelEntry]:
        return [self.entries[k] for k in sorted(self.entries)]

    def keys(self) -> List[str]:
        return sorted(self.entries)

    def get(self, key: str) -> ModelEntry:
        try:
            return self.entries[key]
        except KeyError:
            raise RegistryError(
                f"unknown model key {key!r}. Available: {self.keys() or 'none'} "
                f"(model store: {self.model_store})"
            ) from None

    # ----- loading --------------------------------------------------------- #
    def load(self, key: str) -> torch.nn.Module:
        """Build the architecture, load the weights strictly, cache, eval mode, CPU."""
        if key in self._models:
            return self._models[key]
        entry = self.get(key)
        model = load_model_from_entry(entry)
        self._models[key] = model
        return model

    def clear_cache(self) -> None:
        self._models.clear()


def scan_model_store(model_store: Path) -> Dict[str, ModelEntry]:
    """Return {model_key: ModelEntry} for every key with at least one usable fold."""
    model_store = Path(model_store)
    entries: Dict[str, ModelEntry] = {}
    if not model_store.is_dir():
        return entries

    for key_dir in sorted(p for p in model_store.iterdir() if p.is_dir()):
        folds = _scan_folds(key_dir)
        if not folds:
            continue
        best = _pick_best_fold(folds)
        entries[key_dir.name] = _make_entry(key_dir.name, best, folds)
    return entries


def _scan_folds(key_dir: Path) -> List[FoldEntry]:
    folds: List[FoldEntry] = []
    for fold_dir in sorted(p for p in key_dir.iterdir() if p.is_dir()):
        m = _FOLD_DIR_RE.match(fold_dir.name)
        if not m:
            continue
        pt_path = fold_dir / PT_FILENAME
        if not pt_path.is_file():
            continue
        cfg_path = fold_dir / CONFIG_FILENAME
        best_score: Optional[float] = None
        if cfg_path.is_file():
            try:
                best_score = _best_score_from_config_json(_read_config_json(cfg_path))
            except (OSError, ValueError):
                best_score = None
        if best_score is None:
            bs = load_checkpoint(pt_path).get("best_score")
            best_score = float(bs) if bs is not None else None
        folds.append(FoldEntry(
            fold=int(m.group(1)),
            pt_path=pt_path,
            config_path=cfg_path if cfg_path.is_file() else None,
            best_score=best_score,
        ))
    return folds


def _pick_best_fold(folds: List[FoldEntry]) -> FoldEntry:
    scored = [f for f in folds if f.best_score is not None]
    if scored:
        # Highest score wins; ties go to the lowest fold number.
        return max(scored, key=lambda f: (f.best_score, -f.fold))
    return min(folds, key=lambda f: f.fold)


def _make_entry(key: str, best: FoldEntry, folds: List[FoldEntry]) -> ModelEntry:
    experiment: Dict[str, Any] = {}
    if best.config_path is not None:
        experiment = _experiment_from_config_json(_read_config_json(best.config_path))
    if not experiment:
        extra = load_checkpoint(best.pt_path).get("extra_meta") or {}
        experiment = dict(extra.get("experiment") or {})
        if not experiment and extra.get("model_name"):
            experiment = {"model_name": extra["model_name"]}
    if not experiment.get("model_name"):
        raise RegistryError(
            f"{key}/fold_{best.fold}: no model_name in {CONFIG_FILENAME} or extra_meta"
        )

    model_name = str(experiment["model_name"])
    dataset = str(experiment.get("dataset", ""))
    return ModelEntry(
        key=key,
        display_label=_display_label(model_name, experiment, key),
        scan_type=SCAN_TYPES.get(dataset, dataset or "unknown"),
        scan_type_label=SCAN_TYPE_LABELS.get(dataset, dataset or "unknown"),
        dataset=dataset,
        model_name=model_name,
        fold=best.fold,
        best_score=best.best_score,
        threshold=float(experiment.get("threshold", 0.5)),
        image_size=int(experiment.get("image_size", 256)),
        preprocessing=str(experiment.get("preprocessing", "original")),
        pt_path=best.pt_path,
        config_path=best.config_path,
        config=experiment,
        folds={f.fold: f.best_score for f in folds},
    )


def load_model_from_entry(entry: ModelEntry) -> torch.nn.Module:
    """weights_only load, drop non-model keys, strict load, eval, CPU."""
    blob = load_checkpoint(entry.pt_path)
    extra = blob.get("extra_meta") or {}
    ckpt_model_name = extra.get("model_name") or (extra.get("experiment") or {}).get("model_name")
    if ckpt_model_name and str(ckpt_model_name).lower() != entry.model_name.lower():
        raise RegistryError(
            f"{entry.key}/fold_{entry.fold}: {CONFIG_FILENAME} says model_name="
            f"{entry.model_name!r} but {PT_FILENAME} says {ckpt_model_name!r}"
        )
    state_dict = select_model_state_dict(blob["state_dict"])
    model = build_model(entry.model_name, encoder_weights=None)
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    return model.to("cpu")


_default_registry: Optional[ModelRegistry] = None


def default_registry() -> ModelRegistry:
    """Process-wide registry over $MODEL_STORE_DIR / ./model_store."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelRegistry()
    return _default_registry

"""Model registry: discovery, best fold, safe + strict loading, caching."""

from __future__ import annotations

import pytest
import torch

from inference.registry import (
    ModelRegistry,
    RegistryError,
    load_checkpoint,
    select_model_state_dict,
)
from tests.conftest import FAKE_KEY
from tests.fake_checkpoint import fake_experiment, write_fake_fold


def test_finds_model_and_picks_highest_best_score(fake_registry):
    assert fake_registry.keys() == [FAKE_KEY]
    entry = fake_registry.get(FAKE_KEY)
    assert entry.fold == 2 and entry.best_score == pytest.approx(0.70)
    assert entry.folds == {1: 0.40, 2: 0.70, 3: 0.60}
    assert entry.pt_path.name == "best_model.pt" and entry.pt_path.parent.name == "fold_2"


def test_entry_exposes_key_label_scan_type_and_config(fake_registry):
    entry = fake_registry.get(FAKE_KEY)
    assert entry.key == FAKE_KEY
    assert "U-Net (ResNet34)" in entry.display_label and "FigShare" in entry.display_label
    assert entry.scan_type == "T1ce"
    assert entry.dataset == "figshare"
    assert entry.threshold == 0.5 and entry.image_size == 256
    assert entry.preprocessing == "original"
    assert entry.config["model_name"] == "smp_unet_resnet34"
    public = entry.to_public_dict()
    assert "pt_path" not in public and public["fold"] == 2


def test_brats_scan_type(tmp_path):
    exp = fake_experiment(key="brats_model", dataset="brats2020", preprocessing="clahe")
    write_fake_fold(tmp_path / "brats_model" / "fold_1", exp, best_score=0.8)
    entry = ModelRegistry(tmp_path).get("brats_model")
    assert entry.scan_type == "FLAIR" and entry.preprocessing == "clahe"


def test_checkpoint_loads_with_weights_only(fake_registry):
    blob = load_checkpoint(fake_registry.get(FAKE_KEY).pt_path)
    assert set(blob) == {"state_dict", "epoch", "best_score", "extra_meta"}
    assert blob["extra_meta"]["experiment"]["dataset"] == "figshare"


def test_non_weight_keys_are_dropped_and_load_is_strict(fake_registry):
    blob = load_checkpoint(fake_registry.get(FAKE_KEY).pt_path)
    assert "loss_fn.pos_weight" in blob["state_dict"]          # fixture put it there
    assert "loss_fn.pos_weight" not in select_model_state_dict(blob["state_dict"])
    model = fake_registry.load(FAKE_KEY)                        # strict=True inside
    assert not model.training
    assert next(model.parameters()).device.type == "cpu"


def test_select_model_state_dict_handles_lightning_prefix():
    sd = {"model.a": 1, "model.b.c": 2, "loss_fn.pos_weight": 3}
    assert select_model_state_dict(sd) == {"a": 1, "b.c": 2}
    assert select_model_state_dict({"a": 1, "loss_fn.x": 2}) == {"a": 1}


def test_loaded_models_are_cached(fake_registry):
    assert fake_registry.load(FAKE_KEY) is fake_registry.load(FAKE_KEY)


def test_wrong_architecture_fails_strict_load(tmp_path):
    exp = fake_experiment(key="broken")
    bad_sd = {"encoder.conv1.weight": torch.zeros(1)}
    write_fake_fold(tmp_path / "broken" / "fold_1", exp, state_dict=bad_sd)
    with pytest.raises(RuntimeError):
        ModelRegistry(tmp_path).load("broken")


def test_best_score_falls_back_to_checkpoint_without_json(tmp_path):
    exp = fake_experiment(key="nojson")
    sd = {"w": torch.zeros(1)}
    write_fake_fold(tmp_path / "nojson" / "fold_1", exp, best_score=0.3, state_dict=sd,
                    write_config=False)
    write_fake_fold(tmp_path / "nojson" / "fold_4", exp, best_score=0.9, state_dict=sd,
                    write_config=False)
    entry = ModelRegistry(tmp_path).get("nojson")
    assert entry.fold == 4 and entry.config_path is None
    assert entry.config["model_name"] == "smp_unet_resnet34"   # from extra_meta


def test_unknown_key_and_empty_store(tmp_path):
    reg = ModelRegistry(tmp_path)
    assert reg.list() == []
    with pytest.raises(RegistryError):
        reg.get("missing")
    assert ModelRegistry(tmp_path / "does_not_exist").list() == []


def test_folders_without_checkpoints_are_ignored(tmp_path):
    (tmp_path / "empty_key" / "fold_1").mkdir(parents=True)
    (tmp_path / "notes").mkdir()
    assert ModelRegistry(tmp_path).list() == []

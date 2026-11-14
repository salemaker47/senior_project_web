#!/usr/bin/env python
"""
Put the model files that were uploaded to the Space into model_store/.

    python deploy/huggingface/install_model.py <space_dir> <model_store_dir>

Two layouts are accepted in <space_dir>:

  1. best_model.pt + experiment_config.json at the top level (the simple way:
     drag the two files of one fold into the Space). The target folder
     <model_key>/fold_<k>/ is read from the config ("name" and "fold").
  2. A model_store/ folder that already has <model_key>/fold_<k>/... inside.

A missing model is not an error: the site starts and says that no model is
installed. A model file that is only a Git LFS pointer is an error, because
the site could never load it.

Standard library only; it runs while the image is built.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PT_NAME = "best_model.pt"
CONFIG_NAME = "experiment_config.json"
LFS_MARKER = b"version https://git-lfs"


def is_lfs_pointer(path: Path) -> bool:
    if path.stat().st_size > 2048:
        return False
    return path.read_bytes().startswith(LFS_MARKER)


def check_real_file(path: Path) -> None:
    if is_lfs_pointer(path):
        raise SystemExit(
            f"error: {path} is a Git LFS pointer, not the model itself. "
            "Upload the real file through the Space's 'Files' page."
        )


def target_from_config(config_path: Path) -> tuple[str, int]:
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    experiment = saved.get("EXPERIMENT") or saved.get("experiment") or {}
    name, fold = experiment.get("name"), experiment.get("fold")
    if not name or fold is None:
        raise SystemExit(f"error: {config_path} has no EXPERIMENT name and fold")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))
    return safe, int(fold)


def install(space_dir: Path, store_dir: Path) -> list[Path]:
    installed: list[Path] = []
    store_dir.mkdir(parents=True, exist_ok=True)

    nested = space_dir / "model_store"
    if nested.is_dir():
        for pt in sorted(nested.glob(f"*/fold_*/{PT_NAME}")):
            check_real_file(pt)
            dest = store_dir / pt.parent.parent.name / pt.parent.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pt, dest / PT_NAME)
            if (pt.parent / CONFIG_NAME).is_file():
                shutil.copy2(pt.parent / CONFIG_NAME, dest / CONFIG_NAME)
            installed.append(dest)

    top_pt, top_cfg = space_dir / PT_NAME, space_dir / CONFIG_NAME
    if top_pt.is_file():
        check_real_file(top_pt)
        if not top_cfg.is_file():
            raise SystemExit(f"error: {PT_NAME} was uploaded without {CONFIG_NAME}; upload both")
        key, fold = target_from_config(top_cfg)
        dest = store_dir / key / f"fold_{fold}"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(top_pt, dest / PT_NAME)
        shutil.copy2(top_cfg, dest / CONFIG_NAME)
        installed.append(dest)
    return installed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    installed = install(Path(argv[1]), Path(argv[2]))
    if installed:
        for dest in installed:
            size_mb = (dest / PT_NAME).stat().st_size / 1_048_576
            print(f"installed model: {dest}  ({size_mb:.0f} MB)")
    else:
        print("WARNING: no model files found in the Space. Upload best_model.pt and "
              "experiment_config.json, then rebuild. The site will start without a model.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

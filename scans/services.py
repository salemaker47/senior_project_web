"""
scans/services.py — the parts of the app that touch files and the model store.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from django.conf import settings

from .consent import is_valid_owner_id
from .models import Scan

SCANS_SUBDIR = "scans"

# Formats the Phase 1 loaders accept (detected from content, not extension).
SUPPORTED_FORMATS = [
    "PNG, JPEG or TIFF image of one slice",
    "FigShare brain-tumour .mat file",
    "BraTS 2020 slice .h5 file",
    "Single DICOM file",
]

_registries: Dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# Visitor data
# --------------------------------------------------------------------------- #
def owner_media_dir(owner_id: str) -> Path:
    """MEDIA_ROOT/scans/<owner_id>. Refuses anything that is not one of our ids."""
    if not is_valid_owner_id(owner_id):
        raise ValueError("invalid owner id")
    return Path(settings.MEDIA_ROOT) / SCANS_SUBDIR / owner_id


def scan_media_dir(owner_id: str, scan_id) -> Path:
    return owner_media_dir(owner_id) / str(scan_id)


def delete_owner_data(owner_id: str) -> Dict[str, int]:
    """Remove every scan row and every stored file of one visitor."""
    deleted_rows, _ = Scan.objects.filter(owner_id=owner_id).delete()
    folder = owner_media_dir(owner_id)
    files = 0
    if folder.is_dir():
        files = sum(1 for p in folder.rglob("*") if p.is_file())
        shutil.rmtree(folder)
    return {"scans": deleted_rows, "files": files}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def get_registry():
    """
    Model registry over settings.MODEL_STORE_DIR, one per path. Imported lazily:
    `inference` pulls in torch, which the home page does not need.
    """
    path = str(settings.MODEL_STORE_DIR)
    if path not in _registries:
        from inference.registry import ModelRegistry

        _registries[path] = ModelRegistry(path)
    return _registries[path]


def list_served_models() -> Dict[str, Any]:
    """
    {"models": [public dicts], "error": str}. Never raises: the about page
    must render even when a checkpoint folder is broken.
    """
    try:
        registry = get_registry()
        models: List[Dict[str, Any]] = [e.to_public_dict() for e in registry.list()]
        return {"models": models, "error": ""}
    except Exception as exc:  # noqa: BLE001 - shown on the about page instead
        return {"models": [], "error": str(exc)}

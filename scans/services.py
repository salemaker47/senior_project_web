"""
scans/services.py — everything that touches files, the model store and the
`inference` package. Views stay thin.

Storage layout (MEDIA_ROOT is never served directly; see views.scan_file):

    media/scans/<scan id>/<random>.npz    pixel data of the uploaded slices
    media/scans/<scan id>/<random>.png    original / mask / overlay of a prediction

The uploaded file itself is parsed and then discarded. Only pixel values and
the loader's technical metadata are kept, so DICOM patient tags (and the
FigShare patient id, EXIF data, ...) are never stored.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from django.conf import settings

from inference import DISCLAIMER

from .models import Prediction, Scan

SCANS_SUBDIR = "scans"

# Formats the Phase 1 loaders accept (detected from content, not extension).
SUPPORTED_FORMATS = [
    "PNG, JPEG or TIFF image of one slice",
    "FigShare brain-tumour .mat file",
    "BraTS 2020 slice .h5 file",
    "Single DICOM file",
]

# Model scan type (registry) -> heading of the choice group in the upload form.
SCAN_TYPE_GROUPS = {
    "T1ce": "T1 contrast-enhanced scans",
    "FLAIR": "FLAIR scans (skull-stripped)",
}

# Files of a prediction that can be requested, and how downloads are named.
RESULT_FILES = {
    "original": ("original_path", "original.png"),
    "mask": ("mask_path", "mask.png"),
    "overlay": ("overlay_path", "overlay.png"),
}

_registries: Dict[str, Any] = {}


class UploadRejected(Exception):
    """The uploaded file cannot be used. `str(exc)` is shown to the visitor."""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def scan_media_dir(scan_id) -> Path:
    """MEDIA_ROOT/scans/<scan id>."""
    return Path(settings.MEDIA_ROOT) / SCANS_SUBDIR / str(scan_id)


def random_name(extension: str) -> str:
    """A file name that says nothing about its content: 32 hex characters."""
    return f"{secrets.token_hex(16)}.{extension.lstrip('.')}"


def _relative(path: Path) -> str:
    return path.relative_to(Path(settings.MEDIA_ROOT)).as_posix()


def media_path(relative_path: str) -> Optional[Path]:
    """Absolute path of a stored file, or None if empty, missing or outside MEDIA_ROOT."""
    if not relative_path:
        return None
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def clean_display_name(name: str) -> str:
    """Basename of the upload without control characters, at most 120 characters."""
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:120] or "scan"


# --------------------------------------------------------------------------- #
# Upload: parse, validate, store
# --------------------------------------------------------------------------- #
def max_upload_mb() -> int:
    return settings.SCAN_MAX_UPLOAD_BYTES // (1024 * 1024)


def too_large_message() -> str:
    return f"The file is larger than {max_upload_mb()} MB, the limit for a 2D scan."


def _image_size_without_decoding(path: Path) -> Optional[Tuple[int, int]]:
    """(width, height) from the image header, so a huge image is refused before decoding."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - not a format PIL knows; the loader decides
        return None


def parse_upload(uploaded_file):
    """
    Read an uploaded file with the `inference` loaders.

    Returns a `LoadedScan`. Raises `UploadRejected` with a message for the
    visitor if the file is too large, is not a supported format or cannot be
    decoded.
    """
    from inference import loaders

    if uploaded_file.size > settings.SCAN_MAX_UPLOAD_BYTES:
        raise UploadRejected(too_large_message())
    if uploaded_file.size == 0:
        raise UploadRejected("The file is empty.")

    temp_path: Optional[Path] = None
    try:
        if hasattr(uploaded_file, "temporary_file_path"):
            path = Path(uploaded_file.temporary_file_path())
        else:
            with tempfile.NamedTemporaryFile(prefix="scan_upload_", delete=False) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
            temp_path = path = Path(tmp.name)

        try:
            fmt = loaders.detect_format(path)
        except loaders.UnsupportedFormatError as exc:
            raise UploadRejected(f"This file is not a scan the site can read: {exc}") from exc

        max_pixels = settings.SCAN_MAX_PIXELS
        if fmt in loaders.IMAGE_FORMATS:
            size = _image_size_without_decoding(path)
            if size and size[0] * size[1] > max_pixels:
                raise UploadRejected(
                    f"The image is {size[0]} x {size[1]} pixels, which is too large to process."
                )

        try:
            scan = loaders.load_scan(path)
        except UploadRejected:
            raise
        except Exception as exc:  # noqa: BLE001 - any decoding failure is the same to the visitor
            raise UploadRejected(
                f"The file looks like {fmt.replace('_', ' ')} but could not be read: {exc}"
            ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if not scan.slices:
        raise UploadRejected("The file contains no image data.")
    height, width = scan.slices[0].shape
    if height < 8 or width < 8:
        raise UploadRejected(f"The image is only {width} x {height} pixels.")
    if height * width > max_pixels:
        raise UploadRejected(f"The image is {width} x {height} pixels, which is too large to process.")
    if not all(np.isfinite(s).all() for s in scan.slices):
        raise UploadRejected("The image contains invalid values (NaN or infinity).")
    return scan


def create_scan(session_key: str, upload_name: str, size_bytes: int, loaded) -> Scan:
    """Store the pixel data of a parsed upload and create its Scan row."""
    if not session_key:
        raise ValueError("a scan needs the visitor's session key")
    scan = Scan(
        session_key=session_key,
        original_name=clean_display_name(upload_name),
        detected_format=str(loaded.meta.get("format", "")),
        size_bytes=int(size_bytes),
        height=int(loaded.slices[0].shape[0]),
        width=int(loaded.slices[0].shape[1]),
        n_slices=len(loaded.slices),
        meta=json.loads(json.dumps(loaded.meta, default=str)),
    )
    folder = scan_media_dir(scan.id)
    folder.mkdir(parents=True, exist_ok=False)
    data_file = folder / random_name("npz")
    try:
        np.savez_compressed(data_file, slices=np.stack(loaded.slices).astype(np.float32))
        scan.data_path = _relative(data_file)
        scan.save()
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return scan


def load_stored_scan(scan: Scan):
    """Scan row -> `LoadedScan`, exactly what the loader returned at upload time."""
    from inference.loaders import LoadedScan

    path = media_path(scan.data_path)
    if path is None:
        raise FileNotFoundError("the stored pixel data of this scan is missing")
    with np.load(path, allow_pickle=False) as data:
        stack = data["slices"]
    return LoadedScan([np.ascontiguousarray(s, dtype=np.float32) for s in stack], dict(scan.meta))


# --------------------------------------------------------------------------- #
# Prediction
# --------------------------------------------------------------------------- #
def create_prediction(scan: Scan, model_key: str) -> Prediction:
    return Prediction.objects.create(scan=scan, session_key=scan.session_key, model_key=model_key)


def run_prediction(prediction_id) -> Prediction:
    """
    Do the whole job for one Prediction row: load the stored scan, run the
    `inference` pipeline, write original / mask / overlay PNGs under random
    names and record summary, fold, run time and status.

    Takes only an id and never raises for a failed run (the row gets status
    "failed" and an error message), so it can move to a background worker
    later without changes.
    """
    from inference import pipeline
    from inference.postprocess import mask_to_png_array

    prediction = Prediction.objects.select_related("scan").get(pk=prediction_id)
    prediction.status = Prediction.RUNNING
    prediction.error_message = ""
    prediction.save(update_fields=["status", "error_message"])

    written: List[Path] = []
    try:
        scan = prediction.scan
        loaded = load_stored_scan(scan)
        result = pipeline.run_scan(loaded, prediction.model_key, registry=get_registry())
        chosen = result.slices[result.default_slice_index()]

        folder = scan_media_dir(scan.id)
        folder.mkdir(parents=True, exist_ok=True)
        files = {
            "original_path": chosen.image_u8,
            "mask_path": mask_to_png_array(chosen.mask),
            "overlay_path": chosen.overlay,
        }
        for field, array in files.items():
            path = folder / random_name("png")
            pipeline.write_png(path, array)
            written.append(path)
            setattr(prediction, field, _relative(path))

        prediction.fold = result.fold
        prediction.summary = chosen.summary
        prediction.run_seconds = result.run_seconds
        prediction.status = Prediction.DONE
    except Exception as exc:  # noqa: BLE001 - recorded on the row, shown on the result page
        for path in written:
            path.unlink(missing_ok=True)
        prediction.original_path = prediction.mask_path = prediction.overlay_path = ""
        prediction.summary = {}
        prediction.status = Prediction.FAILED
        prediction.error_message = f"{type(exc).__name__}: {exc}"[:1000]
    prediction.save()
    return prediction


def build_zip(prediction: Prediction) -> bytes:
    """original.png, mask.png, overlay.png, summary.json and a README in one zip."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for field, name in RESULT_FILES.values():
            path = media_path(getattr(prediction, field))
            if path is not None:
                archive.write(path, arcname=name)
        archive.writestr("summary.json", json.dumps(prediction.summary, indent=2) + "\n")
        archive.writestr(
            "README.txt",
            f"{DISCLAIMER}\n\n"
            "original.png  the uploaded slice as the model saw it (8-bit)\n"
            "mask.png      predicted tumor mask, white = tumor, same size as the slice\n"
            "overlay.png   the mask drawn in red on the slice\n"
            "summary.json  model, fold, threshold, tumor pixels and run time\n",
        )
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Deleting
# --------------------------------------------------------------------------- #
def delete_scan(scan: Scan) -> None:
    """Remove one scan: its predictions, its row and its folder."""
    folder = scan_media_dir(scan.id)
    scan.delete()                                   # cascades to predictions
    shutil.rmtree(folder, ignore_errors=True)


def delete_session_data(session_key: str) -> int:
    """Remove every scan, prediction and stored file of one visitor. Returns the scan count."""
    if not session_key:
        return 0
    scans = list(Scan.objects.filter(session_key=session_key))
    for scan in scans:
        delete_scan(scan)
    Prediction.objects.filter(session_key=session_key).delete()
    return len(scans)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def get_registry():
    """
    Model registry over settings.MODEL_STORE_DIR, one per path. Imported lazily:
    `inference` pulls in torch, which the home page does not need. An empty
    store is scanned again on every call, so checkpoints copied in while the
    server runs show up; after that a restart is needed to pick up changes.
    """
    path = str(settings.MODEL_STORE_DIR)
    if path not in _registries:
        from inference.registry import ModelRegistry

        _registries[path] = ModelRegistry(path)
    registry = _registries[path]
    if not registry.entries:
        registry.refresh()
    return registry


def list_served_models() -> Dict[str, Any]:
    """
    {"models": [public dicts], "error": str}. Never raises: pages must render
    even when a checkpoint folder is broken.
    """
    try:
        registry = get_registry()
        models: List[Dict[str, Any]] = [e.to_public_dict() for e in registry.list()]
        return {"models": models, "error": ""}
    except Exception as exc:  # noqa: BLE001 - shown on the page instead
        return {"models": [], "error": str(exc)}


def model_choices() -> List[Tuple[str, List[Tuple[str, str]]]]:
    """
    Grouped choices for the upload form: [(scan type heading, [(key, label), ...]), ...].
    T1 contrast-enhanced first, then FLAIR, then anything else.
    """
    groups: Dict[str, List[Tuple[str, str]]] = {}
    for model in list_served_models()["models"]:
        heading = SCAN_TYPE_GROUPS.get(model["scan_type"], f"{model['scan_type_label']} scans")
        groups.setdefault(heading, []).append((model["key"], model["display_label"]))
    order = list(SCAN_TYPE_GROUPS.values())
    headings = sorted(groups, key=lambda h: (order.index(h) if h in order else len(order), h))
    return [(h, groups[h]) for h in headings]

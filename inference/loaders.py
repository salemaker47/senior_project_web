"""
inference/loaders.py

Read an uploaded scan into a list of 2D float32 slices plus metadata.

The format is detected from the file CONTENT (magic bytes and, for HDF5, the
keys inside), never from the extension. Supported in Phase 1:

    png / jpeg / tiff   ordinary image files (8-bit or 16-bit, gray or colour)
    figshare_mat        FigShare brain-tumour .mat (MATLAB v7.3 = HDF5):
                        `cjdata/image`, transposed   (read_figshare_mat)
    brats_h5            BraTS 2020 slice .h5: key `image`, (H, W, 4),
                        FLAIR is channel 3           (read_brats2020_h5)
    dicom               one DICOM file; rescale slope/intercept applied,
                        MONOCHROME1 inverted; multi-frame gives several slices

Every loader returns `LoadedScan(slices=[(H, W) float32, ...], meta={...})`,
so 3D volumes (Phase 4) only add more slices.

`meta["intensity"]` tells preprocessing which path to take:
    "uint8"  the pixels are already 8-bit display values, exactly like the PNGs
             the models were trained on -> used as they are;
    "raw"    scanner / high-bit-depth intensities -> percentile clip to uint8,
             as `src/preprocess_utils.py` did when it built the training PNGs.

No patient-identifying fields are copied into the metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

import cv2
import h5py
import numpy as np

PathLike = Union[str, Path]

FORMAT_PNG = "png"
FORMAT_JPEG = "jpeg"
FORMAT_TIFF = "tiff"
FORMAT_FIGSHARE_MAT = "figshare_mat"
FORMAT_BRATS_H5 = "brats_h5"
FORMAT_DICOM = "dicom"

IMAGE_FORMATS = (FORMAT_PNG, FORMAT_JPEG, FORMAT_TIFF)
SUPPORTED_FORMATS = IMAGE_FORMATS + (FORMAT_FIGSHARE_MAT, FORMAT_BRATS_H5, FORMAT_DICOM)

INTENSITY_UINT8 = "uint8"
INTENSITY_RAW = "raw"

# Same mapping as BRATS_MODALITY_INDEX in the training repo: FLAIR is channel 3.
BRATS_FLAIR_CHANNEL = 3

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_TIFF_MAGICS = (b"II*\x00", b"MM\x00*")
_DICOM_MAGIC_OFFSET = 128
_DICOM_MAGIC = b"DICM"


class UnsupportedFormatError(ValueError):
    """The file is not one of the supported scan formats, or cannot be decoded."""


@dataclass
class LoadedScan:
    slices: List[np.ndarray]                       # each (H, W) float32
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_slices(self) -> int:
        return len(self.slices)


# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #
def detect_format(path: PathLike) -> str:
    """Return one of SUPPORTED_FORMATS, judged by content. Raises UnsupportedFormatError."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    with open(path, "rb") as f:
        head = f.read(_DICOM_MAGIC_OFFSET + len(_DICOM_MAGIC))

    if not head:
        raise UnsupportedFormatError("the file is empty")
    if head.startswith(_PNG_MAGIC):
        return FORMAT_PNG
    if head.startswith(_JPEG_MAGIC):
        return FORMAT_JPEG
    if head[:4] in _TIFF_MAGICS:
        return FORMAT_TIFF
    if head[_DICOM_MAGIC_OFFSET:_DICOM_MAGIC_OFFSET + 4] == _DICOM_MAGIC:
        return FORMAT_DICOM
    # h5py.is_hdf5 looks for the HDF5 signature at offsets 0, 512, 1024, ...
    # (MATLAB v7.3 files carry a 512-byte text header before it).
    if h5py.is_hdf5(str(path)):
        return _detect_hdf5_flavour(path)
    if _looks_like_headerless_dicom(path):
        return FORMAT_DICOM
    raise UnsupportedFormatError(
        "unrecognised file content. Supported: PNG, JPEG, TIFF, FigShare .mat, "
        "BraTS .h5 and DICOM."
    )


def _detect_hdf5_flavour(path: Path) -> str:
    with h5py.File(path, "r") as f:
        if "cjdata" in f and "image" in f["cjdata"]:
            return FORMAT_FIGSHARE_MAT
        if "image" in f and isinstance(f["image"], h5py.Dataset) and f["image"].ndim == 3:
            return FORMAT_BRATS_H5
        keys = list(f.keys())
    raise UnsupportedFormatError(
        f"HDF5 file is neither a FigShare .mat (cjdata/image) nor a BraTS .h5 "
        f"(image with 3 dimensions); top-level keys: {keys[:8]}"
    )


def _looks_like_headerless_dicom(path: Path) -> bool:
    """Old DICOM files lack the 128-byte preamble; accept them if pixel data parses."""
    import pydicom
    from pydicom.errors import InvalidDicomError

    try:
        ds = pydicom.dcmread(str(path), force=True, stop_before_pixels=True)
    except (InvalidDicomError, OSError, ValueError, AttributeError, KeyError):
        return False
    return all(tag in ds for tag in ("Rows", "Columns", "BitsAllocated"))


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def load_scan(path: PathLike) -> LoadedScan:
    """Detect the format and read the file."""
    path = Path(path)
    fmt = detect_format(path)
    if fmt in IMAGE_FORMATS:
        return load_image_file(path, fmt)
    if fmt == FORMAT_FIGSHARE_MAT:
        return load_figshare_mat(path)
    if fmt == FORMAT_BRATS_H5:
        return load_brats_h5(path)
    if fmt == FORMAT_DICOM:
        return load_dicom(path)
    raise UnsupportedFormatError(f"no loader for format {fmt!r}")  # pragma: no cover


def _meta(fmt: str, arr: np.ndarray, intensity: str, **extra: Any) -> Dict[str, Any]:
    meta = {
        "format":       fmt,
        "intensity":    intensity,
        "height":       int(arr.shape[0]),
        "width":        int(arr.shape[1]),
        "n_slices":     1,
        "source_dtype": str(arr.dtype),
    }
    meta.update(extra)
    return meta


def _to_gray(arr: np.ndarray) -> np.ndarray:
    """Colour -> gray with OpenCV's weights (what cv2.IMREAD_GRAYSCALE uses)."""
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[2] == 1:
        return arr[..., 0]
    if arr.ndim == 3 and arr.shape[2] == 3:
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY)
    raise UnsupportedFormatError(f"unsupported image shape {arr.shape}")


def load_image_file(path: PathLike, fmt: str = "") -> LoadedScan:
    """PNG / JPEG / TIFF. 8-bit images keep their values; deeper ones are 'raw'."""
    path = Path(path)
    fmt = fmt or detect_format(path)
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    arr = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise UnsupportedFormatError(f"could not decode the {fmt.upper()} image")
    source_dtype = arr.dtype
    channels = 1 if arr.ndim == 2 else int(arr.shape[2])
    if arr.dtype not in (np.uint8, np.uint16, np.float32):
        arr = arr.astype(np.float32)
    gray = _to_gray(arr)
    intensity = INTENSITY_UINT8 if source_dtype == np.uint8 else INTENSITY_RAW
    sl = np.ascontiguousarray(gray, dtype=np.float32)
    meta = _meta(fmt, sl, intensity, channels=channels)
    meta["source_dtype"] = str(source_dtype)
    return LoadedScan([sl], meta)


def load_figshare_mat(path: PathLike) -> LoadedScan:
    """FigShare .mat (HDF5): `cjdata/image`, transposed, as in read_figshare_mat."""
    with h5py.File(Path(path), "r") as f:
        image = np.array(f["cjdata"]["image"]).T
    if image.ndim != 2:
        raise UnsupportedFormatError(f"cjdata/image has shape {image.shape}, expected 2D")
    source_dtype = image.dtype
    sl = np.ascontiguousarray(image, dtype=np.float32)
    meta = _meta(FORMAT_FIGSHARE_MAT, sl, INTENSITY_RAW, scan_type="T1ce")
    meta["source_dtype"] = str(source_dtype)
    return LoadedScan([sl], meta)


def load_brats_h5(path: PathLike) -> LoadedScan:
    """BraTS 2020 slice .h5: key `image`, (H, W, 4); FLAIR = channel 3."""
    with h5py.File(Path(path), "r") as f:
        image = np.array(f["image"])
    # Same channel-first fallback as read_brats2020_h5 in the training repo.
    if image.ndim == 3 and image.shape[0] in (3, 4) and image.shape[-1] not in (3, 4):
        image = np.transpose(image, (1, 2, 0))
    if image.ndim != 3 or image.shape[-1] <= BRATS_FLAIR_CHANNEL:
        raise UnsupportedFormatError(
            f"BraTS image has shape {image.shape}, expected (H, W, 4) with FLAIR in channel 3"
        )
    source_dtype = image.dtype
    image = image.astype(np.float32)
    sl = np.ascontiguousarray(image[..., BRATS_FLAIR_CHANNEL])
    meta = _meta(FORMAT_BRATS_H5, sl, INTENSITY_RAW,
                 scan_type="FLAIR", channel=BRATS_FLAIR_CHANNEL)
    meta["source_dtype"] = str(source_dtype)
    return LoadedScan([sl], meta)


def load_dicom(path: PathLike) -> LoadedScan:
    """
    One DICOM file. Stored values are mapped with RescaleSlope / RescaleIntercept
    and MONOCHROME1 (white = low) is inverted so that bright always means high.
    A multi-frame file yields one slice per frame.
    """
    import pydicom

    try:
        ds = pydicom.dcmread(str(Path(path)), force=True)
        if "TransferSyntaxUID" not in getattr(ds, "file_meta", {}):
            # Header-less files: assume the DICOM default transfer syntax.
            ds.file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
        pixels = ds.pixel_array
    except Exception as exc:  # noqa: BLE001 - pydicom raises many types
        raise UnsupportedFormatError(f"could not read DICOM pixel data: {exc}") from exc

    source_dtype = pixels.dtype
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    photometric = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).strip().upper()
    arr = pixels.astype(np.float32)

    if samples > 1:
        # Colour DICOM (secondary capture): (..., H, W, 3) RGB -> luminance.
        if arr.shape[-1] != 3:
            raise UnsupportedFormatError(f"unsupported colour DICOM shape {arr.shape}")
        arr = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)

    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    arr = arr * slope + intercept

    inverted = photometric == "MONOCHROME1"
    if inverted:
        arr = (arr.max() + arr.min()) - arr

    if arr.ndim == 2:
        frames = [arr]
    elif arr.ndim == 3:
        frames = [arr[i] for i in range(arr.shape[0])]
    else:
        raise UnsupportedFormatError(f"unsupported DICOM pixel array shape {arr.shape}")

    slices = [np.ascontiguousarray(fr, dtype=np.float32) for fr in frames]
    meta = _meta(
        FORMAT_DICOM, slices[0], INTENSITY_RAW,
        photometric_interpretation=photometric,
        inverted=inverted,
        rescale_slope=slope,
        rescale_intercept=intercept,
        modality=str(getattr(ds, "Modality", "")),
    )
    meta["n_slices"] = len(slices)
    meta["source_dtype"] = str(source_dtype)
    return LoadedScan(slices, meta)

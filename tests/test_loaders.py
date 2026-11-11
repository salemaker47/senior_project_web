"""One test per loader, on synthetic files. Formats are detected from content."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from inference import loaders
from inference.loaders import UnsupportedFormatError, detect_format, load_scan


def _check_scan(scan, fmt, shape, intensity, n_slices=1):
    assert scan.meta["format"] == fmt
    assert scan.meta["intensity"] == intensity
    assert scan.n_slices == n_slices == scan.meta["n_slices"]
    for sl in scan.slices:
        assert sl.dtype == np.float32
        assert sl.shape == shape
    assert (scan.meta["height"], scan.meta["width"]) == shape


def _encode(tmp_path, name, ext, array, params=None):
    ok, buf = cv2.imencode(ext, array, params or [])
    assert ok
    path = tmp_path / name
    path.write_bytes(buf.tobytes())
    return path


def test_png_8bit_keeps_values_and_ignores_extension(png_file):
    path, u8 = png_file
    assert path.suffix == ".dat"
    assert detect_format(path) == loaders.FORMAT_PNG
    scan = load_scan(path)
    _check_scan(scan, "png", u8.shape, "uint8")
    np.testing.assert_array_equal(scan.slices[0], u8.astype(np.float32))


def test_png_16bit_is_raw(tmp_path, raw_slice):
    u16 = raw_slice.astype(np.uint16)
    path = _encode(tmp_path, "deep.png", ".png", u16)
    scan = load_scan(path)
    _check_scan(scan, "png", u16.shape, "raw")
    np.testing.assert_array_equal(scan.slices[0], u16.astype(np.float32))


def test_png_colour_is_converted_to_gray(tmp_path):
    bgr = np.zeros((40, 60, 3), dtype=np.uint8)
    bgr[..., 2] = 200                                   # pure red in BGR
    path = _encode(tmp_path, "colour.png", ".png", bgr)
    scan = load_scan(path)
    _check_scan(scan, "png", (40, 60), "uint8")
    assert scan.meta["channels"] == 3
    expected = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    np.testing.assert_array_equal(scan.slices[0], expected)


def test_jpeg(tmp_path, raw_slice):
    u8 = (raw_slice / raw_slice.max() * 255).astype(np.uint8)
    path = _encode(tmp_path, "scan.upload", ".jpg", u8, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert detect_format(path) == loaders.FORMAT_JPEG
    scan = load_scan(path)
    _check_scan(scan, "jpeg", u8.shape, "uint8")
    assert np.abs(scan.slices[0] - u8).mean() < 3.0     # lossy, but close


def test_tiff_16bit(tmp_path, raw_slice):
    u16 = raw_slice.astype(np.uint16)
    path = _encode(tmp_path, "scan.upload", ".tiff", u16)
    assert detect_format(path) == loaders.FORMAT_TIFF
    scan = load_scan(path)
    _check_scan(scan, "tiff", u16.shape, "raw")
    np.testing.assert_array_equal(scan.slices[0], u16.astype(np.float32))


def test_figshare_mat_is_transposed(figshare_mat_file):
    path, expected = figshare_mat_file
    assert detect_format(path) == loaders.FORMAT_FIGSHARE_MAT
    scan = load_scan(path)
    _check_scan(scan, "figshare_mat", expected.shape, "raw")
    np.testing.assert_array_equal(scan.slices[0], expected)
    assert scan.meta["scan_type"] == "T1ce"
    assert "PID" not in scan.meta and "patient_id" not in scan.meta


def test_brats_h5_uses_flair_channel_3(brats_h5_file):
    path, expected = brats_h5_file
    assert detect_format(path) == loaders.FORMAT_BRATS_H5
    scan = load_scan(path)
    _check_scan(scan, "brats_h5", expected.shape, "raw")
    np.testing.assert_allclose(scan.slices[0], expected, rtol=1e-6)
    assert scan.meta["channel"] == 3 and scan.meta["scan_type"] == "FLAIR"


def _write_dicom(path, stored, *, photometric="MONOCHROME2", slope=None, intercept=None,
                 frames=None):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"       # MR Image Storage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = "MR"
    ds.PatientName = "Test^Patient"
    ds.Rows, ds.Columns = stored.shape[-2], stored.shape[-1]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation = 0
    if frames:
        ds.NumberOfFrames = frames
    if slope is not None:
        ds.RescaleSlope = slope
    if intercept is not None:
        ds.RescaleIntercept = intercept
    ds.PixelData = stored.astype("<u2").tobytes()
    ds.save_as(str(path), write_like_original=False)
    return pydicom


def test_dicom_rescale_slope_and_intercept(tmp_path, raw_slice):
    stored = raw_slice.astype(np.uint16)
    path = tmp_path / "slice.upload"
    _write_dicom(path, stored, slope=2, intercept=-100)
    assert detect_format(path) == loaders.FORMAT_DICOM
    scan = load_scan(path)
    _check_scan(scan, "dicom", stored.shape, "raw")
    np.testing.assert_allclose(scan.slices[0], stored.astype(np.float32) * 2 - 100)
    assert scan.meta["inverted"] is False
    assert scan.meta["rescale_slope"] == 2.0 and scan.meta["rescale_intercept"] == -100.0
    assert "PatientName" not in scan.meta and "Test^Patient" not in str(scan.meta)


def test_dicom_monochrome1_is_inverted(tmp_path, raw_slice):
    stored = raw_slice.astype(np.uint16)
    path = tmp_path / "inverted.upload"
    _write_dicom(path, stored, photometric="MONOCHROME1")
    scan = load_scan(path)
    values = stored.astype(np.float32)
    np.testing.assert_allclose(scan.slices[0], values.max() + values.min() - values)
    assert scan.meta["inverted"] is True
    # The brightest stored pixel is now the darkest.
    assert scan.slices[0].flat[values.argmax()] == scan.slices[0].min()


def test_dicom_multiframe_gives_several_slices(tmp_path, raw_slice):
    stored = np.stack([raw_slice, raw_slice * 0.5, raw_slice * 0.25]).astype(np.uint16)
    path = tmp_path / "multi.upload"
    _write_dicom(path, stored, frames=3)
    scan = load_scan(path)
    _check_scan(scan, "dicom", raw_slice.shape, "raw", n_slices=3)
    np.testing.assert_array_equal(scan.slices[1], stored[1].astype(np.float32))


def test_unknown_content_is_rejected(tmp_path):
    path = tmp_path / "scan.png"                        # extension lies
    path.write_bytes(b"this is not an image at all" * 20)
    with pytest.raises(UnsupportedFormatError):
        load_scan(path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    with pytest.raises(UnsupportedFormatError):
        load_scan(path)


def test_other_hdf5_is_rejected(tmp_path):
    import h5py

    path = tmp_path / "other.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("something", data=np.zeros((4, 4)))
    with pytest.raises(UnsupportedFormatError):
        load_scan(path)

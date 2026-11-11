"""
Phase 3: upload, prediction, result page, owner-only files, my scans.

Runs against the fake checkpoint (random weights, real dict layout).
"""

from __future__ import annotations

import io
import json
import re
import zipfile

import cv2
import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from inference import DISCLAIMER
from scans import services
from scans.models import Prediction, Scan
from tests.conftest import FAKE_KEY, synthetic_slice
from tests.test_loaders import _write_dicom

pytestmark = pytest.mark.django_db

HOME = reverse("scans:home")
UPLOAD = reverse("scans:upload")
ACCEPT = reverse("scans:consent_accept")
MY_SCANS = reverse("scans:my_scans")
DELETE_ALL = reverse("scans:delete_my_data")

RANDOM_NAME_RE = re.compile(r"^scans/[0-9a-f-]{36}/[0-9a-f]{32}\.(npz|png)$")


@pytest.fixture(autouse=True)
def _store_and_media(settings, tmp_path, fake_store):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = fake_store


@pytest.fixture
def visitor(client):
    client.post(ACCEPT, {"next": HOME})
    return client


def _png_bytes(height=96, width=128, seed=0) -> bytes:
    raw = synthetic_slice(height, width, seed)
    u8 = (raw / raw.max() * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", u8)
    assert ok
    return buf.tobytes()


def _upload(client, content: bytes, name="brain scan.png", model=FAKE_KEY):
    return client.post(UPLOAD, {
        "model_key": model,
        "file": SimpleUploadedFile(name, content, content_type="application/octet-stream"),
    })


def _upload_ok(client, **kwargs) -> Scan:
    response = _upload(client, kwargs.pop("content", _png_bytes()), **kwargs)
    assert response.status_code == 302, response.content.decode()[:2000]
    scan = Scan.objects.latest("created_at")
    assert response["Location"] == reverse("scans:result", args=[scan.id])
    return scan


def _url(scan, name, *args):
    return reverse(f"scans:{name}", args=[scan.id, *args])


def _stored_files(settings):
    root = settings.MEDIA_ROOT
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def _text(response) -> str:
    return response.content.decode()


# --------------------------------------------------------------------------- #
# Upload form
# --------------------------------------------------------------------------- #
def test_upload_page_offers_models_grouped_by_scan_type(visitor):
    html = _text(visitor.get(UPLOAD))
    assert "<legend>T1 contrast-enhanced scans</legend>" in html
    assert f'name="model_key" value="{FAKE_KEY}" checked' in html     # only model: preselected
    assert "U-Net (ResNet34)" in html
    assert 'type="file"' in html and 'enctype="multipart/form-data"' in html
    assert "20 MB" in html


def test_model_choices_put_t1_before_flair(monkeypatch):
    models = [
        {"key": "b", "display_label": "B", "scan_type": "FLAIR", "scan_type_label": "x"},
        {"key": "a", "display_label": "A", "scan_type": "T1ce", "scan_type_label": "y"},
        {"key": "c", "display_label": "C", "scan_type": "FLAIR", "scan_type_label": "x"},
    ]
    monkeypatch.setattr(services, "list_served_models", lambda: {"models": models, "error": ""})
    assert services.model_choices() == [
        ("T1 contrast-enhanced scans", [("a", "A")]),
        ("FLAIR scans (skull-stripped)", [("b", "B"), ("c", "C")]),
    ]


def test_upload_page_without_models(visitor, settings, tmp_path):
    settings.MODEL_STORE_DIR = tmp_path / "empty_store"
    html = _text(visitor.get(UPLOAD))
    assert "No trained models are installed yet" in html
    assert 'type="file"' not in html


# --------------------------------------------------------------------------- #
# Upload with consent works
# --------------------------------------------------------------------------- #
def test_upload_with_consent_runs_the_fake_checkpoint(visitor, settings):
    scan = _upload_ok(visitor)
    session_key = visitor.session.session_key

    assert scan.session_key == session_key
    assert scan.original_name == "brain scan.png"
    assert scan.detected_format == "png"
    assert (scan.width, scan.height, scan.n_slices) == (128, 96, 1)
    assert scan.meta["intensity"] == "uint8"

    prediction = Prediction.objects.get(scan=scan)
    assert prediction.session_key == session_key
    assert prediction.status == Prediction.DONE and prediction.error_message == ""
    assert prediction.model_key == FAKE_KEY and prediction.fold == 2
    assert prediction.run_seconds > 0
    summary = prediction.summary
    assert summary["model_key"] == FAKE_KEY and summary["fold"] == 2
    assert summary["threshold"] == 0.5
    assert (summary["mask_width"], summary["mask_height"]) == (128, 96)
    assert summary["disclaimer"] == DISCLAIMER

    # Files: random names, inside the scan's folder, nothing else on disk.
    paths = [scan.data_path, prediction.original_path, prediction.mask_path, prediction.overlay_path]
    assert len(set(paths)) == 4
    for path in paths:
        assert RANDOM_NAME_RE.match(path), path
        assert "brain" not in path
        assert services.media_path(path) is not None
    assert len(_stored_files(settings)) == 4

    mask = cv2.imread(str(services.media_path(prediction.mask_path)), cv2.IMREAD_UNCHANGED)
    assert mask.shape == (96, 128) and set(np.unique(mask)) <= {0, 255}
    assert int((mask > 0).sum()) == summary["tumor_pixels"]


def test_result_page_shows_images_slider_summary_and_downloads(visitor):
    scan = _upload_ok(visitor)
    response = visitor.get(_url(scan, "result"))
    assert response.status_code == 200
    html = _text(response)
    assert DISCLAIMER in html
    assert "brain scan.png" in html
    for kind in ("original", "mask", "overlay"):
        assert f'src="{_url(scan, "scan_file", kind)}"' in html
    assert 'type="range"' in html and "Overlay opacity" in html
    assert "Tumor pixels" in html and "Share of the image" in html and "Run time" in html
    assert FAKE_KEY in html and "U-Net (ResNet34)" in html
    assert f'href="{_url(scan, "scan_file", "mask")}?download=1"' in html
    assert f'href="{_url(scan, "scan_file", "overlay")}?download=1"' in html
    assert f'href="{_url(scan, "scan_zip")}"' in html
    assert "scans/js/result.js" in html


def test_owner_can_view_and_download_files(visitor):
    scan = _upload_ok(visitor)
    prediction = scan.latest_prediction

    for kind in ("original", "mask", "overlay"):
        response = visitor.get(_url(scan, "scan_file", kind))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["Cache-Control"] == "private, no-store"
        assert "attachment" not in response.get("Content-Disposition", "")
        body = b"".join(response.streaming_content)
        assert body.startswith(b"\x89PNG")

    download = visitor.get(_url(scan, "scan_file", "mask") + "?download=1")
    assert download["Content-Disposition"] == 'attachment; filename="mask.png"'
    mask = cv2.imdecode(np.frombuffer(b"".join(download.streaming_content), np.uint8),
                        cv2.IMREAD_UNCHANGED)
    assert mask.shape == (96, 128)
    assert int((mask > 0).sum()) == prediction.summary["tumor_pixels"]

    assert visitor.get(_url(scan, "scan_file", "secrets")).status_code == 404


def test_zip_contains_everything(visitor):
    scan = _upload_ok(visitor)
    response = visitor.get(_url(scan, "scan_zip"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f'attachment; filename="scan_{str(scan.id)[:8]}.zip"'
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == [
        "README.txt", "mask.png", "original.png", "overlay.png", "summary.json",
    ]
    assert json.loads(archive.read("summary.json")) == scan.latest_prediction.summary
    assert DISCLAIMER in archive.read("README.txt").decode()
    assert archive.read("mask.png").startswith(b"\x89PNG")


def test_upload_of_figshare_mat(visitor, figshare_mat_file):
    path, expected = figshare_mat_file
    scan = _upload_ok(visitor, content=path.read_bytes(), name="1234.mat")
    assert scan.detected_format == "figshare_mat"
    assert scan.meta["intensity"] == "raw"
    assert (scan.height, scan.width) == expected.shape
    assert scan.latest_prediction.status == Prediction.DONE
    stored = services.load_stored_scan(scan)
    np.testing.assert_array_equal(stored.slices[0], expected)


def test_dicom_patient_tags_are_not_stored(visitor, settings, tmp_path, raw_slice):
    path = tmp_path / "slice.dcm"
    _write_dicom(path, raw_slice.astype(np.uint16), slope=2, intercept=-100)
    raw = path.read_bytes()
    assert b"Test^Patient" in raw                              # the upload does carry a name

    scan = _upload_ok(visitor, content=raw, name="slice.dcm")
    prediction = scan.latest_prediction
    assert scan.detected_format == "dicom" and prediction.status == Prediction.DONE

    # Not in the database ...
    stored_text = json.dumps([scan.meta, prediction.summary, scan.original_name])
    assert "Test" not in stored_text and "PatientName" not in stored_text
    # ... and not on disk: the upload itself is not kept, only pixel data and PNGs.
    files = _stored_files(settings)
    assert len(files) == 4
    for file in files:
        assert b"Test^Patient" not in file.read_bytes()
        assert file.suffix in (".npz", ".png")


# --------------------------------------------------------------------------- #
# Another session cannot open the result or the files
# --------------------------------------------------------------------------- #
def test_another_session_gets_404_everywhere(visitor):
    scan = _upload_ok(visitor)

    other = Client()
    other.post(ACCEPT, {"next": HOME})
    assert other.session.session_key != visitor.session.session_key

    assert other.get(_url(scan, "result")).status_code == 404
    for kind in ("original", "mask", "overlay"):
        assert other.get(_url(scan, "scan_file", kind)).status_code == 404
        assert other.get(_url(scan, "scan_file", kind) + "?download=1").status_code == 404
    assert other.get(_url(scan, "scan_zip")).status_code == 404
    assert other.post(_url(scan, "delete_scan")).status_code == 404
    assert str(scan.id) not in _text(other.get(MY_SCANS))

    # Still there for its owner.
    assert Scan.objects.filter(pk=scan.pk).exists()
    assert visitor.get(_url(scan, "scan_file", "mask")).status_code == 200


def test_visitor_without_consent_cannot_open_result_or_files(visitor):
    scan = _upload_ok(visitor)
    stranger = Client()
    assert stranger.get(_url(scan, "result")).status_code == 403          # consent page
    for kind in ("original", "mask", "overlay"):
        response = stranger.get(_url(scan, "scan_file", kind))
        assert response.status_code == 404
        assert response.wsgi_request.session.accessed is False
    assert stranger.get(_url(scan, "scan_zip")).status_code == 404
    assert stranger.post(_url(scan, "delete_scan")).status_code == 404
    assert stranger.get(MY_SCANS).status_code == 403
    assert not stranger.cookies


def test_upload_without_consent_stores_nothing(client, settings):
    response = _upload(client, _png_bytes())
    assert response.status_code == 403
    assert not Scan.objects.exists() and not _stored_files(settings)
    assert not client.cookies


# --------------------------------------------------------------------------- #
# Invalid and oversized files are rejected
# --------------------------------------------------------------------------- #
def _assert_rejected(response, settings, message):
    assert response.status_code == 400
    html = _text(response)
    assert message in html, html[:3000]
    assert 'class="field__error"' in html
    assert not Scan.objects.exists() and not Prediction.objects.exists()
    assert not _stored_files(settings)


def test_invalid_file_is_rejected(visitor, settings):
    response = _upload(visitor, b"this is definitely not a scan " * 100, name="scan.png")
    _assert_rejected(response, settings, "This file is not a scan the site can read")
    assert "Supported: PNG, JPEG, TIFF" in _text(response)


def test_truncated_image_is_rejected(visitor, settings):
    response = _upload(visitor, _png_bytes()[:200], name="broken.png")
    _assert_rejected(response, settings, "could not be read")


def test_empty_file_is_rejected(visitor, settings):
    _assert_rejected(_upload(visitor, b"", name="empty.png"), settings, "The file is empty")


def test_missing_file_and_unknown_model_are_rejected(visitor, settings):
    response = visitor.post(UPLOAD, {"model_key": FAKE_KEY})
    _assert_rejected(response, settings, "Choose a scan file to upload")
    response = _upload(visitor, _png_bytes(), model="not_a_model")
    _assert_rejected(response, settings, "That model is not available")


def test_oversized_file_is_rejected(visitor, settings):
    settings.SCAN_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
    big = _png_bytes() + b"\x00" * (3 * 1024 * 1024)
    response = _upload(visitor, big, name="big.png")
    _assert_rejected(response, settings, "The file is larger than 2 MB")
    # The upload handler stopped the stream; the file never reached the form.
    assert response.wsgi_request.scan_upload_too_large is True
    assert "file" not in response.wsgi_request.FILES


def test_size_is_also_checked_without_the_upload_handler(settings):
    settings.SCAN_MAX_UPLOAD_BYTES = 1000
    with pytest.raises(services.UploadRejected, match="larger than"):
        services.parse_upload(SimpleUploadedFile("big.png", b"x" * 1001))


def test_image_with_too_many_pixels_is_rejected(visitor, settings):
    settings.SCAN_MAX_PIXELS = 64 * 64
    _assert_rejected(_upload(visitor, _png_bytes()), settings, "too large to process")


def test_default_limit_is_20_mb(visitor):
    assert services.max_upload_mb() == 20
    assert "larger than 20 MB" in services.too_large_message()


# --------------------------------------------------------------------------- #
# run_prediction
# --------------------------------------------------------------------------- #
def test_run_prediction_records_a_failure_instead_of_raising(visitor, settings):
    scan = _upload_ok(visitor)
    before = len(_stored_files(settings))
    prediction = services.create_prediction(scan, "model_that_is_gone")

    finished = services.run_prediction(prediction.id)
    assert finished.status == Prediction.FAILED
    assert "model_that_is_gone" in finished.error_message
    assert finished.mask_path == "" and finished.summary == {}
    assert len(_stored_files(settings)) == before

    html = _text(visitor.get(_url(scan, "result")))                 # latest prediction is the failed one
    assert "The prediction failed" in html and DISCLAIMER in html
    assert visitor.get(_url(scan, "scan_file", "mask")).status_code == 404


def test_run_prediction_can_be_repeated(visitor):
    scan = _upload_ok(visitor)
    first = scan.latest_prediction
    again = services.run_prediction(first.id)
    assert again.status == Prediction.DONE
    assert again.summary["tumor_pixels"] == first.summary["tumor_pixels"]


# --------------------------------------------------------------------------- #
# My scans
# --------------------------------------------------------------------------- #
def test_my_scans_lists_only_this_browsers_scans(visitor):
    mine_a = _upload_ok(visitor, name="first.png")
    mine_b = _upload_ok(visitor, name="second.png")
    other = Client()
    other.post(ACCEPT, {"next": HOME})
    theirs = _upload_ok(other, name="theirs.png")

    html = _text(visitor.get(MY_SCANS))
    assert "first.png" in html and "second.png" in html and "theirs.png" not in html
    for scan in (mine_a, mine_b):
        assert f'href="{_url(scan, "result")}"' in html
        assert f'action="{_url(scan, "delete_scan")}"' in html
    assert str(theirs.id) not in html
    assert html.index("second.png") < html.index("first.png")          # newest first

    fresh = Client()
    fresh.post(ACCEPT, {"next": HOME})
    assert "No scans yet" in _text(fresh.get(MY_SCANS))


def test_delete_one_scan(visitor, settings):
    keep = _upload_ok(visitor, name="keep.png")
    gone = _upload_ok(visitor, name="gone.png")
    gone_dir = services.scan_media_dir(gone.id)
    assert gone_dir.is_dir()

    assert visitor.get(_url(gone, "delete_scan")).status_code == 405
    response = visitor.post(_url(gone, "delete_scan"))
    assert response.status_code == 302 and response["Location"] == f"{MY_SCANS}?deleted=1"

    assert not Scan.objects.filter(pk=gone.pk).exists()
    assert not Prediction.objects.filter(scan_id=gone.pk).exists()
    assert not gone_dir.exists()
    assert Scan.objects.filter(pk=keep.pk).exists()
    assert len(_stored_files(settings)) == 4
    assert visitor.get(_url(gone, "result")).status_code == 404
    html = _text(visitor.get(response["Location"]))
    assert "were deleted" in html and "keep.png" in html and "gone.png" not in html


def test_delete_scan_needs_a_csrf_token():
    client = Client(enforce_csrf_checks=True)
    client.post(ACCEPT, {"next": HOME})
    scan = Scan.objects.create(session_key=client.session.session_key, original_name="x.png")
    assert client.post(_url(scan, "delete_scan")).status_code == 403
    assert Scan.objects.filter(pk=scan.pk).exists()


def test_delete_my_data_removes_uploads(visitor, settings):
    _upload_ok(visitor, name="a.png")
    _upload_ok(visitor, name="b.png")
    other = Client()
    other.post(ACCEPT, {"next": HOME})
    theirs = _upload_ok(other, name="theirs.png")

    assert visitor.post(DELETE_ALL).status_code == 302
    assert list(Scan.objects.values_list("pk", flat=True)) == [theirs.pk]
    assert Prediction.objects.count() == 1
    assert len(_stored_files(settings)) == 4
    assert other.get(_url(theirs, "scan_file", "mask")).status_code == 200


def test_display_name_is_cleaned():
    assert services.clean_display_name("C:\\Users\\me\\scan 1.png") == "scan 1.png"
    assert services.clean_display_name("../../etc/passwd") == "passwd"
    assert services.clean_display_name("a\x00b\n.png") == "ab.png"
    assert services.clean_display_name("") == "scan"
    assert len(services.clean_display_name("x" * 500)) == 120

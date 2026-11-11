"""
Phase 5: .env handling, friendly errors, static files with DEBUG off, purge command.
"""

from __future__ import annotations

import io
import os
import time
import uuid
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config import env as env_module
from config import make_env
from inference import DISCLAIMER
from inference.registry import RegistryError
from scans import errors, services
from scans.models import Prediction, Scan

HOME = reverse("scans:home")
ACCEPT = reverse("scans:consent_accept")
UPLOAD = reverse("scans:upload")


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #
def test_parse_env_text():
    text = """
    # a comment
    DJANGO_SECRET_KEY=abc=def
    DJANGO_DEBUG = False
    QUOTED="with spaces"
    SINGLE='x'
    export EXPORTED=1
    EMPTY=
    not a setting line
    """
    assert env_module.parse_env_text(text) == {
        "DJANGO_SECRET_KEY": "abc=def", "DJANGO_DEBUG": "False", "QUOTED": "with spaces",
        "SINGLE": "x", "EXPORTED": "1", "EMPTY": "",
    }


def test_load_env_file_does_not_override_real_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PHASE5_A=from_file\nPHASE5_B=from_file\n")
    monkeypatch.setenv("PHASE5_A", "from_environment")
    monkeypatch.delenv("PHASE5_B", raising=False)
    try:
        assert env_module.load_env_file(env_file) == {"PHASE5_A": "from_file", "PHASE5_B": "from_file"}
        assert os.environ["PHASE5_A"] == "from_environment"
        assert os.environ["PHASE5_B"] == "from_file"
    finally:
        os.environ.pop("PHASE5_B", None)
    assert env_module.load_env_file(tmp_path / "missing.env") == {}


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("PHASE5_FLAG", "true")
    assert env_module.env_bool("PHASE5_FLAG", False) is True
    monkeypatch.setenv("PHASE5_FLAG", "0")
    assert env_module.env_bool("PHASE5_FLAG", True) is False
    monkeypatch.setenv("PHASE5_FLAG", "")
    assert env_module.env_bool("PHASE5_FLAG", True) is True
    monkeypatch.setenv("PHASE5_N", "42")
    assert env_module.env_int("PHASE5_N", 1) == 42
    monkeypatch.delenv("PHASE5_N")
    assert env_module.env_int("PHASE5_N", 1) == 1
    monkeypatch.setenv("PHASE5_L", "a, b ,,c")
    assert env_module.env_list("PHASE5_L", ["x"]) == ["a", "b", "c"]


def test_make_env_creates_env_once(tmp_path, capsys):
    (tmp_path / ".env.example").write_text("# header\nDJANGO_SECRET_KEY=\nDJANGO_DEBUG=False\n")
    assert make_env.main(tmp_path) == 0
    values = env_module.parse_env_text((tmp_path / ".env").read_text())
    assert len(values["DJANGO_SECRET_KEY"]) >= 50 and values["DJANGO_DEBUG"] == "False"

    first = (tmp_path / ".env").read_text()
    assert make_env.main(tmp_path) == 0                      # second run changes nothing
    assert (tmp_path / ".env").read_text() == first
    assert "already exists" in capsys.readouterr().out

    assert make_env.main(tmp_path / "nowhere") == 1


def test_env_example_is_committed_and_has_no_secret():
    from config.settings import BASE_DIR

    values = env_module.parse_env_text((BASE_DIR / ".env.example").read_text())
    assert values["DJANGO_SECRET_KEY"] == ""
    assert values["DJANGO_DEBUG"] == "False"
    ignored = (BASE_DIR / ".gitignore").read_text().split()
    assert ".env" in ignored and ".env.example" not in ignored


def test_debug_is_off_unless_asked_for(settings):
    from config import settings as project_settings

    assert env_module.env_bool("PHASE5_UNSET_DEBUG_FLAG", False) is False
    assert project_settings.SECRET_KEY and "insecure" not in project_settings.SECRET_KEY
    assert project_settings.CSRF_FAILURE_VIEW == "scans.errors.csrf_failure"


# --------------------------------------------------------------------------- #
# Static files with DEBUG off (pytest-django runs with DEBUG = False)
# --------------------------------------------------------------------------- #
def test_static_files_are_served_with_debug_off(client, settings):
    assert settings.DEBUG is False
    for path, kind in (("scans/css/site.css", "text/css"), ("scans/js/result.js", "javascript")):
        response = client.get(f"/static/{path}")
        assert response.status_code == 200
        assert kind in response["Content-Type"]
        assert not response.cookies
    assert client.get("/static/scans/css/missing.css").status_code == 404
    assert client.get("/static/../config/settings.py").status_code in (400, 404)     # refused


# --------------------------------------------------------------------------- #
# Friendly errors
# --------------------------------------------------------------------------- #
def test_friendly_prediction_error_messages():
    assert errors.friendly_prediction_error(RegistryError("unknown model key 'x' (/secret/path)")) == errors.MODEL_UNAVAILABLE
    assert errors.friendly_prediction_error(FileNotFoundError("/secret/path.npz")) == errors.SCAN_DATA_MISSING
    assert errors.friendly_prediction_error(MemoryError()) == errors.OUT_OF_MEMORY
    assert errors.friendly_prediction_error(RuntimeError("DefaultCPUAllocator: out of memory")) == errors.OUT_OF_MEMORY
    assert errors.friendly_prediction_error(ValueError("shape mismatch at layer 3")) == errors.PREDICTION_FAILED
    for message in (errors.MODEL_UNAVAILABLE, errors.SCAN_DATA_MISSING, errors.OUT_OF_MEMORY,
                    errors.PREDICTION_FAILED):
        assert "/" not in message and "Error" not in message and "Traceback" not in message


LEAKS = ("Traceback", "RegistryError", "FileNotFoundError", "Exception", "site-packages",
         "model_store", ".py", "/Users/", "/private/", "/tmp/")


def _assert_no_leak(html: str):
    for needle in LEAKS:
        assert needle not in html, f"{needle!r} leaked into the page"


@pytest.mark.django_db
def test_failed_prediction_page_shows_no_internal_detail(client, settings, tmp_path, caplog):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = tmp_path / "empty_store"
    client.post(ACCEPT, {"next": HOME})
    scan = Scan.objects.create(session_key=client.session.session_key, original_name="x.png")
    prediction = services.create_prediction(scan, "no_such_model")

    with caplog.at_level("ERROR", logger="scans"):
        services.run_prediction(prediction.id)
    prediction.refresh_from_db()
    assert prediction.status == Prediction.FAILED
    assert prediction.error_message == errors.SCAN_DATA_MISSING          # no stored pixel data
    # The technical detail is in the log, with the traceback, for whoever runs the server.
    assert any(r.exc_info for r in caplog.records) and str(prediction.id) in caplog.text

    for url in (reverse("scans:result", args=[scan.id]), reverse("scans:my_scans")):
        html = client.get(url).content.decode()
        _assert_no_leak(html)
        assert DISCLAIMER in html
    html = client.get(reverse("scans:result", args=[scan.id])).content.decode()
    assert "The prediction did not finish" in html
    assert errors.SCAN_DATA_MISSING in html
    assert "Upload the scan again" in html


@pytest.mark.django_db
def test_unreadable_upload_message_hides_library_errors(client, settings, tmp_path, fake_store, caplog):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from tests.conftest import FAKE_KEY

    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = fake_store
    client.post(ACCEPT, {"next": HOME})
    broken_png = b"\\x89PNG\\r\\n\\x1a\\n".decode("unicode_escape").encode("latin-1") + b"garbage" * 50
    with caplog.at_level("INFO", logger="scans"):
        response = client.post(UPLOAD, {
            "model_key": FAKE_KEY, "file": SimpleUploadedFile("broken.png", broken_png),
        })
    assert response.status_code == 400
    html = response.content.decode()
    assert "could not be read. It may be damaged or incomplete" in html
    _assert_no_leak(html)
    assert "upload rejected" in caplog.text


@pytest.mark.django_db
def test_error_pages_are_friendly(client):
    response = client.get("/definitely/not/here/")
    assert response.status_code == 404
    html = response.content.decode()
    assert "Page not found" in html and DISCLAIMER in html
    _assert_no_leak(html)

    response = client.get(reverse("scans:result", args=[uuid.uuid4()]))
    assert response.status_code == 403 and "needs the session cookie" in response.content.decode()


@pytest.mark.django_db
def test_csrf_failure_page_is_friendly():
    client = Client(enforce_csrf_checks=True)
    client.post(ACCEPT, {"next": HOME})
    response = client.post(reverse("scans:delete_my_data"))
    assert response.status_code == 403
    html = response.content.decode()
    assert "That form has expired" in html and "reload the page" in html
    assert "CSRF" not in html
    _assert_no_leak(html)


@pytest.mark.django_db
def test_unexpected_error_gives_the_plain_500_page(client, settings, monkeypatch):
    def boom():
        raise RuntimeError("secret internal detail /Users/someone/project")

    monkeypatch.setattr(services, "list_served_models", boom)
    client.raise_request_exception = False
    response = client.get(reverse("scans:about"))
    assert response.status_code == 500
    html = response.content.decode()
    assert "Something went wrong" in html and DISCLAIMER in html
    assert "secret internal detail" not in html
    _assert_no_leak(html)


def test_error_templates_do_not_show_exception_text(rf):
    for view, status in ((errors.bad_request, 400), (errors.permission_denied, 403),
                         (errors.not_found, 404)):
        response = view(rf.get("/x/"), exception=RuntimeError("internal /Users/secret"))
        assert response.status_code == status
        assert "internal" not in response.content.decode()


# --------------------------------------------------------------------------- #
# purge_old_scans
# --------------------------------------------------------------------------- #
def _scan(session_key, days_old=0, name="s.png"):
    scan = Scan.objects.create(session_key=session_key, original_name=name)
    if days_old:
        Scan.objects.filter(pk=scan.pk).update(created_at=timezone.now() - timedelta(days=days_old))
    folder = services.scan_media_dir(scan.id)
    folder.mkdir(parents=True)
    (folder / "data.npz").write_bytes(b"x")
    services.create_prediction(scan, "m")
    return scan


def _session(expired=False):
    from django.contrib.sessions.backends.db import SessionStore

    store = SessionStore()
    store["cookie_consent"] = True
    store.save()
    if expired:
        Session.objects.filter(pk=store.session_key).update(
            expire_date=timezone.now() - timedelta(days=1))
    return store.session_key


def _purge(*args):
    out = io.StringIO()
    call_command("purge_old_scans", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def purge_world(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    live, dead = _session(), _session(expired=True)
    world = {
        "fresh": _scan(live, 0, "fresh.png"),
        "week_old": _scan(live, 8, "old.png"),
        "three_days": _scan(live, 3, "three.png"),
        "expired_session": _scan(dead, 1, "expired.png"),
        "no_session": _scan("sessionthatneverexisted", 1, "orphan.png"),
        "live": live, "dead": dead,
    }
    root = settings.MEDIA_ROOT / "scans"
    stray = root / str(uuid.uuid4())
    stray.mkdir()
    (stray / "left.png").write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(stray, (two_hours_ago, two_hours_ago))
    recent = root / str(uuid.uuid4())                       # an upload in progress
    recent.mkdir()
    other = root / "not-a-scan-folder"
    other.mkdir()
    os.utime(other, (two_hours_ago, two_hours_ago))
    world.update(stray=stray, recent=recent, other=other)
    return world


@pytest.mark.django_db
def test_purge_old_scans_default_seven_days(purge_world):
    w = purge_world
    out = _purge()
    assert out.strip() == ("Deleted: 1 scan(s) older than 7 day(s), 2 scan(s) without a session, "
                           "1 stray folder(s), 1 expired session(s).")

    remaining = set(Scan.objects.values_list("original_name", flat=True))
    assert remaining == {"fresh.png", "three.png"}
    assert Prediction.objects.count() == 2
    for gone in ("week_old", "expired_session", "no_session"):
        assert not services.scan_media_dir(w[gone].id).exists()
    for kept in ("fresh", "three_days"):
        assert (services.scan_media_dir(w[kept].id) / "data.npz").is_file()

    assert not w["stray"].exists()
    assert w["recent"].is_dir() and w["other"].is_dir()
    assert list(Session.objects.values_list("session_key", flat=True)) == [w["live"]]

    assert _purge().startswith("Deleted: 0 scan(s)")          # second run finds nothing


@pytest.mark.django_db
def test_purge_old_scans_days_option_and_dry_run(purge_world):
    out = _purge("--days", "2", "--dry-run")
    assert out.strip() == ("Would delete: 2 scan(s) older than 2 day(s), 2 scan(s) without a session, "
                           "1 stray folder(s), 1 expired session(s).")
    assert Scan.objects.count() == 5 and Session.objects.count() == 2
    assert purge_world["stray"].exists()

    _purge("--days", "2")
    assert set(Scan.objects.values_list("original_name", flat=True)) == {"fresh.png"}

    _purge("--days", "0")
    assert Scan.objects.count() == 0
    with pytest.raises(CommandError):
        _purge("--days", "-1")


@pytest.mark.django_db
def test_purge_with_no_media_folder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "nothing_here"
    assert "0 stray folder(s)" in _purge()

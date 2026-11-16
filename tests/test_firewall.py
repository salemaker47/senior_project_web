"""
Request firewall, access code, content policy and format allow-list: the
layers that protect the site while it is reachable from the internet.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import cv2
import numpy as np
import pytest
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from scans import firewall
from scans.models import Scan
from tests.conftest import FAKE_KEY, synthetic_slice

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME = reverse("scans:home")
ABOUT = reverse("scans:about")
UPLOAD = reverse("scans:upload")
ACCEPT = reverse("scans:consent_accept")


@pytest.fixture(autouse=True)
def _clean_state():
    firewall.STATE.reset()
    yield
    firewall.STATE.reset()


@pytest.fixture
def fw(settings):
    """Firewall on, as in the public sharing mode."""
    settings.REQUEST_FIREWALL = True
    settings.BEHIND_PROXY = True
    settings.ACCESS_PASSWORD = ""
    return settings


def _from(ip):
    """A request that came through the tunnel on behalf of `ip`."""
    return {"REMOTE_ADDR": "127.0.0.1", "HTTP_CF_CONNECTING_IP": ip}


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"HTTP_AUTHORIZATION": f"Basic {token}"}


# --------------------------------------------------------------------------- #
# Off by default
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_firewall_is_off_by_default(client, settings):
    assert settings.REQUEST_FIREWALL is False and settings.ACCESS_PASSWORD == ""
    for _ in range(150):                                    # well past the per-minute limit
        assert client.get(HOME).status_code == 200
    assert client.get("/.env").status_code == 404           # the site's own 404 page
    assert "Page not found" in client.get("/.env").content.decode()


# --------------------------------------------------------------------------- #
# Probes, methods, malformed requests
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
@pytest.mark.parametrize("path", [
    "/.env", "/.git/config", "/wp-login.php", "/wp-admin/", "/phpmyadmin/", "/admin/",
    "/index.php", "/config.yml", "/backup.sql", "/cgi-bin/test", "/static/../config/settings.py",
    "/scans/..%2f..%2fetc/passwd", "/server-status.bak", "/.well-known/security.txt",
])
def test_scanner_paths_get_a_bare_404(fw, client, path):
    response = client.get(path, **_from("203.0.113.9"))
    assert response.status_code == 404
    assert response.content == b"Not found.\n"               # no template, no page chrome
    assert not response.cookies
    assert not hasattr(response.wsgi_request, "session")    # refused before the session layer
    assert Session.objects.count() == 0


@pytest.mark.django_db
def test_normal_pages_and_robots_are_not_probes(fw, client):
    for path in (HOME, ABOUT, "/robots.txt", "/static/scans/css/site.css", "/static/scans/js/frame.js"):
        assert client.get(path, **_from("203.0.113.9")).status_code == 200
    robots = client.get("/robots.txt", **_from("203.0.113.9")).content.decode()
    assert "Disallow: /" in robots


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "delete", "patch", "options", "trace"])
def test_other_methods_are_refused(fw, client, method):
    response = getattr(client, method)(HOME, **_from("203.0.113.9"))
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD, POST"


@pytest.mark.django_db
def test_overlong_requests_are_refused(fw, client):
    assert client.get("/" + "a" * 600, **_from("203.0.113.9")).status_code == 400
    assert client.get(HOME + "?q=" + "a" * 1100, **_from("203.0.113.9")).status_code == 400


# --------------------------------------------------------------------------- #
# Bans
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_repeated_probing_bans_that_address_only(fw, client):
    fw.FIREWALL_STRIKES_BEFORE_BAN = 4
    attacker, visitor = _from("203.0.113.66"), _from("198.51.100.7")
    for _ in range(4):
        assert client.get("/wp-login.php", **attacker).status_code == 404
    banned = client.get(HOME, **attacker)                    # even a good page now
    assert banned.status_code == 429 and int(banned["Retry-After"]) > 0
    assert client.get(HOME, **visitor).status_code == 200    # others are unaffected


@pytest.mark.django_db
def test_ban_expires(fw, client, monkeypatch):
    fw.FIREWALL_STRIKES_BEFORE_BAN = 2
    fw.FIREWALL_BAN_SECONDS = 600
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(firewall.time, "time", lambda: clock["now"])
    who = _from("203.0.113.66")
    for _ in range(2):
        client.get("/.env", **who)
    assert client.get(HOME, **who).status_code == 429
    clock["now"] += 601
    assert client.get(HOME, **who).status_code == 200


# --------------------------------------------------------------------------- #
# Rate limits
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_requests_per_minute_limit(fw, client, monkeypatch):
    fw.FIREWALL_REQUESTS_PER_MINUTE = 5
    fw.FIREWALL_STRIKES_BEFORE_BAN = 100
    clock = {"now": 2_000_000.0}
    monkeypatch.setattr(firewall.time, "time", lambda: clock["now"])
    who = _from("203.0.113.5")
    assert [client.get(HOME, **who).status_code for _ in range(5)] == [200] * 5
    limited = client.get(HOME, **who)
    assert limited.status_code == 429 and limited["Retry-After"] == "30"
    assert client.get(HOME, **_from("203.0.113.6")).status_code == 200      # another visitor
    clock["now"] += 61
    assert client.get(HOME, **who).status_code == 200                       # window has moved on


def _png() -> bytes:
    raw = synthetic_slice(64, 64)
    ok, buf = cv2.imencode(".png", (raw / raw.max() * 255).astype(np.uint8))
    return buf.tobytes()


@pytest.mark.django_db
def test_upload_limit_per_address(fw, settings, tmp_path, fake_store):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = fake_store
    fw.FIREWALL_UPLOADS_PER_MINUTE = 2
    who = _from("203.0.113.5")
    client = Client()
    client.post(ACCEPT, {"next": HOME}, **who)

    def upload():
        return client.post(UPLOAD, {"model_key": FAKE_KEY,
                                    "file": SimpleUploadedFile("s.png", _png())}, **who)

    assert upload().status_code == 302 and upload().status_code == 302
    third = upload()
    assert third.status_code == 429 and "Upload limit reached" in third.content.decode()
    assert Scan.objects.count() == 2
    assert client.get(HOME, **who).status_code == 200        # browsing still works


@pytest.mark.django_db
def test_global_upload_limit(fw, settings, tmp_path, fake_store):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = fake_store
    fw.FIREWALL_GLOBAL_UPLOADS_PER_MINUTE = 2
    statuses = []
    for n in range(3):
        who = _from(f"203.0.113.{10 + n}")
        client = Client()
        client.post(ACCEPT, {"next": HOME}, **who)
        statuses.append(client.post(UPLOAD, {"model_key": FAKE_KEY,
                                             "file": SimpleUploadedFile("s.png", _png())}, **who).status_code)
    assert statuses == [302, 302, 429]


# --------------------------------------------------------------------------- #
# Who is asking
# --------------------------------------------------------------------------- #
def test_forwarded_address_is_trusted_only_from_this_machine(rf, settings):
    settings.BEHIND_PROXY = True
    via_tunnel = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.5")
    assert firewall.client_ip(via_tunnel) == "203.0.113.5"
    forwarded_for = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.2, 10.0.0.1")
    assert firewall.client_ip(forwarded_for) == "198.51.100.2"
    direct = rf.get("/", REMOTE_ADDR="192.168.1.50", HTTP_CF_CONNECTING_IP="203.0.113.5")
    assert firewall.client_ip(direct) == "192.168.1.50"       # header ignored: not from the tunnel
    garbage = rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="not-an-ip")
    assert firewall.client_ip(garbage) == "127.0.0.1"

    settings.BEHIND_PROXY = False
    assert firewall.client_ip(via_tunnel) == "127.0.0.1"      # no proxy configured: never trust it


# --------------------------------------------------------------------------- #
# Access code
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_access_code_protects_every_page(fw, client):
    fw.ACCESS_PASSWORD = "k7m2-xq9d"
    who = _from("203.0.113.5")
    for path in (HOME, ABOUT, UPLOAD, "/static/scans/css/site.css", "/robots.txt"):
        response = client.get(path, **who)
        assert response.status_code == 401, path
        assert response["WWW-Authenticate"].startswith('Basic realm="Brain MRI demo"')
        assert not response.cookies
    assert client.post(ACCEPT, {"next": HOME}, **who).status_code == 401
    assert Session.objects.count() == 0

    ok = client.get(HOME, **who, **_basic("demo", "k7m2-xq9d"))
    assert ok.status_code == 200 and "Upload a brain MRI slice" in ok.content.decode()


@pytest.mark.django_db
def test_wrong_access_codes_lead_to_a_ban(fw, client):
    fw.ACCESS_PASSWORD = "k7m2-xq9d"
    fw.FIREWALL_STRIKES_BEFORE_BAN = 5
    who = _from("203.0.113.77")
    assert client.get(HOME, **who).status_code == 401                        # no code yet: no strike
    for guess in ("a", "password", "k7m2-xq9", "K7M2-XQ9D", "demo"):
        assert client.get(HOME, **who, **_basic("demo", guess)).status_code == 401
    # Banned now: even the right code is refused until the ban ends.
    assert client.get(HOME, **who, **_basic("demo", "k7m2-xq9d")).status_code == 429
    assert client.get(HOME, **_from("198.51.100.7"), **_basic("demo", "k7m2-xq9d")).status_code == 200


@pytest.mark.django_db
def test_malformed_authorization_headers_are_just_wrong(fw, client):
    fw.ACCESS_PASSWORD = "secret"
    who = _from("203.0.113.5")
    for header in ("Basic !!!notbase64!!!", "Basic ", "Bearer abc", "Basic " + base64.b64encode(b"\xff\xfe").decode()):
        assert client.get(HOME, **who, HTTP_AUTHORIZATION=header).status_code == 401


# --------------------------------------------------------------------------- #
# Browser-side policy
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_content_policy_on_every_response(client, settings):
    for path in (HOME, ABOUT, "/nope/"):
        response = client.get(path)
        policy = response["Content-Security-Policy"]
        for rule in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "object-src 'none'",
                     "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"):
            assert rule in policy, (path, rule)
        assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
        assert "camera=()" in response["Permissions-Policy"]
        assert response["X-Content-Type-Options"] == "nosniff"
        assert "X-Robots-Tag" not in response
    settings.NO_INDEX = True
    assert client.get(HOME)["X-Robots-Tag"] == "noindex, nofollow"


def test_templates_and_scripts_have_nothing_the_policy_would_block():
    """No inline script, inline style or event-handler attribute anywhere."""
    for path in list((REPO_ROOT / "templates").rglob("*.html")) + list((REPO_ROOT / "scans" / "templates").rglob("*.html")):
        text = path.read_text()
        assert not re.search(r"<style[\s>]", text), path
        assert not re.search(r"\sstyle\s*=", text), path
        assert not re.search(r"\son[a-z]+\s*=", text), path
        assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", text), path
        assert "javascript:" not in text, path
        for url in re.findall(r"""(?:src|href)=["']((?:https?:)?//[^"']+)""", text):
            pytest.fail(f"{path} loads an outside resource: {url}")
    for path in (REPO_ROOT / "scans" / "static").rglob("*.js"):
        text = path.read_text()
        assert "eval(" not in text and "innerHTML" not in text and "document.write" not in text, path


# --------------------------------------------------------------------------- #
# Format allow-list
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_format_allow_list(settings, tmp_path, fake_store, figshare_mat_file):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = fake_store
    settings.SCAN_ALLOWED_FORMATS = ["png", "jpeg"]
    client = Client()
    client.post(ACCEPT, {"next": HOME})

    page = client.get(UPLOAD).content.decode()
    assert "PNG or JPEG of one slice" in page and ".mat" not in page
    assert "PNG or JPEG files" in client.get(HOME).content.decode()

    mat_path, _ = figshare_mat_file
    refused = client.post(UPLOAD, {"model_key": FAKE_KEY,
                                   "file": SimpleUploadedFile("x.mat", mat_path.read_bytes())})
    assert refused.status_code == 400
    text = refused.content.decode()
    assert "accepts only PNG or JPEG files" in text and "a FigShare .mat file" in text
    assert not Scan.objects.exists()

    accepted = client.post(UPLOAD, {"model_key": FAKE_KEY, "file": SimpleUploadedFile("s.png", _png())})
    assert accepted.status_code == 302


def test_data_locations_follow_the_environment(monkeypatch, tmp_path):
    """DJANGO_DB_PATH / DJANGO_MEDIA_ROOT keep the sharing mode's data apart."""
    import importlib

    from config import settings as project_settings

    monkeypatch.setenv("DJANGO_DB_PATH", str(tmp_path / "share.sqlite3"))
    monkeypatch.setenv("DJANGO_MEDIA_ROOT", str(tmp_path / "share_media"))
    try:
        reloaded = importlib.reload(project_settings)
        assert reloaded.DATABASES["default"]["NAME"] == tmp_path / "share.sqlite3"
        assert reloaded.MEDIA_ROOT == tmp_path / "share_media"
    finally:
        monkeypatch.delenv("DJANGO_DB_PATH")
        monkeypatch.delenv("DJANGO_MEDIA_ROOT")
        restored = importlib.reload(project_settings)
    assert restored.MEDIA_ROOT == restored.BASE_DIR / "media"
    assert restored.DATABASES["default"]["NAME"] == restored.BASE_DIR / "db.sqlite3"

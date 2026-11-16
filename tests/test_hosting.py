"""
Hosting behind an HTTPS proxy (deploy/huggingface/): origin checks, secure
cookie, framing rules, and the script that installs uploaded model files.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy" / "huggingface"

HOME = reverse("scans:home")
ACCEPT = reverse("scans:consent_accept")
DELETE = reverse("scans:delete_my_data")
COOKIE = "sessionid"

SPACE_HOST = "someone-brain-demo.hf.space"
SPACE_ORIGIN = f"https://{SPACE_HOST}"


@pytest.fixture
def hosted(settings):
    """The settings the Space's Dockerfile switches on."""
    settings.ALLOWED_HOSTS = ["*"]
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.hf.space"]
    settings.FRAME_ANCESTORS = ["https://huggingface.co"]
    return settings


def _proxied(**extra):
    """Headers of a browser request that arrived through the HTTPS proxy."""
    headers = {"HTTP_HOST": SPACE_HOST, "HTTP_X_FORWARDED_PROTO": "https"}
    headers.update(extra)
    return headers


# --------------------------------------------------------------------------- #
# Origin check of the consent forms
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_https_origin_of_the_same_host_is_accepted_even_if_the_app_sees_http(client):
    # No proxy settings at all: the browser says https, Django sees http.
    response = client.post(ACCEPT, {"next": HOME}, HTTP_ORIGIN="https://testserver",
                           HTTP_SEC_FETCH_SITE="same-origin")
    assert response.status_code == 302 and COOKIE in response.cookies


@pytest.mark.django_db
def test_trusted_origin_is_accepted_when_the_host_header_differs(client, settings):
    settings.ALLOWED_HOSTS = ["*"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.hf.space", "https://exact.example"]
    ok = client.post(ACCEPT, {"next": HOME}, HTTP_HOST="10.0.0.5:7860", HTTP_ORIGIN=SPACE_ORIGIN)
    assert ok.status_code == 302
    exact = Client().post(ACCEPT, {"next": HOME}, HTTP_HOST="10.0.0.5:7860",
                          HTTP_ORIGIN="https://exact.example")
    assert exact.status_code == 302


@pytest.mark.django_db
@pytest.mark.parametrize("origin", [
    "https://evil.example",            # not trusted
    "http://someone.hf.space",         # trusted host, wrong scheme
    "https://hf.space.evil.example",   # looks similar, is not a subdomain
    "null",
])
def test_other_origins_are_still_refused(settings, origin):
    settings.ALLOWED_HOSTS = ["*"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.hf.space"]
    client = Client()
    response = client.post(ACCEPT, {"next": HOME}, HTTP_HOST="10.0.0.5:7860", HTTP_ORIGIN=origin)
    assert response.status_code == 403
    assert not response.cookies and not client.cookies


# --------------------------------------------------------------------------- #
# Behind the proxy
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_hosted_flow_sets_a_secure_cookie_and_csrf_forms_work(hosted):
    client = Client(enforce_csrf_checks=True)
    first = client.get(HOME, **_proxied())
    assert first.status_code == 200 and not first.cookies

    accepted = client.post(ACCEPT, {"next": HOME}, **_proxied(HTTP_ORIGIN=SPACE_ORIGIN,
                                                               HTTP_SEC_FETCH_SITE="same-origin"))
    assert accepted.status_code == 302
    cookie = accepted.cookies[COOKIE]
    assert cookie["secure"] is True and cookie["httponly"] is True and cookie["samesite"] == "Lax"

    # A CSRF-protected form (Delete my data) posted by the browser over https.
    page = client.get(HOME, secure=True, **_proxied()).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    deleted = client.post(DELETE, {"csrfmiddlewaretoken": token}, secure=True,
                          **_proxied(HTTP_ORIGIN=SPACE_ORIGIN))
    assert deleted.status_code == 302


@pytest.mark.django_db
def test_csrf_forms_work_even_if_the_proxy_sends_no_forwarded_proto(hosted):
    """Then Django sees http, and CSRF_TRUSTED_ORIGINS has to carry the https origin."""
    hosted.SESSION_COOKIE_SECURE = False          # the test client would not send a Secure cookie over http
    client = Client(enforce_csrf_checks=True)
    client.post(ACCEPT, {"next": HOME}, HTTP_HOST=SPACE_HOST, HTTP_ORIGIN=SPACE_ORIGIN)
    page = client.get(HOME, HTTP_HOST=SPACE_HOST).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    response = client.post(DELETE, {"csrfmiddlewaretoken": token}, HTTP_HOST=SPACE_HOST,
                           HTTP_ORIGIN=SPACE_ORIGIN)
    assert response.status_code == 302


# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_framing_is_denied_by_default(client):
    response = client.get(HOME)
    assert response["X-Frame-Options"] == "DENY"
    assert response["Content-Security-Policy"].endswith("frame-ancestors 'none'")


@pytest.mark.django_db
def test_listed_sites_may_frame_the_app(client, settings):
    settings.FRAME_ANCESTORS = ["https://huggingface.co"]
    response = client.get(HOME)
    assert response["Content-Security-Policy"].endswith("frame-ancestors 'self' https://huggingface.co")
    assert "X-Frame-Options" not in response


@pytest.mark.django_db
def test_pages_carry_the_open_in_own_tab_notice(client):
    html = client.get(HOME).content.decode()
    assert 'id="framed-notice"' in html and "hidden" in html.split('id="framed-notice"')[1][:60]
    assert "Open the demo in its own tab" in html
    assert "scans/js/frame.js" in html
    script = client.get("/static/scans/js/frame.js")
    assert script.status_code == 200
    body = b"".join(script.streaming_content).decode()
    assert "window.self !== window.top" in body


# --------------------------------------------------------------------------- #
# deploy/huggingface/install_model.py
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def install_model():
    spec = importlib.util.spec_from_file_location("install_model", DEPLOY / "install_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(name="01_dice_image_level", fold=1):
    return json.dumps({"EXPERIMENT": {"name": name, "fold": fold, "model_name": "smp_unet_resnet34"},
                       "training_meta": {"best_val_dice": 0.85}})


def test_install_model_from_two_top_level_files(install_model, tmp_path):
    space, store = tmp_path / "space", tmp_path / "store"
    space.mkdir()
    (space / "best_model.pt").write_bytes(b"\x80" * 5000)
    (space / "experiment_config.json").write_text(_config(fold=3))
    (space / "Dockerfile").write_text("FROM scratch")

    installed = install_model.install(space, store)
    dest = store / "01_dice_image_level" / "fold_3"
    assert installed == [dest]
    assert (dest / "best_model.pt").stat().st_size == 5000
    assert json.loads((dest / "experiment_config.json").read_text())["EXPERIMENT"]["fold"] == 3
    assert install_model.main(["x", str(space), str(store)]) == 0


def test_install_model_from_nested_model_store(install_model, tmp_path):
    space, store = tmp_path / "space", tmp_path / "store"
    for fold in (1, 2):
        d = space / "model_store" / "my_model" / f"fold_{fold}"
        d.mkdir(parents=True)
        (d / "best_model.pt").write_bytes(b"\x80" * 4000)
        (d / "experiment_config.json").write_text(_config("my_model", fold))
    installed = install_model.install(space, store)
    assert sorted(p.name for p in installed) == ["fold_1", "fold_2"]
    assert (store / "my_model" / "fold_2" / "experiment_config.json").is_file()


def test_install_model_without_files_is_a_warning_not_an_error(install_model, tmp_path, capsys):
    space = tmp_path / "space"
    space.mkdir()
    assert install_model.main(["x", str(space), str(tmp_path / "store")]) == 0
    assert "no model files found" in capsys.readouterr().out


def test_install_model_rejects_lfs_pointers_and_lonely_files(install_model, tmp_path):
    space = tmp_path / "space"
    space.mkdir()
    (space / "best_model.pt").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 97000000\n")
    (space / "experiment_config.json").write_text(_config())
    with pytest.raises(SystemExit, match="Git LFS pointer"):
        install_model.install(space, tmp_path / "store")

    (space / "best_model.pt").write_bytes(b"\x80" * 5000)
    (space / "experiment_config.json").unlink()
    with pytest.raises(SystemExit, match="upload both"):
        install_model.install(space, tmp_path / "store2")

    (space / "experiment_config.json").write_text(json.dumps({"EXPERIMENT": {}}))
    with pytest.raises(SystemExit, match="no EXPERIMENT name and fold"):
        install_model.install(space, tmp_path / "store3")


def test_install_model_keeps_the_key_inside_the_store(install_model, tmp_path):
    space, store = tmp_path / "space", tmp_path / "store"
    space.mkdir()
    (space / "best_model.pt").write_bytes(b"\x80" * 5000)
    (space / "experiment_config.json").write_text(_config(name="../../etc/x y", fold=1))
    (dest,) = install_model.install(space, store)
    assert store.resolve() in dest.resolve().parents
    assert "/" not in dest.parent.name and " " not in dest.parent.name


# --------------------------------------------------------------------------- #
# Deployment files stay consistent with the project
# --------------------------------------------------------------------------- #
def test_deployment_files_are_consistent():
    dockerfile = (DEPLOY / "Dockerfile").read_text()
    lock = (REPO_ROOT / "requirements.lock.txt").read_text()
    card = (DEPLOY / "README.md").read_text()

    assert "requirements.lock.txt" in dockerfile and "deploy/huggingface/start.sh" in dockerfile
    assert "torch==2.8.0" in dockerfile and "torch==2.8.0" in lock
    assert "gunicorn==" in lock and "\ngunicorn\n" in (REPO_ROOT / "requirements.txt").read_text()
    for name in ("DJANGO_BEHIND_PROXY=True", "DJANGO_SECURE_COOKIES=True", "DJANGO_DEBUG=False",
                 "DJANGO_CSRF_TRUSTED_ORIGINS=https://*.hf.space", "DJANGO_FRAME_ANCESTORS=https://huggingface.co"):
        assert name in dockerfile, name
    port = re.search(r"PORT=(\d+)", dockerfile).group(1)
    assert f"app_port: {port}" in card and "sdk: docker" in card
    assert card.startswith("---\n")
    assert "Not for diagnosis" in card
    start = (DEPLOY / "start.sh").read_text()
    assert "migrate" in start and "purge_old_scans" in start and "gunicorn config.wsgi:application" in start

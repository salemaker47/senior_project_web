"""
Cookie consent, anonymous sessions and "Delete my data".

The promises under test:
  * nothing is stored and no cookie is set before the visitor accepts;
  * `request.session` is not even opened for a visitor without a cookie;
  * accepting sets exactly one cookie (14 days, HttpOnly, SameSite=Lax);
  * upload and result are blocked without consent;
  * "Delete my data" removes this visitor's scans, files, session and cookie.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

import pytest
from django.conf import settings as django_settings
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from inference import DISCLAIMER
from scans import services
from scans.consent import (
    CONSENT_AT_SESSION_KEY,
    CONSENT_SESSION_KEY,
    OWNER_SESSION_KEY,
    consent_required,
    is_valid_owner_id,
)
from scans.models import Scan

pytestmark = pytest.mark.django_db

COOKIE = "sessionid"
FOURTEEN_DAYS = 14 * 24 * 60 * 60

HOME = reverse("scans:home")
ABOUT = reverse("scans:about")
UPLOAD = reverse("scans:upload")
ACCEPT = reverse("scans:consent_accept")
DECLINE = reverse("scans:consent_decline")
DELETE = reverse("scans:delete_my_data")


@pytest.fixture(autouse=True)
def _isolated_files(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MODEL_STORE_DIR = tmp_path / "model_store"


def _text(response) -> str:
    return response.content.decode()


def _assert_untouched(response, client):
    """No cookie in the response or the client, and the session was never opened."""
    assert not response.cookies, f"cookies set: {list(response.cookies)}"
    assert not client.cookies
    assert response.wsgi_request.session.accessed is False
    assert Session.objects.count() == 0


def _accept(client, **extra):
    return client.post(ACCEPT, {"next": extra.pop("next", HOME)}, **extra)


def _make_scan(owner_id: str, name: str = "scan.png") -> Scan:
    scan = Scan.objects.create(owner_id=owner_id, original_name=name)
    folder = services.scan_media_dir(owner_id, scan.id)
    folder.mkdir(parents=True)
    (folder / "input.png").write_bytes(b"input")
    (folder / "mask.png").write_bytes(b"mask")
    return scan


# --------------------------------------------------------------------------- #
# Before consent
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [HOME, ABOUT])
def test_no_session_cookie_before_accepting(client, url):
    response = client.get(url)
    assert response.status_code == 200
    _assert_untouched(response, client)
    html = _text(response)
    assert 'id="cookie-banner"' in html
    assert "single essential session cookie" in html
    assert "no tracking and no account" in html
    # A CSRF token would have to live in a session, so none may be rendered.
    assert "csrfmiddlewaretoken" not in html
    assert f'action="{DELETE}"' not in html


def test_several_page_views_still_set_nothing(client):
    for url in (HOME, ABOUT, HOME, UPLOAD, ABOUT):
        response = client.get(url)
        _assert_untouched(response, client)


def test_home_shows_disabled_upload_with_explanation(client):
    html = _text(client.get(HOME))
    assert re.search(r"<button[^>]*disabled[^>]*>Upload a scan</button>", html)
    assert "Upload is disabled until you accept the session cookie" in html
    assert f'href="{UPLOAD}"' not in html


def test_upload_is_blocked_without_consent(client):
    response = client.get(UPLOAD)
    assert response.status_code == 403
    _assert_untouched(response, client)
    html = _text(response)
    assert "needs the session cookie" in html
    assert f'action="{ACCEPT}"' in html and f'name="next" value="{UPLOAD}"' in html


def test_upload_post_is_blocked_without_consent(client):
    response = client.post(UPLOAD, {"file": "x"})
    assert response.status_code == 403
    _assert_untouched(response, client)


def test_result_is_blocked_without_consent(client):
    scan = _make_scan(uuid.uuid4().hex)
    response = client.get(reverse("scans:result", args=[scan.id]))
    assert response.status_code == 403
    _assert_untouched(response, client)


def test_delete_is_blocked_without_consent(client):
    scan = _make_scan(uuid.uuid4().hex)
    response = client.post(DELETE)
    assert response.status_code == 403
    _assert_untouched(response, client)
    assert Scan.objects.filter(pk=scan.pk).exists()


def test_decline_stores_nothing_and_keeps_pages_readable(client):
    response = client.post(DECLINE, {"next": ABOUT})
    assert response.status_code == 302
    assert response["Location"] == f"{ABOUT}?consent=declined"
    _assert_untouched(response, client)

    about = client.get(response["Location"])
    assert about.status_code == 200
    _assert_untouched(about, client)
    assert "cookie-banner is-declined" in _text(about)
    assert "upload is disabled" in _text(about)

    home = client.get(HOME)
    assert home.status_code == 200
    assert re.search(r"<button[^>]*disabled[^>]*>Upload a scan</button>", _text(home))
    assert client.get(UPLOAD).status_code == 403
    _assert_untouched(home, client)


def test_stale_session_cookie_is_not_consent_and_is_removed(client):
    client.cookies[COOKIE] = "thissessiondoesnotexist"
    response = client.get(HOME)
    assert response.status_code == 200
    assert 'id="cookie-banner"' in _text(response)
    assert response.cookies[COOKIE].value == ""
    assert response.cookies[COOKIE]["max-age"] == 0
    assert Session.objects.count() == 0
    assert client.get(UPLOAD).status_code == 403


# --------------------------------------------------------------------------- #
# Accepting
# --------------------------------------------------------------------------- #
def test_accepting_sets_the_session_cookie(client):
    response = _accept(client, next=UPLOAD)
    assert response.status_code == 302 and response["Location"] == UPLOAD

    assert list(response.cookies) == [COOKIE]
    cookie = response.cookies[COOKIE]
    assert cookie.value
    assert cookie["max-age"] == FOURTEEN_DAYS
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"

    session = client.session
    assert session[CONSENT_SESSION_KEY] is True
    stamp = datetime.fromisoformat(session[CONSENT_AT_SESSION_KEY])
    assert stamp.tzinfo is not None
    assert is_valid_owner_id(session[OWNER_SESSION_KEY])
    assert Session.objects.count() == 1


def test_after_accepting_banner_is_gone_and_upload_opens(client):
    _accept(client)
    home = client.get(HOME)
    html = _text(home)
    assert 'id="cookie-banner"' not in html
    assert f'href="{UPLOAD}"' in html
    assert f'action="{DELETE}"' in html and "Delete my data" in html
    assert client.get(UPLOAD).status_code == 200


def test_only_one_cookie_is_ever_set(client):
    """CSRF tokens are kept in the session: no `csrftoken` cookie appears."""
    _accept(client)
    for url in (HOME, ABOUT, UPLOAD):
        response = client.get(url)
        assert "csrfmiddlewaretoken" in _text(response)
        assert set(response.cookies) <= {COOKIE}
    assert set(client.cookies) == {COOKIE}


def test_accepting_twice_keeps_owner_and_timestamp(client):
    _accept(client)
    first = dict(client.session)
    _accept(client)
    second = dict(client.session)
    assert second[OWNER_SESSION_KEY] == first[OWNER_SESSION_KEY]
    assert second[CONSENT_AT_SESSION_KEY] == first[CONSENT_AT_SESSION_KEY]
    assert Session.objects.count() == 1


def test_accept_must_be_a_post(client):
    response = client.get(ACCEPT)
    assert response.status_code == 405
    _assert_untouched(response, client)
    assert client.get(DECLINE).status_code == 405


@pytest.mark.parametrize("headers", [
    {"HTTP_SEC_FETCH_SITE": "cross-site"},
    {"HTTP_SEC_FETCH_SITE": "same-site"},
    {"HTTP_ORIGIN": "https://evil.example"},
    {"HTTP_ORIGIN": "null"},
])
def test_cross_site_accept_is_refused(client, headers):
    response = client.post(ACCEPT, {"next": HOME}, **headers)
    assert response.status_code == 403
    _assert_untouched(response, client)


def test_same_origin_browser_accept_is_allowed(client):
    response = client.post(ACCEPT, {"next": HOME}, HTTP_SEC_FETCH_SITE="same-origin",
                           HTTP_ORIGIN="http://testserver")
    assert response.status_code == 302 and COOKIE in response.cookies


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/x", "javascript:alert(1)"])
def test_next_cannot_leave_the_site(client, target):
    assert _accept(client, next=target)["Location"] == HOME
    assert Client().post(DECLINE, {"next": target})["Location"] == f"{HOME}?consent=declined"


def test_decline_after_accepting_changes_nothing(client):
    _accept(client)
    response = client.post(DECLINE, {"next": ABOUT})
    assert response["Location"] == ABOUT
    assert client.session[CONSENT_SESSION_KEY] is True


# --------------------------------------------------------------------------- #
# Result view ownership
# --------------------------------------------------------------------------- #
def test_result_is_visible_to_its_owner_only(client):
    _accept(client)
    mine = _make_scan(client.session[OWNER_SESSION_KEY])
    theirs = _make_scan(uuid.uuid4().hex)

    response = client.get(reverse("scans:result", args=[mine.id]))
    assert response.status_code == 200
    assert DISCLAIMER in _text(response)
    assert client.get(reverse("scans:result", args=[theirs.id])).status_code == 404


# --------------------------------------------------------------------------- #
# Delete my data
# --------------------------------------------------------------------------- #
def test_delete_my_data_clears_scans_files_session_and_cookie(client, settings):
    _accept(client)
    owner = client.session[OWNER_SESSION_KEY]
    session_key = client.session.session_key
    _make_scan(owner, "a.png")
    _make_scan(owner, "b.png")
    other_owner = uuid.uuid4().hex
    other = _make_scan(other_owner)
    assert services.owner_media_dir(owner).is_dir()

    response = client.post(DELETE)
    assert response.status_code == 302 and response["Location"] == f"{HOME}?deleted=1"

    # Cookie cleared in the browser, session row gone on the server.
    assert response.cookies[COOKIE].value == ""
    assert response.cookies[COOKIE]["max-age"] == 0
    assert not Session.objects.filter(session_key=session_key).exists()
    assert Session.objects.count() == 0

    # This visitor's rows and files are gone; another visitor's are untouched.
    assert not Scan.objects.filter(owner_id=owner).exists()
    assert not services.owner_media_dir(owner).exists()
    assert Scan.objects.filter(pk=other.pk).exists()
    assert (services.scan_media_dir(other_owner, other.id) / "mask.png").is_file()

    # The browser drops the expired cookie; the old id no longer works.
    client.cookies.clear()
    home = client.get(response["Location"])
    html = _text(home)
    assert "were deleted" in html and 'id="cookie-banner"' in html
    _assert_untouched(home, client)
    assert client.get(UPLOAD).status_code == 403

    replay = Client()
    replay.cookies[COOKIE] = session_key
    assert replay.get(UPLOAD).status_code == 403


def test_delete_my_data_must_be_a_post(client):
    _accept(client)
    assert client.get(DELETE).status_code == 405
    assert client.session[CONSENT_SESSION_KEY] is True


def test_delete_my_data_needs_a_csrf_token():
    client = Client(enforce_csrf_checks=True)
    _accept(client)                                   # consent forms carry no token by design
    assert client.post(DELETE).status_code == 403
    assert client.session[CONSENT_SESSION_KEY] is True

    html = _text(client.get(HOME))
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
    response = client.post(DELETE, {"csrfmiddlewaretoken": token})
    assert response.status_code == 302
    assert Session.objects.count() == 0


def test_owner_media_dir_rejects_foreign_ids():
    for bad in ("", "../etc", "a" * 31, "A" * 32, None):
        with pytest.raises(ValueError):
            services.owner_media_dir(bad)


# --------------------------------------------------------------------------- #
# Decorator, settings, about page
# --------------------------------------------------------------------------- #
def test_consent_required_decorator_does_not_run_the_view(rf):
    calls = []

    @consent_required
    def view(request):
        calls.append(request)

    request = rf.get("/anything/")
    response = view(request)
    assert response.status_code == 403 and calls == []
    assert not hasattr(request, "session")            # nothing even looked for one


def test_settings():
    s = django_settings
    assert s.SESSION_COOKIE_AGE == FOURTEEN_DAYS
    assert s.SESSION_COOKIE_HTTPONLY is True
    assert s.SESSION_COOKIE_SAMESITE == "Lax"
    assert s.CSRF_USE_SESSIONS is True
    assert s.DATABASES["default"]["ENGINE"].endswith("sqlite3")
    assert s.SCAN_MAX_UPLOAD_BYTES == 32 * 1024 * 1024
    assert s.FILE_UPLOAD_MAX_MEMORY_SIZE <= s.SCAN_MAX_UPLOAD_BYTES
    assert s.DATA_UPLOAD_MAX_NUMBER_FILES == 1
    assert "django.contrib.auth" not in s.INSTALLED_APPS
    assert "django.contrib.admin" not in s.INSTALLED_APPS


def test_project_paths():
    from pathlib import Path

    from config import settings as project_settings

    base = Path(project_settings.__file__).resolve().parent.parent
    assert project_settings.MEDIA_ROOT == base / "media"
    assert project_settings.STATIC_ROOT == base / "staticfiles"
    assert project_settings.BASE_DIR == base


def test_about_with_empty_model_store(client):
    response = client.get(ABOUT)
    html = _text(response)
    assert "No trained models are installed yet" in html
    assert DISCLAIMER in html
    assert "Limits" in html
    _assert_untouched(response, client)


def test_about_lists_served_models(client, settings):
    from tests.fake_checkpoint import fake_experiment

    key = "07_unetpp_effb4_dicebce_image_level"
    for fold, score in ((1, 0.81), (2, 0.87)):
        fold_dir = settings.MODEL_STORE_DIR / key / f"fold_{fold}"
        fold_dir.mkdir(parents=True)
        (fold_dir / "best_model.pt").write_bytes(b"")          # never opened for listing
        exp = fake_experiment(key=key, fold=fold, model_name="smp_unetpp_efficientnetb4")
        (fold_dir / "experiment_config.json").write_text(json.dumps({
            "EXPERIMENT": exp, "training_meta": {"best_val_dice": score},
        }))

    html = _text(client.get(ABOUT))
    assert key in html
    assert "U-Net++ (EfficientNet-B4)" in html
    assert "T1 contrast-enhanced slice" in html
    assert "2 of 2" in html and "0.8700" in html


def test_disclaimer_is_on_every_page(client):
    _accept(client)
    for url in (HOME, ABOUT, UPLOAD):
        assert DISCLAIMER in _text(client.get(url))

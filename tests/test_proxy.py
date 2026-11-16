"""
Behind an HTTPS proxy (the sharing tunnel, deploy/tunnel/): origin checks of
the consent forms, the secure cookie, CSRF-protected forms, and framing.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.urls import reverse

HOME = reverse("scans:home")
ACCEPT = reverse("scans:consent_accept")
DELETE = reverse("scans:delete_my_data")
COOKIE = "sessionid"

TUNNEL_HOST = "some-random-words.trycloudflare.com"
TUNNEL_ORIGIN = f"https://{TUNNEL_HOST}"


@pytest.fixture
def hosted(settings):
    """The settings the sharing launcher switches on."""
    settings.ALLOWED_HOSTS = [".trycloudflare.com"]
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com"]
    return settings


def _proxied(**extra):
    """Headers of a browser request that arrived through the HTTPS proxy."""
    headers = {"HTTP_HOST": TUNNEL_HOST, "HTTP_X_FORWARDED_PROTO": "https"}
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
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com", "https://exact.example"]
    ok = client.post(ACCEPT, {"next": HOME}, HTTP_HOST="10.0.0.5:7860", HTTP_ORIGIN=TUNNEL_ORIGIN)
    assert ok.status_code == 302
    exact = Client().post(ACCEPT, {"next": HOME}, HTTP_HOST="10.0.0.5:7860",
                          HTTP_ORIGIN="https://exact.example")
    assert exact.status_code == 302


@pytest.mark.django_db
@pytest.mark.parametrize("origin", [
    "https://evil.example",                    # not trusted
    "http://someone.trycloudflare.com",        # trusted host, wrong scheme
    "https://trycloudflare.com.evil.example",  # looks similar, is not a subdomain
    "null",
])
def test_other_origins_are_still_refused(settings, origin):
    settings.ALLOWED_HOSTS = ["*"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.trycloudflare.com"]
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

    accepted = client.post(ACCEPT, {"next": HOME}, **_proxied(HTTP_ORIGIN=TUNNEL_ORIGIN,
                                                               HTTP_SEC_FETCH_SITE="same-origin"))
    assert accepted.status_code == 302
    cookie = accepted.cookies[COOKIE]
    assert cookie["secure"] is True and cookie["httponly"] is True and cookie["samesite"] == "Lax"

    # A CSRF-protected form (Delete my data) posted by the browser over https.
    page = client.get(HOME, secure=True, **_proxied()).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    deleted = client.post(DELETE, {"csrfmiddlewaretoken": token}, secure=True,
                          **_proxied(HTTP_ORIGIN=TUNNEL_ORIGIN))
    assert deleted.status_code == 302


@pytest.mark.django_db
def test_csrf_forms_work_even_if_the_proxy_sends_no_forwarded_proto(hosted):
    """Then Django sees http, and CSRF_TRUSTED_ORIGINS has to carry the https origin."""
    hosted.SESSION_COOKIE_SECURE = False          # the test client would not send a Secure cookie over http
    client = Client(enforce_csrf_checks=True)
    client.post(ACCEPT, {"next": HOME}, HTTP_HOST=TUNNEL_HOST, HTTP_ORIGIN=TUNNEL_ORIGIN)
    page = client.get(HOME, HTTP_HOST=TUNNEL_HOST).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    response = client.post(DELETE, {"csrfmiddlewaretoken": token}, HTTP_HOST=TUNNEL_HOST,
                           HTTP_ORIGIN=TUNNEL_ORIGIN)
    assert response.status_code == 302


# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_framing_is_denied(client):
    response = client.get(HOME)
    assert response["X-Frame-Options"] == "DENY"
    assert response["Content-Security-Policy"].endswith("frame-ancestors 'none'")

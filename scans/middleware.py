"""scans/middleware.py — CSRF without a cookie, security headers, and correct caching headers."""

from __future__ import annotations

from django.conf import settings
from django.middleware.clickjacking import XFrameOptionsMiddleware
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.cache import patch_vary_headers

from .consent import has_session_cookie


class ConsentAwareCsrfViewMiddleware(CsrfViewMiddleware):
    """
    Django's CSRF protection with the secret stored in the session
    (`CSRF_USE_SESSIONS = True`), so the site never sets a `csrftoken` cookie.

    The stock middleware reads `request.session` on every request to look for
    the secret. A visitor without a session cookie cannot have one, so for them
    the answer is given without opening the session. Effects:
      * pages viewed before consent never touch the session;
      * a POST to a protected view before consent is rejected (no secret).

    `_get_secret` is a private method of Django 4.2's CsrfViewMiddleware.
    tests/test_consent.py fails if a Django upgrade changes this behaviour.
    """

    def _get_secret(self, request):
        if not has_session_cookie(request):
            return None
        return super()._get_secret(request)


# The site loads only its own files: no CDN, no inline script or style, no
# plugins, forms post only to itself, and no other page may show it in a frame.
# A browser enforcing this cannot be made to run injected script even if some
# text were ever rendered unescaped.
CONTENT_POLICY = (
    "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware(XFrameOptionsMiddleware):
    """
    Browser-side protection headers on every response: the content policy
    above, Django's `X-Frame-Options: DENY` (for browsers that ignore
    `frame-ancestors`), a permissions policy, and `X-Robots-Tag` when
    settings.NO_INDEX is on.
    """

    def process_response(self, request, response):
        response = super().process_response(request, response)
        response.headers["Content-Security-Policy"] = CONTENT_POLICY
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        if settings.NO_INDEX:
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response


class VaryOnCookieMiddleware:
    """
    Every page depends on the session cookie (banner or no banner), but pages
    for visitors without a cookie never open the session, so Django would not
    add `Vary: Cookie` by itself.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_vary_headers(response, ("Cookie",))
        return response

"""scans/middleware.py — CSRF without a cookie, and correct caching headers."""

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
# plugins, forms post only to itself. A browser enforcing this cannot be made
# to run injected script even if some text were ever rendered unescaped.
CONTENT_POLICY = (
    "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class FrameAncestorsMiddleware(XFrameOptionsMiddleware):
    """
    Browser-side protection headers on every response.

    Content-Security-Policy: CONTENT_POLICY plus who may show the site in a
    frame. Default: nobody (`frame-ancestors 'none'` and Django's usual
    `X-Frame-Options: DENY`). When settings.FRAME_ANCESTORS lists sites, those
    and the site itself are allowed; X-Frame-Options cannot name a site, so it
    is left out then. A hosting page such as huggingface.co shows the app in a
    frame, where the session cookie does not work, so base.html then tells the
    visitor to open the site in its own tab (static/scans/js/frame.js).
    """

    def process_response(self, request, response):
        ancestors = settings.FRAME_ANCESTORS
        if ancestors:
            frame_rule = "frame-ancestors 'self' " + " ".join(ancestors)
        else:
            frame_rule = "frame-ancestors 'none'"
            response = super().process_response(request, response)
        response.headers["Content-Security-Policy"] = f"{CONTENT_POLICY}; {frame_rule}"
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

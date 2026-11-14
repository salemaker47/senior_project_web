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


class FrameAncestorsMiddleware(XFrameOptionsMiddleware):
    """
    Who may show this site inside a frame.

    Default: nobody (`X-Frame-Options: DENY`, Django's usual behaviour). When
    settings.FRAME_ANCESTORS lists sites, those and the site itself are allowed
    through a Content-Security-Policy header instead; X-Frame-Options cannot
    name a site. A hosting page such as huggingface.co shows the app in a
    frame, where the session cookie does not work, so base.html then tells
    the visitor to open the site in its own tab (static/scans/js/frame.js).
    """

    def process_response(self, request, response):
        ancestors = settings.FRAME_ANCESTORS
        if not ancestors:
            return super().process_response(request, response)
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' " + " ".join(ancestors)
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

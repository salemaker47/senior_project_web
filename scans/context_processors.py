"""Template context shared by every page."""

from __future__ import annotations

from django.conf import settings

from inference import DISCLAIMER

from . import services
from .consent import has_consent

DECLINED_QUERY_VALUE = "declined"


def site(request):
    """
    `cookie_consent`    the visitor accepted the session cookie
    `consent_declined`  the visitor has just declined (from the redirect URL;
                        nothing is stored on the server for a decline)

    Templates must use `cookie_consent` and never `request.session`: for a
    visitor without a cookie that would create exactly the session we promise
    not to create. `{% csrf_token %}` belongs inside `{% if cookie_consent %}`
    for the same reason.
    """
    consent = has_consent(request)
    return {
        "cookie_consent": consent,
        "consent_declined": (not consent) and request.GET.get("consent") == DECLINED_QUERY_VALUE,
        "disclaimer": DISCLAIMER,
        "session_cookie_days": settings.SESSION_COOKIE_AGE // (24 * 60 * 60),
        "max_upload_mb": settings.SCAN_MAX_UPLOAD_BYTES // (1024 * 1024),
        "max_upload_bytes": settings.SCAN_MAX_UPLOAD_BYTES,
        "format_summary": services.format_summary(),
    }

"""
scans/consent.py

Cookie consent without accounts.

Rules this module enforces:
  * No session exists before the visitor accepts. A visitor without a session
    cookie is never asked for `request.session`, in views or in templates.
  * Accepting creates the session and stores `cookie_consent` and a timestamp.
    Scans and predictions are linked to the visitor by the session key.
  * Declining stores nothing on the server and sets no cookie.

Everything that needs to know whether the visitor accepted goes through
`has_consent(request)`.
"""

from __future__ import annotations

from functools import wraps
from typing import Optional
from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import is_same_domain, url_has_allowed_host_and_scheme

CONSENT_SESSION_KEY = "cookie_consent"
CONSENT_AT_SESSION_KEY = "cookie_consent_at"
_CACHE_ATTR = "_cookie_consent"


def has_session_cookie(request) -> bool:
    """True if the browser sent our session cookie. Does not open the session."""
    return bool(request.COOKIES.get(settings.SESSION_COOKIE_NAME))


def has_consent(request) -> bool:
    """
    True if this visitor accepted the session cookie.

    Without a session cookie the answer is "no" and `request.session` is not
    touched. With one, the session is read; a stale or forged cookie loads as
    an empty session, counts as "no", and Django's SessionMiddleware then
    removes the cookie.
    """
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    if not has_session_cookie(request):
        result = False
    else:
        result = request.session.get(CONSENT_SESSION_KEY) is True
    setattr(request, _CACHE_ATTR, result)
    return result


def grant_consent(request) -> None:
    """Create the session (this is what sets the cookie) and record the consent."""
    session = request.session
    if session.get(CONSENT_SESSION_KEY) is not True:
        session[CONSENT_SESSION_KEY] = True
        session[CONSENT_AT_SESSION_KEY] = timezone.now().isoformat()
    session.set_expiry(settings.SESSION_COOKIE_AGE)
    setattr(request, _CACHE_ATTR, True)


def clear_session(request) -> None:
    """Delete the session row and the cookie."""
    request.session.flush()
    setattr(request, _CACHE_ATTR, False)


def get_session_key(request) -> Optional[str]:
    """
    The session key that links this browser to its scans, or None for a
    visitor who has not accepted (the session is not touched for them).
    """
    if not has_consent(request):
        return None
    return request.session.session_key or None


def consent_required(view):
    """
    Decorator for views that store or show a visitor's data (upload, result,
    delete). Visitors who have not accepted get a 403 page that explains why
    and offers the accept button; the view itself does not run.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not has_consent(request):
            return render(request, "scans/consent_required.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def is_same_origin_post(request) -> bool:
    """
    Guard for the accept / decline forms, which cannot carry a CSRF token: a
    token needs a session, and there is none before consent.

    Browsers label cross-site form posts with `Sec-Fetch-Site` and `Origin`;
    such requests are refused, so another site cannot make a visitor "accept".
    Clients that send neither header (curl, the test client) are allowed: they
    are not a browser acting for a victim.

    The Origin must name this site's host. The scheme is not compared: behind
    an HTTPS proxy the browser says https while this process sees http. An
    origin listed in settings.CSRF_TRUSTED_ORIGINS is accepted as well.
    """
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None and fetch_site.lower() not in ("same-origin", "none"):
        return False
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    parts = urlsplit(origin)
    if not parts.netloc:
        return False                       # "null" and other opaque origins
    if parts.netloc == request.get_host():
        return True
    return _is_trusted_origin(parts.scheme, parts.netloc)


def _is_trusted_origin(scheme: str, netloc: str) -> bool:
    """Same matching as Django's CSRF_TRUSTED_ORIGINS: exact, or `*.domain` wildcards."""
    for trusted in settings.CSRF_TRUSTED_ORIGINS:
        t = urlsplit(trusted)
        if t.scheme != scheme:
            continue
        if t.netloc.startswith("*."):
            if is_same_domain(netloc, t.netloc[1:]):
                return True
        elif t.netloc == netloc:
            return True
    return False


def safe_next_url(request, default: str = "/") -> str:
    """The `next` form field if it points back to this site, else `default`."""
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default

"""scans/views.py"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import services
from .consent import (
    clear_session,
    consent_required,
    get_owner_id,
    grant_consent,
    has_consent,
    is_same_origin_post,
    safe_next_url,
)
from .context_processors import DECLINED_QUERY_VALUE
from .models import Scan


# --------------------------------------------------------------------------- #
# Pages everyone can read
# --------------------------------------------------------------------------- #
@require_GET
def home(request):
    return render(request, "scans/home.html", {
        "data_deleted": request.GET.get("deleted") == "1",
    })


@require_GET
def about(request):
    served = services.list_served_models()
    return render(request, "scans/about.html", {
        "models": served["models"],
        "models_error": served["error"],
        "supported_formats": services.SUPPORTED_FORMATS,
    })


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #
def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _without_query(url: str, *names: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in names]
    return urlunsplit(parts._replace(query=urlencode(query)))


# No CSRF token on these two forms: a token needs a session, and the point is
# that there is none yet. `is_same_origin_post` refuses cross-site posts.
@csrf_exempt
@require_POST
def consent_accept(request):
    if not is_same_origin_post(request):
        return HttpResponseForbidden("Cross-site request refused.")
    grant_consent(request)
    return redirect(_without_query(safe_next_url(request, reverse("scans:home")), "consent", "deleted"))


@csrf_exempt
@require_POST
def consent_decline(request):
    """Stores nothing and sets no cookie. The redirect URL carries the choice."""
    if not is_same_origin_post(request):
        return HttpResponseForbidden("Cross-site request refused.")
    target = safe_next_url(request, reverse("scans:home"))
    if has_consent(request):
        # Already accepted earlier: withdrawing is what "Delete my data" does.
        return redirect(target)
    return redirect(_with_query(_without_query(target, "deleted"), consent=DECLINED_QUERY_VALUE))


@consent_required
@require_POST
def delete_my_data(request):
    """Remove this visitor's scans and files, then the session and its cookie."""
    owner_id = get_owner_id(request)
    if owner_id:
        services.delete_owner_data(owner_id)
    clear_session(request)
    return redirect(_with_query(reverse("scans:home"), deleted="1"))


# --------------------------------------------------------------------------- #
# Upload and result (filled in Phase 3)
# --------------------------------------------------------------------------- #
@consent_required
@require_GET
def upload(request):
    return render(request, "scans/upload.html", {
        "supported_formats": services.SUPPORTED_FORMATS,
    })


@consent_required
@require_GET
def result(request, scan_id):
    # A scan of another visitor is a 404, not a 403: its existence is not revealed.
    scan = get_object_or_404(Scan, pk=scan_id, owner_id=get_owner_id(request))
    return render(request, "scans/result.html", {"scan": scan})

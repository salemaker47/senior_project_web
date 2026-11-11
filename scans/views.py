"""scans/views.py"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import services
from .consent import (
    clear_session,
    consent_required,
    get_session_key,
    grant_consent,
    has_consent,
    is_same_origin_post,
    safe_next_url,
)
from .context_processors import DECLINED_QUERY_VALUE
from .forms import UploadForm
from .models import Scan
from .uploadhandlers import TOO_LARGE_ATTR


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
    services.delete_session_data(get_session_key(request))
    clear_session(request)
    return redirect(_with_query(reverse("scans:home"), deleted="1"))


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #
def _owned_scan_or_404(request, scan_id) -> Scan:
    """
    The scan, if this request's session owns it. Everything else is a 404: no
    session, another visitor's scan and a scan that does not exist all look
    the same from outside.
    """
    session_key = get_session_key(request)
    if not session_key:
        raise Http404("No such scan.")
    return get_object_or_404(Scan, pk=scan_id, session_key=session_key)


# --------------------------------------------------------------------------- #
# Upload and predict
# --------------------------------------------------------------------------- #
@consent_required
@require_http_methods(["GET", "POST"])
def upload(request):
    status = 200
    if request.method == "POST":
        form = UploadForm(
            request.POST, request.FILES,
            upload_too_large=getattr(request, TOO_LARGE_ATTR, False),
        )
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            scan = services.create_scan(
                get_session_key(request), uploaded.name, uploaded.size, form.loaded_scan,
            )
            prediction = services.create_prediction(scan, form.cleaned_data["model_key"])
            # Runs in the request for now; the function only needs the id, so it
            # can be handed to a background worker later.
            services.run_prediction(prediction.id)
            return redirect("scans:result", scan_id=scan.id)
        status = 400
    else:
        form = UploadForm()

    selected = form["model_key"].value()
    if not selected and len(form.grouped_choices) == 1 and len(form.grouped_choices[0][1]) == 1:
        selected = form.grouped_choices[0][1][0][0]          # the only model there is
    return render(request, "scans/upload.html", {
        "form": form,
        "selected_model": selected,
        "supported_formats": services.SUPPORTED_FORMATS,
        "models_error": services.list_served_models()["error"],
    }, status=status)


# --------------------------------------------------------------------------- #
# Result, files, downloads
# --------------------------------------------------------------------------- #
@consent_required
@require_GET
def result(request, scan_id):
    scan = _owned_scan_or_404(request, scan_id)
    prediction = scan.latest_prediction
    summary = prediction.summary if prediction else {}
    return render(request, "scans/result.html", {
        "scan": scan,
        "prediction": prediction,
        "summary": summary,
        "share_percent": 100.0 * float(summary.get("tumor_share", 0.0)),
        "format_label": scan.detected_format.replace("_", " "),
    })


def _done_prediction_or_404(request, scan_id):
    scan = _owned_scan_or_404(request, scan_id)
    prediction = scan.latest_prediction
    if prediction is None or not prediction.is_done:
        raise Http404("No result for this scan.")
    return scan, prediction


def _private(response):
    """Results belong to one browser: keep them out of shared caches."""
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def scan_file(request, scan_id, kind):
    """
    The only way a stored file leaves the server. 404 unless this request's
    session owns the scan. `?download=1` sends it as an attachment.
    """
    scan, prediction = _done_prediction_or_404(request, scan_id)
    if kind not in services.RESULT_FILES:
        raise Http404("No such file.")
    field, download_name = services.RESULT_FILES[kind]
    path = services.media_path(getattr(prediction, field))
    if path is None:
        raise Http404("No such file.")
    return _private(FileResponse(
        open(path, "rb"), content_type="image/png",
        as_attachment=request.GET.get("download") == "1", filename=download_name,
    ))


@require_GET
def scan_zip(request, scan_id):
    scan, prediction = _done_prediction_or_404(request, scan_id)
    response = HttpResponse(services.build_zip(prediction), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="scan_{str(scan.id)[:8]}.zip"'
    return _private(response)


# --------------------------------------------------------------------------- #
# My scans
# --------------------------------------------------------------------------- #
@consent_required
@require_GET
def my_scans(request):
    scans = Scan.objects.filter(session_key=get_session_key(request)).prefetch_related("predictions")
    rows = []
    for scan in scans:
        predictions = sorted(scan.predictions.all(), key=lambda p: p.created_at, reverse=True)
        prediction = predictions[0] if predictions else None
        summary = prediction.summary if prediction else {}
        rows.append({
            "scan": scan,
            "prediction": prediction,
            "summary": summary,
            "share_percent": 100.0 * float(summary.get("tumor_share", 0.0)),
        })
    return render(request, "scans/my_scans.html", {
        "rows": rows,
        "scan_deleted": request.GET.get("deleted") == "1",
    })


@require_POST
def delete_scan(request, scan_id):
    scan = _owned_scan_or_404(request, scan_id)
    services.delete_scan(scan)
    return redirect(_with_query(reverse("scans:my_scans"), deleted="1"))

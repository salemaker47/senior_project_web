"""
scans/errors.py — what visitors see when something goes wrong.

Two rules:
  * No stack traces, exception names, file paths or library messages reach a
    visitor. Technical detail goes to the "scans" logger (the console).
  * Error pages follow the consent rules. They render through the normal
    templates, which only ask `has_consent`, so a visitor without a cookie
    can hit a 404 without a session being opened. (Django's default handlers
    open the session through its stock CSRF helper.)
"""

from __future__ import annotations

import logging

from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import loader

logger = logging.getLogger("scans")

# --------------------------------------------------------------------------- #
# Failed predictions
# --------------------------------------------------------------------------- #
MODEL_UNAVAILABLE = (
    "The selected model is not available on this server right now. "
    "Upload the scan again and choose another model, or try again later."
)
SCAN_DATA_MISSING = (
    "The stored image of this scan could not be found. Please upload the scan again."
)
OUT_OF_MEMORY = (
    "The server ran out of memory while running the model. "
    "Try again in a moment, or upload a smaller image."
)
PREDICTION_FAILED = (
    "Something went wrong while running the model. Your file was read correctly, so "
    "this is a problem on our side. Please try again; if it keeps failing, try another model."
)


def friendly_prediction_error(exc: BaseException) -> str:
    """The message stored on a failed Prediction and shown on its result page."""
    from inference.registry import RegistryError

    if isinstance(exc, RegistryError):
        return MODEL_UNAVAILABLE
    if isinstance(exc, FileNotFoundError):
        return SCAN_DATA_MISSING
    if isinstance(exc, MemoryError) or "out of memory" in str(exc).lower():
        return OUT_OF_MEMORY
    return PREDICTION_FAILED


# --------------------------------------------------------------------------- #
# Error pages
# --------------------------------------------------------------------------- #
def _error(request, status: int, title: str, message: str):
    return render(request, "error.html", {"title": title, "message": message}, status=status)


def bad_request(request, exception=None):
    return _error(
        request, 400, "That request could not be handled",
        "The request was not in the form this site expects. If you were uploading a scan, "
        "go back and try again with a single file.",
    )


def permission_denied(request, exception=None):
    return _error(request, 403, "Not allowed", "You are not allowed to do that.")


def csrf_failure(request, reason=""):
    """A form was submitted without a valid security token (expired session, old tab)."""
    logger.info("CSRF check failed for %s: %s", request.path, reason)
    return _error(
        request, 403, "That form has expired",
        "For your safety, forms on this site only work for a limited time and only from "
        "the browser they were opened in. Go back, reload the page and try again. "
        "If you deleted your data or the cookie in the meantime, accept the cookie again first.",
    )


def not_found(request, exception=None):
    return _error(
        request, 404, "Page not found",
        "There is nothing at this address. A scan that was deleted, or that belongs to "
        "another browser, also ends up here.",
    )


def server_error(request):
    # No request context here: after an unexpected error, touch as little as possible.
    # Django has already logged the traceback to the console.
    return HttpResponseServerError(loader.render_to_string("500.html"))

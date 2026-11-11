"""
scans/errors.py — error pages that follow the consent rules.

They render through the normal templates (which only ask `has_consent`), so a
visitor without a cookie can hit a 404 without a session being opened.
"""

from __future__ import annotations

from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import loader


def _error(request, status: int, title: str, message: str):
    return render(request, "error.html", {"title": title, "message": message}, status=status)


def bad_request(request, exception=None):
    return _error(request, 400, "Bad request", "The request could not be understood.")


def permission_denied(request, exception=None):
    return _error(request, 403, "Not allowed", "You are not allowed to do that.")


def not_found(request, exception=None):
    return _error(
        request, 404, "Page not found",
        "There is nothing at this address. A scan that was deleted, or that belongs to "
        "another browser, also ends up here.",
    )


def server_error(request):
    # No request context here: after an unexpected error, touch as little as possible.
    return HttpResponseServerError(loader.render_to_string("500.html"))

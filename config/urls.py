"""
URL configuration.

MEDIA_URL is deliberately not routed: stored scans and results belong to one
visitor and are served by scans.views.scan_file, which checks the owner.

Static files (our own CSS and JavaScript) are served by Django itself, also
with DEBUG off, so the local demo needs no web server and no collectstatic.

The error handlers are our own because Django's defaults are wrapped in its
stock CSRF helper, which opens the session even for a visitor without a cookie.
"""

from django.conf import settings
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path

urlpatterns = [
    re_path(
        r"^%s(?P<path>.*)$" % settings.STATIC_URL.lstrip("/"),
        serve_static, {"insecure": True},
    ),
    path("", include("scans.urls")),
]

handler400 = "scans.errors.bad_request"
handler403 = "scans.errors.permission_denied"
handler404 = "scans.errors.not_found"
handler500 = "scans.errors.server_error"

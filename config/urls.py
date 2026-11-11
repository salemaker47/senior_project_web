"""
URL configuration.

MEDIA_URL is deliberately not routed: stored scans and results belong to one
visitor and are served by scans.views.scan_file, which checks the owner.

The error handlers are our own because Django's defaults are wrapped in its
stock CSRF helper, which opens the session even for a visitor without a cookie.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("scans.urls")),
]

handler400 = "scans.errors.bad_request"
handler403 = "scans.errors.permission_denied"
handler404 = "scans.errors.not_found"
handler500 = "scans.errors.server_error"

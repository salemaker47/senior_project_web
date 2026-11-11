"""
URL configuration.

MEDIA_URL is deliberately not routed: uploaded scans and results belong to one
visitor and are served (Phase 3) by a view that checks the owner.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("scans.urls")),
]

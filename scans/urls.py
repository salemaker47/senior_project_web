from django.urls import path

from . import views

app_name = "scans"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("consent/accept/", views.consent_accept, name="consent_accept"),
    path("consent/decline/", views.consent_decline, name="consent_decline"),
    path("my-data/delete/", views.delete_my_data, name="delete_my_data"),
    path("upload/", views.upload, name="upload"),
    path("scans/", views.my_scans, name="my_scans"),
    path("scans/<uuid:scan_id>/", views.result, name="result"),
    path("scans/<uuid:scan_id>/files/<slug:kind>.png", views.scan_file, name="scan_file"),
    path("scans/<uuid:scan_id>/download.zip", views.scan_zip, name="scan_zip"),
    path("scans/<uuid:scan_id>/delete/", views.delete_scan, name="delete_scan"),
]

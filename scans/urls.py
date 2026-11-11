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
    path("scans/<uuid:scan_id>/", views.result, name="result"),
]

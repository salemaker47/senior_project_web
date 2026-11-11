"""
scans/models.py

Both models are linked to the visitor by `session_key`, the key of the
anonymous session created when the visitor accepted the cookie.

What is stored about an upload: the pixel data of its slices (as an .npz file
under a random name), a display name, the detected format and the technical
metadata the loader reports (size, bit depth, rescale values). The uploaded
file itself is NOT kept, so DICOM patient tags, the FigShare patient id and
image EXIF data never reach the disk or the database.
"""

from __future__ import annotations

import uuid

from django.db import models


class Scan(models.Model):
    """One uploaded scan of one anonymous visitor."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=40, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Name shown to the visitor (basename of the upload, cleaned).
    original_name = models.CharField(max_length=255, blank=True)
    # Format found from the file content: png, jpeg, tiff, figshare_mat, brats_h5, dicom.
    detected_format = models.CharField(max_length=32, blank=True, default="")
    # Pixel data, relative to MEDIA_ROOT: scans/<scan id>/<random>.npz
    data_path = models.CharField(max_length=255, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)       # size of the upload
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    n_slices = models.PositiveIntegerField(default=1)
    # Loader metadata (format, intensity kind, dtype, rescale values). No patient tags.
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Scan {self.id}"

    @property
    def latest_prediction(self):
        return self.predictions.order_by("-created_at").first()


class Prediction(models.Model):
    """One run of one model on one scan."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Waiting"),
        (RUNNING, "Running"),
        (DONE, "Done"),
        (FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="predictions")
    session_key = models.CharField(max_length=40, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    model_key = models.CharField(max_length=200)
    fold = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)

    # Result files, relative to MEDIA_ROOT, stored under random names.
    original_path = models.CharField(max_length=255, blank=True, default="")
    mask_path = models.CharField(max_length=255, blank=True, default="")
    overlay_path = models.CharField(max_length=255, blank=True, default="")

    summary = models.JSONField(default=dict, blank=True)
    run_seconds = models.FloatField(null=True, blank=True)
    # Written for the visitor (see errors.friendly_prediction_error). Technical
    # detail is logged, never stored here.
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Prediction {self.id} ({self.status})"

    @property
    def is_done(self) -> bool:
        return self.status == self.DONE

    @property
    def is_failed(self) -> bool:
        return self.status == self.FAILED

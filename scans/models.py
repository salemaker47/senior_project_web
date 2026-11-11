"""scans/models.py"""

from __future__ import annotations

import uuid

from django.db import models


class Scan(models.Model):
    """
    One uploaded scan of one anonymous visitor.

    `owner_id` is the random id stored in the visitor's session when they
    accept the cookie (not the session key, so it can appear in file paths).
    Files of a scan live in MEDIA_ROOT/scans/<owner_id>/<scan id>/.

    Phase 2 only needs the ownership link, for "Delete my data". Phase 3 adds
    the upload and result fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    original_name = models.CharField(max_length=255, blank=True)
    model_key = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Scan {self.id}"

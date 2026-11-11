"""scans/uploadhandlers.py"""

from __future__ import annotations

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload

TOO_LARGE_ATTR = "scan_upload_too_large"


class MaxSizeUploadHandler(FileUploadHandler):
    """
    Counts the bytes of an uploaded file while it streams in and stops the
    upload once it is larger than settings.SCAN_MAX_UPLOAD_BYTES. The file is
    then missing from request.FILES and `request.scan_upload_too_large` is
    True, which the upload form turns into a clear message.

    Without this, Django would first write the whole oversized file to a
    temporary file and only then let the form reject it.
    """

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self._received = 0

    def receive_data_chunk(self, raw_data, start):
        self._received += len(raw_data)
        if self._received > settings.SCAN_MAX_UPLOAD_BYTES:
            setattr(self.request, TOO_LARGE_ATTR, True)
            raise StopUpload(connection_reset=False)
        return raw_data          # pass the chunk on to the next handler

    def file_complete(self, file_size):
        return None              # the next handler builds the file object

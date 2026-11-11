"""scans/forms.py"""

from __future__ import annotations

from django import forms

from . import services


class UploadForm(forms.Form):
    """
    One scan file and the model to run on it.

    The model choices come from the registry and are grouped by the scan type
    each model expects (T1 contrast-enhanced or FLAIR). `clean_file` checks the
    size and that the `inference` loader can parse the file; the parsed scan is
    kept on the form as `loaded_scan`.
    """

    model_key = forms.ChoiceField(
        label="Model for your scan type",
        error_messages={
            "required": "Choose the model that matches your scan type.",
            "invalid_choice": "That model is not available. Choose one from the list.",
        },
    )
    file = forms.FileField(
        label="Scan file",
        allow_empty_file=True,          # reported by parse_upload with a clearer message
        error_messages={"required": "Choose a scan file to upload."},
    )

    def __init__(self, *args, upload_too_large: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.loaded_scan = None
        self.grouped_choices = services.model_choices()
        self.fields["model_key"].choices = self.grouped_choices
        self.has_models = bool(self.grouped_choices)
        if upload_too_large:
            # The upload handler stopped the oversized file, so the field is empty.
            self.fields["file"].error_messages["required"] = services.too_large_message()

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        try:
            self.loaded_scan = services.parse_upload(uploaded)
        except services.UploadRejected as exc:
            raise forms.ValidationError(str(exc)) from exc
        return uploaded

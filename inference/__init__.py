"""
inference — framework-free brain-MRI tumor segmentation for the web app.

This package must not import Django. It is used by the Django views (Phase 3)
and by the command-line tool (`python -m inference predict ...`).

Modules
    models       build_model mirror of the training repo (src/sg_models.py)
    registry     scan model_store/, pick the best fold per model key, load + cache
    loaders      read PNG/JPEG/TIFF, FigShare .mat, BraTS .h5, DICOM -> 2D slices
    preprocess   the exact training preprocessing (copied, not re-invented)
    predictor    CPU batched inference under torch.inference_mode()
    postprocess  blob removal, native-size mask, red overlay, summary dict
    pipeline     file -> result, glueing the above together
    cli          command-line entry point
"""

import os

# Albumentations phones home to check for a newer version on import unless this
# is set. The web app must not make network calls on behalf of a visitor.
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

DISCLAIMER = "Research and education demo. Not for diagnosis."

__all__ = ["DISCLAIMER"]

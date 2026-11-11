# Progress

Tick a step and commit right after finishing it. A new session resumes at the
first unticked step of the current phase and never starts the next phase.

## Phase 0 — Scaffold

- [x] 1. Python/OS checked; `.venv` created; `requirements.txt` written and installed
- [x] 2. `git init`; `.gitignore` covers `model_store/`, `media/`, `.venv/`, `db.sqlite3`, `.env`
- [x] 3. `CLAUDE.md` written (app, locations, model facts, rules, phases)
- [x] 4. `docs/PLAN.md` and `docs/PROGRESS.md` written
- [x] 5. Empty `inference/`, `tests/`, `model_store/`, `media/` created (with `.gitkeep`)
- [x] 6. User told which files to copy into `model_store/` and how to name the folders

### Notes

- Resolved versions installed on 2026-11-11 (`.venv/bin/pip list`): Django 4.2.30,
  torch 2.8.0 (CPU, `torch.cuda.is_available() == False`),
  segmentation-models-pytorch 0.5.0 (pulls timm 1.0.30), albumentations 2.0.8,
  opencv-python-headless 5.0.0, numpy 2.0.2, pillow 11.3.0, h5py 3.14.0,
  pydicom 2.4.4 (last line for Python 3.9; pydicom 3 needs 3.10), nibabel 5.3.3,
  pytest 8.4.2, pytest-django.

- Environment: macOS (Apple Silicon), system Python 3.9 — the only interpreter on
  the machine. Django is therefore held to the 4.2 LTS line (the last that
  supports Python 3.9). Both Python 3.9 and Django 4.2 are past upstream
  support; installing Python 3.12 (e.g. via Homebrew) would allow Django 5.x.
- torch, segmentation-models-pytorch and albumentations are **unpinned**: no
  `model_store/**/experiment_config.json` existed during Phase 0. Pin them to
  `repro_metadata.lib_versions` from a real checkpoint's config once one is
  copied in (planned for Phase 5 at the latest, ideally before Phase 3).

## Phase 1 — Inference package and CLI (2D)

- [x] 1. `inference/models.py` + `inference/registry.py`: build_model mirror, model_store scan, best fold, `weights_only=True`, strict load, cache
- [x] 2. `inference/loaders.py`: content-sniffed PNG/JPEG/TIFF, FigShare `.mat`, BraTS `.h5`, single DICOM → list of 2D float slices + metadata
- [x] 3. `inference/preprocess.py`: training steps copied verbatim (percentile→uint8→resize, gray→3ch, eval transform)
- [ ] 4. `inference/predictor.py`, `inference/postprocess.py`, `inference/pipeline.py`: CPU batched inference, blob removal, native-size mask, overlay, summary
- [ ] 5. `inference/cli.py` + `__main__.py`: `python -m inference predict <file> --model <key> --out <dir>` writes `mask.png`, `overlay.png`, `summary.json`
- [ ] 6. Tests: loaders (synthetic files), preprocessing, full run with fake checkpoint, golden test (skipped when `tests/golden/` empty)
- [ ] 7. CLI run verified end to end; `docs/PROGRESS.md` updated; summary written

## Phase 2 — Django skeleton, cookie consent, anonymous sessions

- [ ] not started

## Phase 3 — Upload, predict, result page, downloads

- [ ] not started

## Phase 4 — 3D volumes (NIfTI, DICOM series)

- [ ] not started

## Phase 5 — Cleanup, README, final checks

- [ ] not started

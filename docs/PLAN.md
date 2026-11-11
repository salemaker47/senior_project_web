# Plan

One phase per session. A session finishes its phase, ticks `PROGRESS.md`, and
stops. The next session starts with `CLAUDE.md` and `PROGRESS.md`.

## Phase 0 — Scaffold (this session)

Python / OS check, `.venv`, `requirements.txt`, `git init`, `.gitignore`,
`CLAUDE.md`, `docs/`, empty `inference/`, `tests/`, `model_store/`, `media/`.
Ends by telling the user which files to copy into `model_store/`.

## Phase 1 — Inference package and command-line tool (2D formats)

- `inference/` (no Django imports): model registry over `model_store/`
  (pick the fold with the highest `best_score` per model key), model builder
  mirroring `build_model` from the training repo, preprocessing copied exactly
  from `src/preprocess_utils.py` and `src/sg_data_utils.py` (percentile clip,
  uint8, 256x256 `INTER_LINEAR`, gray→3ch, optional CLAHE, ImageNet
  normalisation), prediction (`sigmoid(logits) > threshold`), mask and overlay
  rendering.
- 2D readers: PNG/JPEG, FigShare `.mat` (HDF5 `cjdata/image`, transposed),
  BraTS `.h5` (`image[..., 3]` = FLAIR).
- CLI: `python -m inference predict <file> --model <key> --out <dir>`.
- Tests with a tiny random-weight checkpoint fixture in the real dict layout.

## Phase 2 — Django skeleton, cookie consent, anonymous sessions

- Project + one app, settings for local dev (SQLite, `media/`), base template
  with our own CSS/JS (no CDN, no build step).
- Cookie banner; nothing is stored until the visitor accepts. Anonymous session
  cookie links uploads to the browser. No accounts.
- pytest-django set up; tests for consent gating and session creation.

## Phase 3 — Upload, predict, result page, downloads

- Upload form (2D formats from Phase 1), server-side validation and size limits.
- Run inference through `inference/`, store input/mask/overlay under `media/`
  keyed by the anonymous session.
- Result page with the input, mask, overlay, model key and fold used, and the
  line "Research and education demo. Not for diagnosis." Download buttons for
  the mask PNG and overlay PNG. A "my uploads" list for the current session.

## Phase 4 — 3D volumes (NIfTI, DICOM series)

- Readers for NIfTI (`nibabel`) and DICOM series (`pydicom`), slice selection /
  per-slice prediction, slice browser on the result page, download of the
  predicted volume.

## Phase 5 — Cleanup, README, final checks

- README with setup and usage, pin the three ML libraries to the training
  versions, final test run, remove dead code, check the disclaimer on every
  result page.

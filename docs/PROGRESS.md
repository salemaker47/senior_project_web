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
- [x] 4. `inference/predictor.py`, `inference/postprocess.py`, `inference/pipeline.py`: CPU batched inference, blob removal, native-size mask, overlay, summary
- [x] 5. `inference/cli.py` + `__main__.py`: `python -m inference predict <file> --model <key> --out <dir>` writes `mask.png`, `overlay.png`, `summary.json`
- [x] 6. Tests: loaders (synthetic files), preprocessing, full run with fake checkpoint, golden test (skipped when `tests/golden/` empty)
- [x] 7. CLI run verified end to end; `docs/PROGRESS.md` updated; summary written

### Notes (Phase 1, finished 2026-11-11)

- Result: `.venv/bin/python -m pytest` gives 47 passed, 1 skipped (the golden
  test, `tests/golden/` is empty). The CLI was run on a synthetic FigShare-style
  `.mat` with a random-weight checkpoint and wrote `mask.png`, `overlay.png`
  and `summary.json`.
- **Not yet checked on real checkpoints**: `model_store/` was still empty in
  this session. `weights_only=True`, the strict load and the golden test have
  only run against the fake checkpoint. First thing to do once files are
  copied: `python -m inference list`, one `predict`, then add golden pairs
  (`tests/golden/README.md`).
- torch, segmentation-models-pytorch and albumentations are still unpinned for
  the same reason.
- 8-bit image uploads (PNG/JPEG/8-bit TIFF) skip the percentile clip, because
  the training PNGs were already 8-bit when the dataset read them; this is what
  lets a training PNG reproduce its training prediction. `.mat`, `.h5`, DICOM
  and 16-bit images get the percentile clip.
- `A.CLAHE(clip_limit=2.0)` is copied as written in the training repo.
  Albumentations reads it as the range (1.0, 2.0) and samples per call, so
  "clahe" models are slightly non-deterministic (also in the training repo's
  own evaluation). The golden test may sit close to 0.99 for such a model.
- Fold choice reads `training_meta.best_val_dice` from `experiment_config.json`
  (the same number as `best_score`) and only opens `best_model.pt` for folds
  without it.
- Blob removal runs on the model-size (256x256) mask, before the resize to the
  input size. The default of 20 pixels is therefore in model pixels.
- Extra module beyond the brief: `inference/pipeline.py` (file in, result out),
  shared by the CLI and the future Django views. Extra command:
  `python -m inference list`. `--model-store` or `$MODEL_STORE_DIR` point at
  another store.
- Multi-frame DICOM already yields several slices; the CLI saves the slice
  with the most tumor pixels unless `--slice` is given.

## Phase 2 — Django skeleton, cookie consent, anonymous sessions

- [x] 1. Django project `config` + app `scans`; settings (SQLite, `media/`, `MODEL_STORE_DIR`, upload limits, 14-day HttpOnly SameSite=Lax session cookie)
- [x] 2. Consent core: `has_consent`, `consent_required`, accept / decline / "Delete my data" views, `Scan` model, CSRF without a second cookie
- [x] 3. Pages: base template, home, about (served models, limits, disclaimer), upload and result stubs; own CSS and JS
- [x] 4. Tests: no cookie before accepting, upload blocked without consent, accepting sets the cookie, "Delete my data" clears it
- [x] 5. `python manage.py runserver` verified; `docs/PROGRESS.md` updated; summary written

### Notes (Phase 2, finished 2026-11-11)

- Result: `.venv/bin/python -m pytest` gives 82 passed, 1 skipped (golden
  test). `python manage.py runserver` was started and the whole flow was
  exercised with curl: no cookie on first visit, 403 on `/upload/`, accept sets
  `sessionid` (Max-Age 1209600, HttpOnly, SameSite=Lax), "Delete my data"
  expires it.
- First run on a new checkout: `.venv/bin/python manage.py migrate`.
- Consent lives in `scans/consent.py`. `has_consent(request)` answers "no"
  from the missing cookie alone and never opens the session; with a cookie it
  reads `cookie_consent` from the session. Templates use the `cookie_consent`
  context variable, never `request.session`.
- **One cookie only.** `CSRF_USE_SESSIONS = True` keeps the CSRF secret in the
  session, so no `csrftoken` cookie exists. Consequences to keep in mind in
  Phase 3:
  - `{% csrf_token %}` may only be rendered inside `{% if cookie_consent %}`;
    rendering it for a visitor without consent would create a session.
  - `scans.middleware.ConsentAwareCsrfViewMiddleware` overrides the private
    `_get_secret` of Django 4.2 so the session is not opened for visitors
    without a cookie. `tests/test_consent.py` fails if a Django upgrade breaks
    this.
  - The accept and decline forms carry no CSRF token (there is no session to
    hold one). They are `csrf_exempt` and guarded by `is_same_origin_post`
    (`Sec-Fetch-Site` and `Origin`).
- Decline stores nothing on the server. The redirect carries
  `?consent=declined` for a small banner, and `consent.js` notes the choice in
  the tab's `sessionStorage` so the banner stays small on later pages.
- Scans are linked to a random `owner_id` stored in the session at accept time
  (not the session key). Files go to `media/scans/<owner_id>/<scan_id>/`;
  `services.delete_owner_data` removes rows and that folder.
- `Scan` has only the ownership fields; Phase 3 adds upload and result fields
  in a new migration. `upload` and `result` are stubs behind
  `consent_required`.
- `MEDIA_URL` is not routed on purpose. Phase 3 must serve files through a
  view that checks `owner_id`.
- Settings: `MODEL_STORE_DIR` (env override), `SCAN_MAX_UPLOAD_BYTES` 32 MB
  (env override; to be enforced by the Phase 3 upload form),
  `FILE_UPLOAD_MAX_MEMORY_SIZE` 5 MB, `DATA_UPLOAD_MAX_MEMORY_SIZE` 1 MB,
  `DATA_UPLOAD_MAX_NUMBER_FILES` 1 (raise in Phase 4 for DICOM series).
  The secret key comes from `$DJANGO_SECRET_KEY` or the git-ignored
  `.secret_key`, generated on first start.
- No auth, admin or messages apps are installed (no accounts).
- Open items: scans of expired sessions are not cleaned up yet (a management
  command fits Phase 5); `SESSION_COOKIE_SECURE` is off while `DEBUG` is on
  because localhost is plain http; the about page lists models from a registry
  that is scanned once per server start.
- Still not done from Phase 1: `model_store/` is empty, so real checkpoints,
  `weights_only=True` on real files and the golden test remain unverified.

## Phase 3 — Upload, predict, result page, downloads

- [x] 1. Models `Scan` and `Prediction` (UUID keys, linked by `session_key`), migrations, 20 MB limit, upload handler
- [x] 2. Services: parse and store an upload without patient tags, `run_prediction(prediction_id)`, delete helpers
- [ ] 3. Upload form and view (model choice from the registry, labelled by scan type; size and parse validation)
- [ ] 4. Result page (original, mask, overlay with opacity slider, summary, downloads), owner-only file and zip views
- [ ] 5. "My scans" page with per-scan delete
- [ ] 6. Tests: upload with the fake checkpoint, other session gets 404, invalid and oversized files rejected
- [ ] 7. Browser flow verified on the running server; `docs/PROGRESS.md` updated; summary written

## Phase 4 — 3D volumes (NIfTI, DICOM series)

- [ ] not started

## Phase 5 — Cleanup, README, final checks

- [ ] not started

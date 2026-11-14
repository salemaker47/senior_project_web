# senior_project_web — brain-MRI tumor segmentation demo (Django)

Read this file first in every session. It replaces re-pasting the brief.

## What the app does

A Django site, on localhost for now, where a visitor uploads a brain MRI scan and
gets back the predicted tumor mask. There is no sign-up and no account. The
visitor accepts cookies, and an anonymous session cookie links their uploads to
their browser.

## Where things are

- Training repo, **read-only reference, never edit it**:
  `/Users/salemaker/Documents/code/senior_project`
  (library in `src/`, recipes in `configs/`, Colab notebooks in `notebooks/`).
- This folder (`/Users/salemaker/Documents/code/senior_project_web`) is the web
  app repo.
- Trained models go in `model_store/<model_key>/fold_<k>/best_model.pt`, with
  `experiment_config.json` beside each. `model_store/` is git-ignored.
- Machine: macOS (Apple Silicon), Python 3.9 system interpreter, no GPU. The
  virtual environment is `.venv/` (git-ignored); install with
  `.venv/bin/pip install -r requirements.txt`.

## Running it

- First time: `.venv/bin/python -m config.make_env` (creates `.env` with a
  secret key), then `.venv/bin/python manage.py migrate`
- Server: `.venv/bin/python manage.py runserver`
- Tests: `.venv/bin/python -m pytest`
- Command line: `.venv/bin/python -m inference predict <file> --model <key> --out <dir>`
- Housekeeping: `.venv/bin/python manage.py purge_old_scans --days 7`
- Settings come from `.env` (see `.env.example`). `DJANGO_DEBUG` is off by
  default; static files are still served by Django.
- Visitors never see exception text. Failures are logged through the `scans`
  logger and shown as plain sentences (`scans/errors.py`).
- Setup and usage for people: `README.md`. Limits: `docs/LIMITS.md`. Browser
  checklist: `docs/MANUAL_TEST.md`.

## Consent rules (from Phase 2, binding for later phases)

- No session and no cookie before the visitor accepts. Ask
  `scans.consent.has_consent(request)`; never read `request.session` for a
  visitor who has not accepted, in views or templates.
- Views that store or show visitor data use `@consent_required`.
- The site sets exactly one cookie. CSRF tokens live in the session, so
  `{% csrf_token %}` goes only inside `{% if cookie_consent %}`.
- Visitor data (`Scan`, `Prediction`) is keyed by the session key,
  `get_session_key(request)`. Files live under `media/scans/<scan_id>/` with
  random names and are served only by owner-checking views (404 for anyone
  else), never through `MEDIA_URL`.
- The uploaded file is never kept: only the parsed pixel data and the loader's
  technical metadata are stored. No DICOM patient tags on disk or in the
  database.
- Error pages come from `scans/errors.py`; Django's default handlers would
  open the session.

## Facts about the trained models

- `best_model.pt` is a `torch.save` dict with `state_dict` (weights, `model.`
  prefix already removed), `epoch`, `best_score` (best validation Dice) and
  `extra_meta`. `extra_meta` holds `model_name`, `encoder_weights` and
  `experiment` (the full config, including `dataset`, `preprocessing`,
  `image_size`, `threshold`). The file is already the best epoch of its fold.
- For each model, serve the fold with the highest `best_score`.
- Models are built by `build_model` in `src/sg_models.py` of the training repo
  using segmentation-models-pytorch with `in_channels=3`, `classes=1`,
  `activation=None`. For example `smp_unet_resnet34` is
  `smp.Unet(encoder_name="resnet34")` and `smp_unetpp_efficientnetb4` is
  `smp.UnetPlusPlus(encoder_name="efficientnet-b4")`. Build with
  `encoder_weights=None`.
- The model outputs logits of shape (N, 1, H, W). The mask is
  `sigmoid(logits) > threshold`.
- Training images were produced by `src/preprocess_utils.py`: 2D slice, clip to
  the 1st–99th percentile, scale to uint8, resize to 256x256 with
  `cv2.INTER_LINEAR`.
- Evaluation transform (`build_eval_transform` in `src/sg_data_utils.py`): gray
  to 3 identical channels, `A.Resize(256, 256)`, `A.CLAHE(clip_limit=2.0,
  tile_grid_size=(8, 8))` only when `preprocessing == "clahe"`, `A.Normalize`
  with ImageNet mean and std, `ToTensorV2`.
- `dataset == "figshare"` means T1 contrast-enhanced slices.
  `dataset == "brats2020"` means skull-stripped FLAIR slices.
- FigShare `.mat` files are HDF5: read `cjdata/image` and transpose it. BraTS
  `.h5` files: key `image`, shape (H, W, 4), FLAIR is channel 3.

## Rules for every phase

- One phase per session. Never start the next phase.
- Keep `docs/PROGRESS.md` as a checklist per phase. Tick each step and commit
  right after finishing it, so a new session can resume if this one is cut off.
- Small local commits. The repo is hosted on GitHub since 2026-11-14 (`origin` =
  `https://github.com/salemaker47/senior_project_web`, public). Push only when
  the owner asks; never push `.env`, `model_store/`, `media/`, the database or
  the golden test images (all git-ignored).
- The `inference/` package must not import Django.
- Copy the preprocessing from the training repo exactly; do not re-invent it.
- Tests use pytest and must pass without the real checkpoints: build a tiny
  random-weight checkpoint with the same dict layout in a fixture.
- Plain Django templates with our own CSS and JavaScript. No CDN, no build step.
- Every page that shows a result carries:
  "Research and education demo. Not for diagnosis."
- If an instruction conflicts with what you find, stop and ask.

## Phases (details in docs/PLAN.md, status in docs/PROGRESS.md)

0. Repo scaffold: venv, requirements, git, this file, docs, empty packages.
1. Inference package and command-line tool (2D formats).
2. Django skeleton, cookie consent, anonymous sessions.
3. Upload, predict, result page, downloads.
4. 3D volumes (NIfTI, DICOM series).
5. Cleanup, README, final checks.

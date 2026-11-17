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
- [x] 3. Upload form and view (model choice from the registry, labelled by scan type; size and parse validation)
- [x] 4. Result page (original, mask, overlay with opacity slider, summary, downloads), owner-only file and zip views
- [x] 5. "My scans" page with per-scan delete
- [x] 6. Tests: upload with the fake checkpoint, other session gets 404, invalid and oversized files rejected
- [x] 7. Browser flow verified on the running server; `docs/PROGRESS.md` updated; summary written

### Notes (Phase 3, finished 2026-11-11)

- Result: `.venv/bin/python -m pytest` gives 110 passed, 1 skipped (golden
  test). The flow was run on `runserver` with a random-weight checkpoint
  (`MODEL_STORE_DIR` pointed at a fake store): accept cookie, upload a PNG,
  result page, mask download, zip download, my scans, delete. Pages were
  checked in headless Chrome, including the opacity slider.
- **Not yet run with real checkpoints**: `model_store/` is still empty. After
  copying models: `python manage.py migrate`, `runserver`, upload a real slice.
- After pulling this phase run `python manage.py migrate` (migrations 0002 and
  0003).
- Changed from Phase 2, as the Phase 3 brief asked:
  - `Scan` and `Prediction` are linked to the visitor by `session_key`. The
    separate random `owner_id` in the session is gone;
    `consent.get_session_key(request)` replaces `get_owner_id`.
  - `SCAN_MAX_UPLOAD_BYTES` is 20 MB (was 32 MB).
- **The uploaded file is not kept.** It is parsed by the `inference` loader and
  only the pixel data is stored (`scans/<scan id>/<random>.npz`), with the
  loader's technical metadata in `Scan.meta`. This is how "do not store DICOM
  patient tags" is met on disk as well as in the database; it also drops the
  FigShare patient id and image EXIF data. The zip therefore holds
  `original.png` (the 8-bit slice), `mask.png`, `overlay.png`, `summary.json`
  and a README, not the original upload.
- Files: `media/scans/<scan id>/<32 hex>.npz|png`. They are served only by
  `views.scan_file` and `views.scan_zip`, which return 404 unless the request's
  session owns the scan (also 404 without a session, without opening one).
- `services.run_prediction(prediction_id)` does the whole job and records a
  failure on the row instead of raising. The upload view calls it directly.
  A scan can have several predictions; the pages show the latest.
- Upload validation: size (stream stopped by `MaxSizeUploadHandler`, checked
  again in `parse_upload`), format from content, decode, at least 8x8 pixels,
  at most `SCAN_MAX_PIXELS` (4096x4096), finite values. Rejected uploads leave
  no row and no file.
- A multi-frame DICOM is accepted; the slice with the most predicted tumor
  pixels is shown. Browsing slices is Phase 4.
- Own error pages (`scans/errors.py`, `templates/error.html`, `500.html`):
  Django's default handlers open the session through its stock CSRF helper,
  which broke the "never open the session before consent" rule on 404 pages.
- The overlay slider paints the mask on a canvas above the original; without
  JavaScript the server-rendered `overlay.png` is shown.
- Open items for Phase 5: cleanup of scans whose session expired; the
  prediction runs inside the request (a few seconds on CPU, first request also
  loads the model); pin the three ML libraries; golden test with real files.

## Phase 4 — 3D volumes (NIfTI, DICOM series)

- [ ] not started

## Phase 5 — Cleanup, README, final checks

- [x] 1. `.env` and committed `.env.example` for the secret key and debug flag; static files served with debug off
- [x] 2. Friendly error pages and failed-prediction messages; no stack traces or internal details shown to visitors
- [x] 3. Management command `purge_old_scans --days 7` (old scans, files, expired sessions)
- [x] 4. `README.md`: setup, model files, running the site, tests, command-line tool
- [x] 5. `docs/MANUAL_TEST.md` and `docs/LIMITS.md`
- [x] 6. Full test suite green; fresh clone set up and run by following the README
- [x] 7. `docs/PROGRESS.md` updated; final summary written

### Notes (Phase 5, finished 2026-11-11)

- Result: `.venv/bin/python -m pytest` gives 127 passed, 1 skipped (golden
  test).
- Fresh-clone check: the repo was cloned into a scratch folder and the README
  was followed: `config.make_env`, `migrate`, `pytest` (127 passed, 1 skipped),
  `inference list`, `runserver` with the default `.env` (debug off),
  accept cookie, upload, mask download, delete my data, `inference predict`,
  `purge_old_scans --dry-run`. The package install was done from the same
  `requirements.txt` into a fresh venv in a separate folder and linked in; it
  resolved to exactly the versions of the working venv.
- Phase 4 (3D volumes) was not built. Phase 5 was requested directly after
  Phase 3. NIfTI and DICOM series are listed as unsupported in
  `docs/LIMITS.md`.
- `.env`: `DJANGO_SECRET_KEY` (required) and `DJANGO_DEBUG` (default False),
  plus optional overrides. `python -m config.make_env` creates it from
  `.env.example`. The Phase 2 `.secret_key` file is gone. Without a key the
  settings stop with a message that names the command.
- With debug off Django would not serve static files, so `config/urls.py`
  serves them itself. No `collectstatic` and no extra package.
- `DJANGO_SECURE_COOKIES` replaces "secure when debug is off": the demo runs
  over http on localhost, where Safari drops Secure cookies.
- Visitors never see exception text: `Prediction.error_message` holds one of
  four plain sentences (`scans/errors.py`), upload rejections use fixed
  wording per format, the CSRF failure page and the 400/403/404/500 pages are
  our own. Tracebacks and library messages go to the `scans` logger (console).
- `purge_old_scans --days N [--dry-run]` removes expired sessions, scans older
  than N days, scans whose session no longer exists, and stray folders under
  `media/scans/` older than one hour. Nothing schedules it.
- `requirements.lock.txt` records the tested versions. The three ML libraries
  are still not pinned to the training versions.

### Still open after Phase 5

- `model_store/` has been empty in every session. Never done with real files:
  loading a real checkpoint (`weights_only=True`, strict load), a real
  prediction in the browser, and the golden test. `docs/MANUAL_TEST.md` is the
  checklist for this.
- Pin `torch`, `segmentation-models-pytorch` and `albumentations` to
  `repro_metadata.lib_versions` once an `experiment_config.json` is available.
- Phase 4 (3D volumes) if wanted.
- Python 3.9 and Django 4.2 are past upstream support; Python 3.12 would allow
  Django 5.

## After Phase 5 — first real model (2026-11-12)

Not a phase of the plan; recorded so the next session knows the state.

- Model `01_dice_image_level` (U-Net ResNet34, Dice loss, FigShare,
  image-level split, folds 1-5) was trained on the MacBook GPU with the
  training repo's own notebook code, on FigShare data rebuilt locally from the
  public download. Copied into `model_store/01_dice_image_level/fold_1..5/`
  (`best_model.pt` + `experiment_config.json`; `best.ckpt` left out).
- Fold 1 is served (best validation Dice 0.8550). Test Dice over the five
  folds: 0.851 ± 0.005.
- Checked: `weights_only=True` loads the real file, it holds no `loss_fn.*`
  keys, the strict load works. Golden test with six fold-1 test slices (two per
  tumour class), reference masks made with the training repo's
  `BrainTumorDataset` + `build_eval_transform` + `load_model_from_pt` on CPU:
  pixel-identical. Raw `.mat` uploads give the same masks as the PNGs.
  Site run end to end with a PNG and a `.mat` upload; test data deleted after.
- Full suite: 133 passed (the golden test now runs on this machine).
- `requirements.txt` pins torch 2.8.0, segmentation-models-pytorch 0.5.0 and
  albumentations 2.0.8, the versions in this model's
  `repro_metadata.lib_versions`.
- Golden pair folders (`tests/golden/*/`) are git-ignored.
- Demo files for the browser: `Senior_Project_local/demo_uploads/` (six fold-1
  test slices with ground truth, three raw `.mat` files).
- Still open: the Colab-trained models (other library versions), any BraTS /
  FLAIR model, Phase 4.

## GitHub (2026-11-14)

- Pushed `main` to `https://github.com/salemaker47/senior_project_web` (public)
  at the owner's request. This replaces the earlier "no remote, no push" rule;
  `CLAUDE.md` now says: push only when the owner asks.
- Checked before publishing: no secrets, `.env`, database, uploads, model files
  or golden images in the history. GitHub holds the code only; the trained
  model must be copied into `model_store/` after a clone (see README).

## Hosting on Hugging Face Spaces (2026-11-14)

- Added at the owner's request ("free cloud option"): `deploy/huggingface/`
  with `Dockerfile`, Space `README.md`, `start.sh`, `install_model.py` and the
  guide `HOSTING.md`. The Space holds only those two files plus the model
  files; the image clones the code from GitHub.
- App changes, all off by default: `DJANGO_BEHIND_PROXY`,
  `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_FRAME_ANCESTORS`;
  `FrameAncestorsMiddleware` replaces Django's X-Frame-Options middleware (same
  DENY by default); the consent origin check compares hosts, not schemes, and
  accepts trusted origins; `frame.js` shows an "open in its own tab" notice
  when the site is framed (cookies do not work in the Hugging Face page);
  `gunicorn` added to the requirements.
- Tested locally without Docker: clean copy of the code, model install step,
  `start.sh`, gunicorn, proxied requests with and without `X-Forwarded-Proto`
  and with an internal Host header, forged origin refused, framed notice
  checked in headless Chrome. Suite: 150 passed.
- **Not tested:** building the Docker image and running on Hugging Face. The
  first build there is the first test of the Dockerfile.
- The owner still has to: push, create the Space, upload the four files
  (prepared in `Senior_Project_local/hf_space_upload/`).

## Sharing from the owner's computer through a tunnel (2026-11-16)

Not a phase of the plan. The owner chose this after Hugging Face turned out to
charge for Docker Spaces (see the correction in `deploy/huggingface/HOSTING.md`),
and asked for it to be safe for the computer, with several layers of protection.

- [x] 1. App layers, all off by default: request firewall (`scans/firewall.py`), access code, strict content policy, upload format allow-list, separate database and upload folder
- [x] 2. Launcher `deploy/tunnel/share.py` with sandbox profiles for the server and the tunnel; `cloudflared` installed with Homebrew
- [x] 3. Tests (194 passed) and a live test through a real public link
- [x] 4. Second live run after the launcher fix (it must not look up the new address early)
- [x] 5. Pages checked in a real browser under the strict content policy
- [x] 6. Docs: `deploy/tunnel/SHARING.md`, README, LIMITS, CLAUDE.md; correct the Hugging Face guide
- [x] 7. `docs/PROGRESS.md` notes; summary written

### Notes

- Result: `.venv/bin/python -m pytest` gives 194 passed.
- Hugging Face: the owner created a Space, but a free account cannot run a
  Docker Space any more (confirmed in Hugging Face's docs and forum, see the
  correction at the top of `deploy/huggingface/HOSTING.md`). The uploaded
  files are still in the Space `salemaker/brain-mri-demo`, which never built;
  it can be deleted.
- Live tests, two sessions through real `trycloudflare.com` links: access code
  required (401 without, 200 with), scanner paths 404, DELETE 405, consent,
  upload, mask download over HTTPS, `.mat` refused, result invisible without
  the owner's session, ban after eight refusals (the right code then gets 429),
  clean stop (link dead, upload and database deleted, no process left).
- Sandbox, checked with a probe program and by a test: listing the home
  folder, reading `.env`, writing into the code, internet access and starting
  a shell are blocked; reading the code, writing `share_data/` and listening
  on 127.0.0.1 are allowed. The real server (model load, prediction) runs
  inside it.
- Found and fixed during the live test:
  - the tunnel program needs to listen on 127.0.0.1 for its status endpoint;
  - looking up the new address right away made macOS cache "not found", so the
    link failed on this Mac only. The launcher now waits for the tunnel's
    "Registered tunnel connection" message and never resolves the name.
- Pages were loaded in headless Chrome under the content policy (home and
  about through the real link; result and upload from a saved copy served
  with the same header): no violations, overlay slider works.
- Also changed: `templates/500.html` uses the site stylesheet (no inline
  style); `/robots.txt` disallows everything; `config.env.load_env_file`
  tolerates an unreadable `.env`.
- For the owner to do: turn on the macOS firewall (it is off; steps in
  `SHARING.md`). Not changed from here because it needs the admin password.
- Not pushed. `git push` when the owner wants GitHub to have it.

## Cleanup of unused code (2026-11-17)

Not a phase of the plan. The owner asked for a review of everything written so
far and for unnecessary and unused parts to be deleted.

- [x] 1. Small leftovers: `config/asgi.py`, `ModelRegistry.clear_cache`, `InferenceResult.scan_meta`, the launcher's `current_share.txt`, settings that restated Django defaults or were never read (`MEDIA_URL`, `STATIC_ROOT`), `nibabel` from the requirements
- [x] 2. Hugging Face deployment and the framing code that only it needed
- [x] 3. Docs brought in line; full test run; notes below

### Notes

- Method: `pyflakes` and `vulture` over all Python, a script that lists every
  definition never referenced outside tests, and checks for unused CSS classes,
  JavaScript functions, static files, template variables and settings. Then a
  read-through of `scans/`, `inference/`, the settings and the launcher.
- Result: the code was already lean. Besides step 1, the only sizeable unused
  part was the Hugging Face deployment: it needs a paid plan and never ran.
  Removed with it: `DJANGO_FRAME_ANCESTORS`, `frame.js`, the "open in its own
  tab" notice and its CSS, and eight tests. The headers middleware is now
  `SecurityHeadersMiddleware` and always sends `frame-ancestors 'none'`.
  `tests/test_hosting.py` became `tests/test_proxy.py` (same proxy and origin
  tests, with the tunnel's host name). To restore the deployment:
  `git revert d9bd82c`.
- The sections above about Hugging Face are history; the files they name no
  longer exist.
- `.venv/bin/python -m pytest` gives 186 passed (194 before, minus the eight
  removed tests). A one-minute live sharing session after the cleanup: 401
  without the code, 200 with it, scanner path 404, headers as expected, clean
  stop.
- `nibabel` is no longer in the requirements. Phase 4 (3D volumes) has to add
  it back.
- Also cleaned outside this repository: three unused items in the training
  repository (branch `fix/review-findings`, commit `d58bc57`, 75 tests pass),
  and `Senior_Project_local/hf_space_upload/` moved to the Trash (its model
  file is identical to `model_store/01_dice_image_level/fold_1/`).
- Planned, not built: a permanent `github.io` address that forwards visitors
  to the current tunnel link. Written into `docs/PLAN.md` as Phases 6 to 8.
- Not pushed.

## Phase 6 — Front-door page for the `github.io` address

- [x] 1. `deploy/pages/`: `index.html`, `door.css`, `door.js`, `status.example.json`; `status.json` there is git-ignored
- [x] 2. Tests in `tests/test_pages.py`
- [x] 3. Browser check, served locally: no status file, future time, past time, foreign address; forwarding
- [x] 4. The checks added to `docs/MANUAL_TEST.md`
- [x] 5. Notes below; summary written

### Notes

- Result: `.venv/bin/python -m pytest` gives 195 passed (186 before, plus 9 in
  `tests/test_pages.py`). One of the new tests runs `decide()` from `door.js`
  in headless Chrome with 30 status values and is skipped where Chrome is not
  installed. Breaking the address check on purpose made that test fail.
- Nothing is published: no branch was created, nothing was pushed, GitHub
  Pages is not switched on.
- The page forwards only when all of this holds: `online` is the value true,
  `url` is `https://<name>.trycloudflare.com` with nothing before or after
  (the launcher's own pattern, anchored; a test keeps them equal), and `until`
  is a time in the future.
- Added beyond the plan, for Phase 7 to respect:
  - times must be written exactly as `YYYY-MM-DDTHH:MM:SSZ` (UTC);
  - a stop time more than 13 hours away is not believed (a session lasts 12
    hours at most), so a wrong or tampered file cannot show "online" for long;
  - a "Stay on this page" button stops the automatic forwarding;
  - the forwarding replaces the page in the browser history, so "Back" from
    the demo does not bounce the visitor forward again;
  - the page carries its own content policy (only its own files load) and
    asks search engines not to index it.
- Browser check in headless Chrome against a local file server on 127.0.0.1,
  with outside name lookups switched off: no file, broken file, stopped, past
  time and foreign address all show "offline"; a future time shows "online"
  with the countdown and then leaves for the address; "Stay on this page"
  keeps the page; a page that first sees "offline" forwards after the status
  turns "online" at the next 30-second check. Looked at screenshots at desktop
  and phone width, light mode. Dark mode and other browsers were not looked at.
- Not checked: the page under its real address (`/senior_project_web/` on
  `github.io`). All paths are relative, so the folder name should not matter;
  Phase 8 confirms it.
- Not pushed.

## Phase 7 — Launcher option `--publish`

- [ ] not started (steps in `docs/PLAN.md`)

## Phase 8 — Go live, measure, document

- [ ] not started (steps in `docs/PLAN.md`; needs the owner for the pushes)

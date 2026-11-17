# Brain MRI tumor segmentation demo

A small Django site that runs on your own machine. A visitor uploads one brain
MRI slice, picks a model, and gets back the predicted tumor mask, an overlay
and a short summary. There are no accounts. One session cookie, set only after
the visitor accepts it, links uploads to their browser.

**Research and education demo. Not for diagnosis.**

The models come from the training repository (`senior_project`). This
repository only serves them.

- Known limits of the models and the app: [docs/LIMITS.md](docs/LIMITS.md)
- Browser checklist: [docs/MANUAL_TEST.md](docs/MANUAL_TEST.md)

## What you need

- Python 3.9 or newer (developed and tested on Python 3.9, macOS, Apple Silicon)
- About 1.5 GB of disk space for the Python packages (PyTorch is the large one)
- No GPU. Everything runs on the CPU.
- The trained model files (see "Model files" below). The site starts without
  them, but it cannot predict anything.

## Setup

Run these from the repository folder.

```
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m config.make_env
.venv/bin/python manage.py migrate
```

What the last two do:

- `config.make_env` creates `.env` from `.env.example` and fills in a new
  secret key. `.env` is git-ignored. Run it once; it never overwrites an
  existing `.env`.
- `migrate` creates the SQLite database `db.sqlite3`.

On Windows use `.venv\Scripts\python` in place of `.venv/bin/python`. Windows
has not been tested.

If `pip install -r requirements.txt` picks package versions that do not work
together in the future, install the exact versions the project was tested with:

```
.venv/bin/pip install -r requirements.lock.txt
```

## Model files

Trained models are not in git. Copy them from the training outputs on Drive
into `model_store/`:

```
Drive:  outputs/checkpoints/segmentation/<dataset>/<experiment_name>/fold_<k>/best_model.pt
Drive:  outputs/checkpoints/segmentation/<dataset>/<experiment_name>/fold_<k>/experiment_config.json

Here:   model_store/<model_key>/fold_<k>/best_model.pt
Here:   model_store/<model_key>/fold_<k>/experiment_config.json
```

Rules:

- `<model_key>` is a folder name of your choice. Use the experiment name, for
  example `07_unetpp_effb4_dicebce_image_level`. If you copy the same
  experiment for both datasets, give them different names, for example by
  adding `_figshare` or `_brats2020`.
- `fold_<k>` keeps its name from Drive (`fold_1` to `fold_5`). Copy every fold
  you have. The site serves the fold with the highest validation Dice.
- Only those two files are needed. Do not copy `best.ckpt`.

Check what the site will serve:

```
.venv/bin/python -m inference list
```

It prints one block per model: label, scan type, the fold it chose and its
score. With an empty `model_store/` it prints "no models found". Restart the
site after adding or changing models.

The three machine-learning packages (`torch`, `segmentation-models-pytorch`,
`albumentations`) are pinned to the versions the served model
`01_dice_image_level` was trained with. Every model records its own versions in
`experiment_config.json` under `repro_metadata.lib_versions`. If a model
trained with other versions fails to load, install that model's versions.

## Run the site

```
.venv/bin/python manage.py runserver
```

Open http://127.0.0.1:8000/. Accept the cookie, choose "Upload", pick a model
and a file. The first prediction after a start takes a few seconds longer
because the model is loaded.

Accepted files, recognised from their content: PNG, JPEG, TIFF, FigShare
`.mat`, BraTS 2020 slice `.h5`, and a single uncompressed DICOM file. The
limit is 20 MB.

This is Django's development server. It is meant for a demo on your own
machine, not for the open internet.

## Hosting it for other devices

GitHub only stores this code; it cannot run the site. One command opens a
temporary public link to the site running on your Mac, protected by an access
code, a request firewall and a sandbox. It is free and works while the command
runs. Guide: [deploy/tunnel/SHARING.md](deploy/tunnel/SHARING.md).

```
.venv/bin/python deploy/tunnel/share.py
```

A permanent address that forwards to the current link is being built: the
front-door page is in `deploy/pages/` and the launcher has the option
`--publish`, but GitHub Pages is not switched on yet (see the guide).

## Tests

```
.venv/bin/python -m pytest
```

The tests need no model files. They build a small checkpoint with random
weights in the same layout as the real ones. Expect about ten seconds and one
or two skipped tests:

- The golden test compares the site's output with masks predicted in the
  training repository. It runs once you add real files, as described in
  [tests/golden/README.md](tests/golden/README.md).
- One test of the front-door page (`deploy/pages/`) runs its script in Chrome
  and is skipped where Chrome is not installed.

On the development machine both run, and the count is 217 passed with none
skipped.

## Command-line tool

The same code that the site uses, without the site:

```
.venv/bin/python -m inference list
.venv/bin/python -m inference predict <file> --model <model_key> --out <folder>
```

`predict` writes `mask.png`, `overlay.png` and `summary.json` into the folder.
Useful options: `--min-blob-pixels 0` keeps even the smallest predicted blobs
(the default removes blobs under 20 pixels), `--slice N` picks a frame of a
multi-frame DICOM, and `--model-store <folder>` (before `predict`) reads models
from another folder.

## Housekeeping

Scans stay on disk until the visitor deletes them. To remove old ones:

```
.venv/bin/python manage.py purge_old_scans --days 7
```

This deletes scans older than seven days with their files, scans whose session
no longer exists, leftover folders, and expired sessions. Add `--dry-run` to
see the counts without deleting anything.

## Settings

Settings live in `.env`. Variables set in the shell take precedence.

| Variable | Default | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY` | none, required | Signs the session data. Created by `config.make_env`. |
| `DJANGO_DEBUG` | `False` | `True` shows Django's debug pages with stack traces. Use only while developing. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Host names the site answers to. |
| `DJANGO_SECURE_COOKIES` | `False` | Send the session cookie over HTTPS only. |
| `MODEL_STORE_DIR` | `model_store` | Folder with the model files. |
| `SCAN_MAX_UPLOAD_BYTES` | `20971520` | Largest upload in bytes. |
| `DJANGO_BEHIND_PROXY` | `False` | Trust the `X-Forwarded-Proto` header of an HTTPS proxy. Set by the sharing launcher. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Extra origins allowed to post forms. Set by the sharing launcher. |
| `DJANGO_REQUEST_FIREWALL` | `False` | Rate limits, bans and scanner-path refusal. Set by the sharing launcher. |
| `DEMO_ACCESS_PASSWORD` | empty | Access code for the whole site. Set by the sharing launcher. |
| `SCAN_ALLOWED_FORMATS` | empty (all) | Upload formats, e.g. `png,jpeg`. Set by the sharing launcher. |

## What is stored about a visitor

- Nothing, until the visitor accepts the cookie. No session, no cookie.
- After accepting: one session cookie (14 days, HttpOnly, SameSite=Lax).
- For each upload: the pixel data of the slice, the result images, a display
  name and technical metadata. The uploaded file itself is discarded after it
  is read, so DICOM patient tags are never kept.
- Files are stored under random names in `media/` and are only served to the
  browser that uploaded them. Everyone else gets "page not found".
- "Delete my data" in the page footer removes all of it at once.

## Layout

```
config/       Django project: settings, URLs, .env handling
scans/        the web app: consent, upload, results, my scans, error pages
inference/    model loading and prediction; does not import Django
templates/    base template and error pages
tests/        pytest suite; tests/golden/ for real reference masks
docs/         PLAN.md, PROGRESS.md, LIMITS.md, MANUAL_TEST.md
deploy/       sharing from this computer through a temporary public link (tunnel/);
              front-door page for a permanent address, not published yet (pages/)
model_store/  trained models (git-ignored)
media/        uploaded pixel data and results (git-ignored)
```

`CLAUDE.md` holds the project brief and the rules the code follows.

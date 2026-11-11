# Progress

Tick a step and commit right after finishing it. A new session resumes at the
first unticked step of the current phase and never starts the next phase.

## Phase 0 — Scaffold

- [ ] 1. Python/OS checked; `.venv` created; `requirements.txt` written and installed
- [x] 2. `git init`; `.gitignore` covers `model_store/`, `media/`, `.venv/`, `db.sqlite3`, `.env`
- [x] 3. `CLAUDE.md` written (app, locations, model facts, rules, phases)
- [x] 4. `docs/PLAN.md` and `docs/PROGRESS.md` written
- [x] 5. Empty `inference/`, `tests/`, `model_store/`, `media/` created (with `.gitkeep`)
- [ ] 6. User told which files to copy into `model_store/` and how to name the folders

### Notes

- Environment: macOS (Apple Silicon), system Python 3.9 — the only interpreter on
  the machine. Django is therefore held to the 4.2 LTS line (the last that
  supports Python 3.9). Both Python 3.9 and Django 4.2 are past upstream
  support; installing Python 3.12 (e.g. via Homebrew) would allow Django 5.x.
- torch, segmentation-models-pytorch and albumentations are **unpinned**: no
  `model_store/**/experiment_config.json` existed during Phase 0. Pin them to
  `repro_metadata.lib_versions` from a real checkpoint's config once one is
  copied in (planned for Phase 5 at the latest, ideally before Phase 3).

## Phase 1 — Inference package and CLI (2D)

- [ ] not started

## Phase 2 — Django skeleton, cookie consent, anonymous sessions

- [ ] not started

## Phase 3 — Upload, predict, result page, downloads

- [ ] not started

## Phase 4 — 3D volumes (NIfTI, DICOM series)

- [ ] not started

## Phase 5 — Cleanup, README, final checks

- [ ] not started

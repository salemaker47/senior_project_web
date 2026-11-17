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

Status: not built. Phase 5 was done directly after Phase 3 at the owner's
request. `docs/LIMITS.md` lists 3D input as unsupported.

- Add `nibabel` back to the requirements (removed on 2026-11-17 as unused).
- Readers for NIfTI (`nibabel`) and DICOM series (`pydicom`), slice selection /
  per-slice prediction, slice browser on the result page, download of the
  predicted volume.

## Phase 5 — Cleanup, README, final checks

- README with setup and usage, pin the three ML libraries to the training
  versions, final test run, remove dead code, check the disclaimer on every
  result page.
- As built: friendly error pages and messages, `purge_old_scans`, `.env` for
  the secret key and debug flag, `README.md`, `docs/MANUAL_TEST.md`,
  `docs/LIMITS.md`. The three ML libraries could not be pinned to the training
  versions because no real `experiment_config.json` was available;
  `requirements.lock.txt` records the versions the project was tested with.

## Phases 6 to 8 — A permanent `github.io` address for the shared demo

Planned on 2026-11-17 at the owner's request. Goal: one address that never
changes, `https://salemaker47.github.io/senior_project_web/`, which sends
visitors to the laptop's current sharing link while the laptop is sharing and
says "offline" otherwise.

How it works: GitHub Pages serves only static files and its address cannot be
pointed at the laptop, so the page is a front door, not the site. The sharing
launcher (`deploy/tunnel/share.py`) writes the current link into a small
`status.json` on a `gh-pages` branch; the front-door page reads that file and
forwards the visitor.

Order: 6, then 7, then 8. Each needs the one before. Phase 4 is independent.

Rules for all three phases:

- The access code is never published: not in the page, not in `status.json`,
  not in a commit.
- Publishing is off unless the owner starts the launcher with `--publish`.
- The site is never shown inside the front-door page (the session cookie does
  not work in a frame). The page forwards; the address bar then shows the
  `trycloudflare.com` link.
- The sandboxes and the request firewall are not weakened. Only the launcher
  itself, which runs outside the sandboxes, talks to GitHub.
- The launcher never touches the `main` branch or the working files.

### Phase 6 — Front-door page (nothing is published yet)

1. `deploy/pages/` with `index.html`, `door.css`, `door.js` and
   `status.example.json`. Plain files: no CDN, no inline script or style,
   relative paths only (the page lives under `/senior_project_web/`).
2. Format of `status.json`:
   `{"online": true, "url": "https://<name>.trycloudflare.com", "until": "<UTC time>", "updated": "<UTC time>"}`.
3. Page behaviour, decided by one pure function in `door.js`:
   - **Online** (`online` is true, `until` is in the future, and `url` is an
     `https` address directly under `trycloudflare.com`): shows that the demo
     is online, a button, a note that the owner gives out the access code, and
     forwards after a few seconds.
   - **Offline** (everything else: no file, unreadable file, time passed,
     any other address): says the demo is offline and checks again every
     30 seconds.
   - Reads the file as `status.json?t=<now>` so an old copy is not reused.
   - A `<noscript>` line, and "Research and education demo. Not for diagnosis."
4. Tests (pytest): the files exist; no inline script or style and no outside
   address in them; the disclaimer is there; the address pattern in `door.js`
   accepts what the launcher's `TUNNEL_URL_RE` accepts and nothing else.
5. Browser check with `python -m http.server` in `deploy/pages/`: no status
   file, a status with a future time, a status with a past time, a status with
   a foreign address. Add the four checks to `docs/MANUAL_TEST.md`.

Done when the page shows the right state in all four cases, served locally.

### Phase 7 — Launcher option `--publish` (tested against a local stand-in)

1. `deploy/tunnel/publish.py`, standard library only:
   - `build_status(online, url, until)` returns the dictionary of Phase 6.
     As built in Phase 6, the page believes a status only if both times are
     written exactly as `YYYY-MM-DDTHH:MM:SSZ` (UTC) and the stop time is at
     most 13 hours away; a test must tie the launcher's output to that.
   - `publish(status, ...)` keeps its own checkout of the `gh-pages` branch in
     `share_data/pages/`, creates the branch if the remote has none, copies
     `deploy/pages/` into it, writes `status.json`, commits and pushes.
   - Git runs with a time limit and without asking questions, so a missing
     login fails quickly with a clear message.
2. `share.py`: option `--publish`. It is refused together with `--open`. It
   publishes "online" once the tunnel is registered and "offline" when the
   session stops. A failed push is a warning; sharing continues. The launcher
   prints the permanent address.
3. Sandbox: check whether the sandboxed server can reach the macOS Keychain,
   where the GitHub login is stored. If it can, deny that in the server's
   profile and add the case to the probe test.
4. Tests, with a local bare repository as the remote: first publish creates
   the branch with page and status; a second one changes only the status;
   "offline" is published on stop; `--open --publish` is refused; a failing
   push does not stop the session; the status never contains the access code;
   the remote's `main` is untouched.
5. `CLAUDE.md`: the push rule becomes "the launcher pushes to `gh-pages` when
   the owner runs it with `--publish`; nothing else is pushed without being
   asked".

Done when the tests pass and a rehearsal against a local bare repository shows
an "online" commit followed by an "offline" commit. Nothing is pushed to
GitHub in this phase.

As built: the branch holds a single commit that each publish replaces (a
forced push, guarded: the branch name is fixed, and a branch holding other
files is left alone). So the rehearsal shows "online" and then "offline" as
the content of that one commit, and GitHub keeps no history of sessions. The
launcher also has `--publish-remote`, to publish to a stand-in repository.

### Phase 8 — Go live, measure, document

Needs the owner: pushing uses the owner's GitHub login, which works in the
VS Code terminal and not in the assistant's shell.

1. Owner: `git push` (so GitHub has Phases 6 and 7), then
   `.venv/bin/python deploy/tunnel/share.py --publish` once. This creates the
   `gh-pages` branch on GitHub.
2. Owner: on GitHub open the repository's Settings, Pages, choose "Deploy from
   a branch", branch `gh-pages`, folder `/ (root)`.
3. Live checks from a second device on another network (a phone on mobile
   data): the permanent address forwards to the demo; the access code is asked;
   an upload works; after Ctrl+C the page says offline; with `--hours` set
   very short, a session that ends by itself is shown as offline too.
4. Measure how long GitHub takes to show a status change and write it down.
5. Docs: `deploy/tunnel/SHARING.md` (the permanent address, `--publish`, what
   becomes public), `README.md`, `docs/LIMITS.md`, `docs/MANUAL_TEST.md`.

Done when the permanent address opens the demo from another device while the
laptop is sharing, and shows "offline" after the session stops.

Known limits to write into `docs/LIMITS.md` in Phase 8: the address bar shows
the `trycloudflare.com` link after forwarding; GitHub needs about a minute to
show a status change (soft limit of 10 page builds per hour, two per session);
the status file is public, so anyone can see when the laptop is sharing and the
current link, and the access code is the only gate.

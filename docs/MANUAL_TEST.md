# Manual test in the browser

About ten minutes. Needs at least one model in `model_store/` (see the README)
and a brain MRI slice that matches it, for example a PNG from
`data/<dataset>/processed/images/` of the training data.

Start the site with `.venv/bin/python manage.py runserver` and open
http://127.0.0.1:8000/ in a fresh private window. Keep the browser's developer
tools open on the cookie list (Chrome: Application, Cookies).

## Before accepting

- [ ] The home page shows the cookie banner with "Accept cookie" and "Decline".
- [ ] The cookie list is empty.
- [ ] "Upload a scan" is greyed out, with a sentence that explains why.
- [ ] The about page opens and lists your models with scan type, fold and score.
- [ ] Opening `/upload/` by typing the address shows "This page needs the session cookie".
- [ ] The cookie list is still empty.

## Decline

- [ ] Click "Decline". The banner shrinks to one line and the cookie list stays empty.
- [ ] Home and about still open. Upload is still greyed out.

## Accept

- [ ] Click "Accept cookie". The banner disappears.
- [ ] The cookie list shows exactly one cookie, `sessionid`, marked HttpOnly, SameSite Lax, expiring in 14 days.
- [ ] The menu now shows "Upload" and "My scans", and the footer shows "Delete my data".

## Upload and result

- [ ] On "Upload", models are grouped under "T1 contrast-enhanced scans" and "FLAIR scans".
- [ ] Choose the model that matches your slice, choose the file, click "Predict tumor mask". The button shows "Predicting…".
- [ ] The result page shows three images: original, predicted mask, overlay.
- [ ] The mask sits on the tumor. (With real weights. If it is far off, check that the scan type matches the model.)
- [ ] The opacity slider fades the red overlay from invisible (0%) to solid (100%).
- [ ] The summary shows tumor pixels, share of the image, run time, model, fold and threshold.
- [ ] "Research and education demo. Not for diagnosis." is on the page.
- [ ] "Mask (PNG)" downloads `mask.png`: white tumor on black, same size as your image.
- [ ] "Overlay (PNG)" downloads `overlay.png`.
- [ ] "Everything (ZIP)" downloads a zip with `original.png`, `mask.png`, `overlay.png`, `summary.json` and `README.txt`.

## Rejected files

- [ ] Upload a text file renamed to `scan.png`. The form says it is not a scan the site can read. No stack trace.
- [ ] Choose a file larger than 20 MB. The form says the limit is 20 MB and does not send it.
- [ ] Submit without a file. The form asks for a file.

## Ownership

- [ ] Copy the address of your result page. Open it in a different browser (private windows of one browser share their cookies): it shows the cookie page, and after accepting there, "Page not found".
- [ ] In that second browser, the address of an image (`.../files/mask.png`) also gives "Page not found".
- [ ] "My scans" in the second browser is empty.

## My scans and deleting

- [ ] Back in the first browser, "My scans" lists your uploads, newest first, with thumbnails.
- [ ] "Delete" on one scan asks for confirmation and removes it from the list.
- [ ] The deleted scan's result address now gives "Page not found".
- [ ] "Delete my data" in the footer asks for confirmation, returns to the home page with a confirmation message, and the banner is back.
- [ ] The cookie list is empty again and `media/scans/` holds no folders.

## Error pages

- [ ] `http://127.0.0.1:8000/nothing-here/` shows the site's own "Page not found" page, not a Django debug page.

## Command line and housekeeping

- [ ] `.venv/bin/python -m inference list` prints your models.
- [ ] `.venv/bin/python -m inference predict <file> --model <model_key> --out out/` writes `mask.png`, `overlay.png` and `summary.json`.
- [ ] `.venv/bin/python manage.py purge_old_scans --days 7 --dry-run` prints the counts and deletes nothing.
- [ ] `.venv/bin/python -m pytest` passes.

## Front-door page (`deploy/pages/`)

The page for the permanent `github.io` address. It is not published yet, so
check it on this machine. In a second terminal:

```
cd deploy/pages
python3 -m http.server 8001 --bind 127.0.0.1
```

Open http://127.0.0.1:8001/. A `status.json` in that folder is git-ignored.

- [ ] Without `status.json` the page says "The demo is offline right now" and shows when it last checked.
- [ ] Copy `status.example.json` to `status.json` and set `until` to a time one hour from now (`date -u -v+1H +%Y-%m-%dT%H:%M:%SZ` prints one). Within 30 seconds the page says "The demo is online", counts down from 5 and leaves for the example address. That address does not exist, so the browser then shows an error; this is expected.
- [ ] Go to the page again and click "Stay on this page" during the countdown. The page stays, and "Open the demo now" still leads to the address.
- [ ] Set `until` to a time in the past. Within 30 seconds the page says offline.
- [ ] Set `until` to the future again and `url` to `https://example.com`. The page says offline: it forwards to `trycloudflare.com` addresses only.
- [ ] Delete `status.json` and stop the file server with Ctrl+C.

## Permanent address (live)

About five minutes. Needs a phone with mobile data (Wi-Fi off) and a PNG of a
brain slice on it.

- [ ] `.venv/bin/python deploy/tunnel/share.py --publish --hours 1` prints the box with `Permanent: https://salemaker47.github.io/senior_project_web/` and "forwards here in about a minute", and no warning.
- [ ] On the phone open https://salemaker47.github.io/senior_project_web/. Within a minute it says "The demo is online" and forwards after five seconds.
- [ ] The browser asks for a user name and password. `demo` and the access code get in.
- [ ] Accept the cookie, upload the PNG: the result page shows the mask.
- [ ] Open the github.io address again in a second tab. Press Ctrl+C in the terminal. The launcher prints "the front door says 'offline'", and within about a minute the second tab says "The demo is offline right now".
- [ ] `.venv/bin/python deploy/tunnel/share.py --publish --hours 0.05` and wait three minutes: the page goes online and, after the automatic stop, offline again.


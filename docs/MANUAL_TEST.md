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

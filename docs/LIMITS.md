# Known limits

**Research and education demo. Not for diagnosis.** This page says why.

## The models

**What they were trained on**

- FigShare models saw T1 contrast-enhanced slices of three tumor types:
  meningioma, glioma and pituitary tumor.
- BraTS 2020 models saw skull-stripped FLAIR slices of gliomas, with the tumor
  sub-regions merged into one "whole tumor" mask.
- A model is unreliable on anything else: another MRI sequence, CT, a scan
  with the skull still present for a BraTS model, other tumor types, children,
  post-surgery scans, or a photo of a printed film.
- Every FigShare slice contains a tumor. Those models have hardly seen a
  tumor-free slice, so they may mark something on a healthy one.

**What the scores mean**

- The Dice score shown on the about page is the validation score of one
  cross-validation fold on the training dataset. It is not a clinical accuracy.
- Models trained with an image-level split had slices of the same patient in
  both training and validation. Their scores are optimistic. The training
  repository's README explains this and lists the patient-level results that
  exist.
- The site serves, per model, the single fold with the highest validation
  score. There is no ensemble and no measure of uncertainty.

**What the output is**

- A binary mask of pixels: tumor or not. It does not name a tumor type, grade
  or size in millimetres.
- An empty mask is not a statement that the brain is healthy. A non-empty mask
  is not a statement that a tumor is present.
- The threshold is the one stored with the model (0.5 in all current recipes). The visitor cannot change it.
- Predicted blobs smaller than 20 pixels, counted on the 256 by 256 model
  image, are removed. A very small true finding can disappear with them.

**How the image is prepared**

- The network sees one 2D slice, resized to 256 by 256 pixels. It has no 3D
  context, and a non-square image is squeezed to a square.
- The mask is predicted at 256 by 256 and scaled back to the input size with
  nearest-neighbour resizing, so its edges are blocky on large images.
- Raw data (`.mat`, `.h5`, DICOM, 16-bit images) is clipped to its 1st to 99th
  percentile, as in training. An 8-bit PNG, JPEG or TIFF is used as it is,
  because the training images were 8-bit at that point. A screenshot with a
  different brightness window, borders, text or annotations will give a worse
  result.
- The model with CLAHE preprocessing (`06_clahe_dicebce`) is slightly random.
  The training code's CLAHE step draws its strength anew on every call, and
  this site copies that behaviour. The same image can give slightly different
  masks on two runs.

**What has been verified, and what not**

- Verified with the model `01_dice_image_level` (U-Net ResNet34, Dice loss,
  FigShare, image-level split): the checkpoint loads safely and strictly, and
  on six test-split slices the site's masks are pixel-identical to the
  training code's own predictions (the golden test). Uploading the raw
  FigShare `.mat` files gives the same masks as the PNGs.
- That model was trained on the MacBook GPU with the FigShare data rebuilt
  from the public download, not on Colab. Its scores belong to that run.
- `torch`, `segmentation-models-pytorch` and `albumentations` are pinned to the
  versions that model was trained with. Models trained with other versions,
  for example the Colab models, have not been checked here.
- The FLAIR (BraTS) side of the site has never run with a real model.

## The app

**Input**

- 2D only. NIfTI volumes and DICOM series are not supported; that phase of the
  plan was not built. A multi-frame DICOM is accepted, but only the frame with
  the most predicted tumor pixels is shown.
- Compressed DICOM (JPEG, JPEG 2000, RLE) cannot be read.
- Files up to 20 MB and images up to 4096 by 4096 pixels.
- The visitor chooses the model. The site cannot tell whether the scan type
  matches the model.

**Speed and scale**

- The prediction runs inside the upload request, on the CPU. The page waits
  until it is done. The first prediction after a start also loads the model.
- It is built for one or a few visitors on one machine and a SQLite database.
  `runserver` is Django's development server; do not expose that to the
  internet. For a public link use the hosting setup in `deploy/huggingface/`,
  which runs a production server with debug off and secure cookies.
- Models are found when the server starts. Restart it after changing
  `model_store/`.

**When shared from the owner's computer (tunnel)**

- The link works only while the launcher runs and the laptop is awake, and the
  address changes at every start. Cloudflare offers such tunnels for testing,
  without guarantees, and can see the traffic.
- Uploads are limited to PNG and JPEG unless `--all-formats` is given.
- Everyone who has the access code shares one set of limits per address; a
  whole classroom behind one network address can hit the upload limit.
- The sandbox relies on macOS's `sandbox-exec`, which Apple marks as
  deprecated. It was tested on the development Mac only.
- Visitors' addresses are written to `share_data/logs/` and stay there until
  the next session.

**When hosted publicly (Hugging Face Spaces)**

- Hugging Face now requires its paid PRO plan for this kind of Space.

- Anyone with the link can upload. There are no accounts and no rate limit.
- Uploads are deleted after one day and are lost at every restart of the
  Space; a free Space has no permanent disk.
- A free Space sleeps when nobody visits and takes about a minute to wake.
- One server process on a shared CPU: fine for a demo, slow under load.
- The container image has not been built on the development machine. The
  server, start script and proxy behaviour were tested locally without Docker.

**Privacy**

- The uploaded file is discarded after reading, so DICOM tags are not kept.
  Text that is part of the picture itself (burned-in names) is not detected or
  removed.
- Pixel data and results are stored unencrypted in `media/`, and the scan rows
  in the database carry the visitor's session key.
- A visitor who clears their cookies loses access to their scans. The files
  stay on disk until `purge_old_scans` runs; nothing runs it automatically.
- The session cookie is not marked Secure by default, because the demo runs
  over plain http on localhost.

**Browser**

- The opacity slider needs JavaScript. Without it the page shows a fixed
  overlay.
- A declined cookie banner is remembered only for the current tab.
- Checked in desktop Chrome. Phone-sized screens and other browsers have not
  been checked by hand.

**Platform**

- Developed on Python 3.9 and Django 4.2, the last Django line that supports
  Python 3.9. Both are past their upstream support period.
- Tested on macOS (Apple Silicon) only.

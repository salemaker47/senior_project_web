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
- Small local commits. No remote, no push.
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

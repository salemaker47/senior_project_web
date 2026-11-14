---
title: Brain MRI Tumor Segmentation Demo
emoji: 🧠
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Upload a brain MRI slice, get the predicted tumor mask
---

# Brain MRI tumor segmentation demo

**Research and education demo. Not for diagnosis.**

Upload one brain MRI slice and get the predicted tumor mask, an overlay and a
short summary. A student project; the model is a U-Net trained on the public
FigShare brain-tumor dataset (T1 contrast-enhanced slices).

Open the app in its own browser tab (the link is shown at the top of the app).
Inside this page the session cookie does not work, so uploads are disabled.

- Do not upload scans of real patients or images that carry personal details.
- Uploads are deleted after one day at the latest, and whenever this Space restarts.
- Source code and the list of known limits:
  https://github.com/salemaker47/senior_project_web

# Hosting the demo on Hugging Face Spaces (free)

GitHub stores the code but cannot run it. A Hugging Face Space can: it builds a
Docker container from four small files and gives the app a public link that
works from any device.

**Research and education demo. Not for diagnosis.** A public link means
strangers can upload images. Read "What changes when it is public" below first.

## What you need

- The code pushed to GitHub (the container downloads it from there).
- A free Hugging Face account.
- Four files to upload to the Space:

| File | Where it comes from |
|---|---|
| `Dockerfile` | `deploy/huggingface/Dockerfile` in this repository |
| `README.md` | `deploy/huggingface/README.md` (the Space's page card, not the project README) |
| `best_model.pt` | one fold of your model, e.g. `model_store/01_dice_image_level/fold_1/` |
| `experiment_config.json` | the same fold folder |

Upload the fold the site serves locally (the one `python -m inference list`
names). The container reads the model name and fold number from
`experiment_config.json` and files the model in the right place by itself.

## Steps

1. **Push the code.** In the repository folder: `git push`.
2. **Create the account** at https://huggingface.co/join and confirm your email.
3. **Create the Space** at https://huggingface.co/new-space:
   - Space name: for example `brain-mri-demo`
   - SDK: **Docker**, template **Blank**
   - Hardware: **CPU basic** (free)
   - Visibility: **Public**
4. **Upload the four files.** In the Space open the **Files** tab, choose
   **Add file**, then **Upload files**. Drag in all four files and click
   **Commit changes to main**. Your `README.md` replaces the one the Space
   created.
5. **Wait for the build.** The **App** tab shows "Building". The first build
   takes around ten minutes because it downloads PyTorch. The **Logs** button
   shows progress. Near the end of the build log you should see a line that
   starts with `installed model:`.
6. **Open the link.** When the status is "Running", the app's own address is

   ```
   https://<your-username>-<space-name>.hf.space
   ```

   The same link is behind the "Open the demo in its own tab" button shown at
   the top of the app on the Space page. Share this address. Inside the
   Hugging Face page itself the session cookie does not work, so the app only
   offers that button there.

## Recommended: set a secret key

In the Space, open **Settings**, then **Variables and secrets**, and add a
**secret** named `DJANGO_SECRET_KEY` with a long random value. You can make one
with:

```
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Without it the app makes a new key on every start. That works, but it signs
every visitor out whenever the Space restarts.

## Updating

- **New code:** push to GitHub, then in the Space's **Settings** click
  **Factory rebuild**. A normal restart keeps the old code.
- **New model:** upload the new `best_model.pt` and `experiment_config.json`
  over the old ones. The Space rebuilds by itself.

## What changes when it is public

- **Anyone with the link can upload.** The cookie banner, per-browser
  ownership of results and "Delete my data" all still apply. There are no
  accounts and no rate limit.
- **Uploads do not last.** They are deleted after one day at the latest, and
  all of them disappear whenever the Space restarts, because a free Space has
  no permanent disk.
- **It sleeps.** A free Space stops after a period without visitors (about two
  days at the time of writing) and wakes on the next visit, which takes around
  a minute.
- **One request at a time for predictions.** The app runs one server process on
  a shared CPU. It is fine for a demo, not for many simultaneous users.
- **The model file is public** in the Space's Files tab, like everything else
  in a public Space.

## If something goes wrong

| What you see | Likely cause |
|---|---|
| Build fails at `install_model.py` with "Git LFS pointer" | The model was added through git without LFS. Upload it through the Files page. |
| Build fails at `git clone` | The GitHub repository is private or the code was not pushed. |
| App runs but says "No trained models are installed yet" | The two model files were not uploaded, or only one of them was. |
| "That form has expired" on every button | Open the app at its own `.hf.space` address, not inside the Hugging Face page. |
| "Bad Request (400)" everywhere | The address is not the Space's. Check the link. |

## How it was tested

The container itself was not built on the development machine (no Docker
there). What was tested locally, from a clean copy of the code: the model
install step, the start script, the production server (`gunicorn`), and
requests that look like a browser coming through an HTTPS proxy, including the
case where the proxy sends no `X-Forwarded-Proto` header. The first real build
on Hugging Face is therefore the first test of the `Dockerfile`. If it fails,
the build log says where.

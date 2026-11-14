#!/usr/bin/env bash
# Start the site inside the container: database, model check, housekeeping, server.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
  # Better: set DJANGO_SECRET_KEY as a secret in the Space settings. Without it
  # a new key is made on every start, which signs visitors out on a restart
  # (their uploads are gone after a restart anyway: the disk is not kept).
  DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  export DJANGO_SECRET_KEY
  echo "[start] DJANGO_SECRET_KEY is not set; generated a temporary one for this run"
fi

python manage.py migrate --noinput

echo "[start] models in model_store/:"
python -m inference list || echo "[start] WARNING: no usable model found; the site will say that no model is installed"

# Housekeeping: remove old uploads now and then once an hour.
PURGE_DAYS="${PURGE_DAYS:-1}"
python manage.py purge_old_scans --days "$PURGE_DAYS" || true
(
  while true; do
    sleep "${PURGE_INTERVAL_SECONDS:-3600}"
    python manage.py purge_old_scans --days "$PURGE_DAYS" || true
  done
) &

# One process (the model is loaded once), a few threads for page views.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-7860}" \
  --workers 1 --threads 4 --timeout 120 \
  --access-logfile - --error-logfile -

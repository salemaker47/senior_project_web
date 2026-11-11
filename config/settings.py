"""
Django settings for the brain-MRI segmentation demo (local development).

No accounts: there is no auth app, no admin and no messages framework. The
only state kept per visitor is one anonymous session, created when the visitor
accepts the session cookie (see scans/consent.py).
"""

import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _load_secret_key() -> str:
    """
    $DJANGO_SECRET_KEY if set; otherwise a random key generated once and kept in
    the git-ignored file `.secret_key`, so sessions survive a server restart.
    """
    key = os.environ.get("DJANGO_SECRET_KEY")
    if key:
        return key
    key_file = BASE_DIR / ".secret_key"
    if key_file.is_file():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = get_random_secret_key()
    key_file.write_text(key + "\n", encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


SECRET_KEY = _load_secret_key()

# Local demo. Set DJANGO_DEBUG=0 to try the production-style behaviour.
DEBUG = _env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "scans",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # CSRF secret lives in the session (no csrftoken cookie); this subclass
    # never opens the session for a visitor without a session cookie.
    "scans.middleware.ConsentAwareCsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "scans.middleware.VaryOnCookieMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "scans.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------- #
# Sessions and cookies
#
# One essential cookie, set only after the visitor accepts it. It links the
# visitor's uploads to their browser. No tracking, no account.
# --------------------------------------------------------------------------- #
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "sessionid"
SESSION_COOKIE_AGE = 14 * 24 * 60 * 60          # 14 days
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG                # localhost runs over plain http
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False

# Keep the CSRF secret in the session, so no second cookie is ever set.
CSRF_USE_SESSIONS = True

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"


# --------------------------------------------------------------------------- #
# Files: uploads, results, trained models
# --------------------------------------------------------------------------- #
# Uploaded scans and results. Not routed in urls.py on purpose: Phase 3 serves
# these files through a view that checks the owner.
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

# Trained checkpoints: <MODEL_STORE_DIR>/<model_key>/fold_<k>/best_model.pt
MODEL_STORE_DIR = Path(os.environ.get("MODEL_STORE_DIR") or BASE_DIR / "model_store")

# Upload limits.
#   SCAN_MAX_UPLOAD_BYTES         largest scan file the upload form accepts
#   FILE_UPLOAD_MAX_MEMORY_SIZE   files above this are streamed to a temp file
#   DATA_UPLOAD_MAX_MEMORY_SIZE   largest request body excluding file data
#   DATA_UPLOAD_MAX_NUMBER_FILES  files per request
#   DATA_UPLOAD_MAX_NUMBER_FIELDS form fields per request
SCAN_MAX_UPLOAD_BYTES = _env_int("SCAN_MAX_UPLOAD_BYTES", 32 * 1024 * 1024)      # 32 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024                                     # 5 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024                                     # 1 MB
DATA_UPLOAD_MAX_NUMBER_FILES = 1
DATA_UPLOAD_MAX_NUMBER_FIELDS = 50


# --------------------------------------------------------------------------- #
# Internationalisation
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True


# --------------------------------------------------------------------------- #
# Static files (our own CSS and JavaScript; no CDN, no build step)
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

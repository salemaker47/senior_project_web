"""
Django settings for the brain-MRI segmentation demo (local development).

No accounts: there is no auth app, no admin and no messages framework. The
only state kept per visitor is one anonymous session, created when the visitor
accepts the session cookie (see scans/consent.py).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent

# Secret key, debug flag and optional overrides live in `.env` (git-ignored;
# see `.env.example`). Real environment variables take precedence.
load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Create the .env file with:  python -m config.make_env"
    )

# Off by default, so visitors never see Django's debug pages and stack traces.
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

# Behind an HTTPS proxy (the sharing tunnel; see deploy/tunnel/). Both off by
# default, so localhost behaves as before.
#   DJANGO_BEHIND_PROXY          trust the proxy's X-Forwarded-Proto header
#   DJANGO_CSRF_TRUSTED_ORIGINS  e.g. https://*.trycloudflare.com
BEHIND_PROXY = env_bool("DJANGO_BEHIND_PROXY", False)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "scans",
]

MIDDLEWARE = [
    # First, so a refused request reaches nothing else. Off unless
    # DJANGO_REQUEST_FIREWALL is set (public sharing; see scans/firewall.py).
    "scans.firewall.RequestFirewallMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # CSRF secret lives in the session (no csrftoken cookie); this subclass
    # never opens the session for a visitor without a session cookie.
    "scans.middleware.ConsentAwareCsrfViewMiddleware",
    # Content-Security-Policy, X-Frame-Options: DENY and related headers.
    "scans.middleware.SecurityHeadersMiddleware",
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
        # DJANGO_DB_PATH: the public sharing mode keeps its own database.
        "NAME": Path(os.environ.get("DJANGO_DB_PATH") or BASE_DIR / "db.sqlite3"),
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
# localhost runs over plain http; turn this on when the site is behind HTTPS.
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)

# Keep the CSRF secret in the session, so no second cookie is ever set.
CSRF_USE_SESSIONS = True
CSRF_FAILURE_VIEW = "scans.errors.csrf_failure"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"


# --------------------------------------------------------------------------- #
# Files: uploads, results, trained models
# --------------------------------------------------------------------------- #
# Uploaded scans and results. Not routed in urls.py on purpose: these files
# are served only through a view that checks the owner.
# DJANGO_MEDIA_ROOT: the public sharing mode keeps its own upload folder.
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT") or BASE_DIR / "media")

# Trained checkpoints: <MODEL_STORE_DIR>/<model_key>/fold_<k>/best_model.pt
# Relative values are taken from the project folder; absolute paths stay absolute.
MODEL_STORE_DIR = BASE_DIR / (os.environ.get("MODEL_STORE_DIR") or "model_store")

# Upload limits.
#   SCAN_MAX_UPLOAD_BYTES         largest 2D scan file the upload form accepts
#   SCAN_MAX_PIXELS               largest slice (width x height) accepted
#   FILE_UPLOAD_MAX_MEMORY_SIZE   files above this are streamed to a temp file
#   DATA_UPLOAD_MAX_MEMORY_SIZE   largest request body excluding file data
#   DATA_UPLOAD_MAX_NUMBER_FILES  files per request
#   DATA_UPLOAD_MAX_NUMBER_FIELDS form fields per request
SCAN_MAX_UPLOAD_BYTES = env_int("SCAN_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)      # 20 MB
SCAN_MAX_PIXELS = 4096 * 4096
# Formats the upload accepts (names as in inference.loaders). Empty = all.
# Public sharing narrows this to png,jpeg: fewer file parsers face strangers.
SCAN_ALLOWED_FORMATS = env_list("SCAN_ALLOWED_FORMATS", [])
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024                                     # 5 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024                                     # 1 MB
DATA_UPLOAD_MAX_NUMBER_FILES = 1
DATA_UPLOAD_MAX_NUMBER_FIELDS = 50

# The first handler stops reading an upload as soon as it passes
# SCAN_MAX_UPLOAD_BYTES, so an oversized file is never written to disk.
FILE_UPLOAD_HANDLERS = [
    "scans.uploadhandlers.MaxSizeUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]


# --------------------------------------------------------------------------- #
# Internationalisation
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True


# --------------------------------------------------------------------------- #
# Request firewall and access code (public sharing only; scans/firewall.py)
# --------------------------------------------------------------------------- #
REQUEST_FIREWALL = env_bool("DJANGO_REQUEST_FIREWALL", False)
FIREWALL_REQUESTS_PER_MINUTE = env_int("FIREWALL_REQUESTS_PER_MINUTE", 120)     # per address
FIREWALL_UPLOADS_PER_MINUTE = env_int("FIREWALL_UPLOADS_PER_MINUTE", 6)         # per address
FIREWALL_UPLOADS_PER_HOUR = env_int("FIREWALL_UPLOADS_PER_HOUR", 40)            # per address
FIREWALL_GLOBAL_UPLOADS_PER_MINUTE = env_int("FIREWALL_GLOBAL_UPLOADS_PER_MINUTE", 30)
FIREWALL_STRIKES_BEFORE_BAN = env_int("FIREWALL_STRIKES_BEFORE_BAN", 8)
FIREWALL_BAN_SECONDS = env_int("FIREWALL_BAN_SECONDS", 900)
# HTTP Basic password for the whole site. Empty = no password.
ACCESS_USER = os.environ.get("DEMO_ACCESS_USER") or "demo"
ACCESS_PASSWORD = os.environ.get("DEMO_ACCESS_PASSWORD", "")
# Ask search engines not to index the site (header on every response).
NO_INDEX = env_bool("DJANGO_NO_INDEX", False)


# --------------------------------------------------------------------------- #
# Static files (our own CSS and JavaScript; no CDN, no build step)
# --------------------------------------------------------------------------- #
# Served by config/urls.py straight from the app folder; no collectstatic.
STATIC_URL = "static/"


# --------------------------------------------------------------------------- #
# Logging: technical details of failures go to the console, not to visitors
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        "scans": {"handlers": ["console"], "level": "INFO"},      # includes scans.firewall
    },
}

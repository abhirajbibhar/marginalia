"""
Shared Django settings for both deployment targets.

Target-specific settings live in ``local.py`` (SQLite + filesystem) and
``cloudflare.py`` (D1 + R2 on Python Workers). Everything here must be valid on
BOTH targets: no PostgreSQL, no Redis, no subprocesses at import time.

Portability rules enforced by this module (see docs/PARITY.md):

* Only ORM features that work on SQLite *and* D1 (no transaction.atomic
  reliance, no select_for_update, no raw SQL).
* Password hashing uses Argon2id (argon2-cffi ships prebuilt for Pyodide and as
  a normal wheel locally) with parameters tuned for Worker CPU limits.
* Static and media handling is delegated to the target modules.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = False
DEPLOYMENT_TARGET = os.environ.get("DEPLOYMENT_TARGET", "local").strip().lower()

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    # Project apps (order: dependencies first). Labels stay the brief's names;
    # the apps/ package avoids stdlib shadowing (notably `collections`).
    "runtime",
    "apps.accounts",
    "apps.library",
    "apps.authors",
    "apps.series",
    "apps.collections",
    "apps.reading",
    "apps.annotations",
    "apps.rooms",
    "apps.dashboard",
    "apps.adminpanel",
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Project middleware (strict CSP incl. wasm-unsafe-eval for the PDF engine)
    "config.middleware.SecurityHeadersMiddleware",
    "config.middleware.RateLimitMiddleware",
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
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.library.context_processors.library_globals",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# DATABASES is defined by the target module.

# ---------------------------------------------------------------------------
# Auth & passwords
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "auth.User"  # stock user + accounts.Profile (role, theme, …)

# Argon2id fits both targets: argon2-cffi 23.x is a prebuilt Pyodide package and
# a normal wheel locally. Parameters are deliberately lighter than the Django
# defaults so that login stays inside Python Worker CPU budgets (≈50-100 ms of
# CPU per hash) while remaining a memory-hard KDF. Override via env if desired.
ARGON2_TIME_COST = int(os.environ.get("ARGON2_TIME_COST", "2"))
ARGON2_MEMORY_COST = int(os.environ.get("ARGON2_MEMORY_COST", "19456"))  # KiB
ARGON2_PARALLELISM = int(os.environ.get("ARGON2_PARALLELISM", "1"))

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    # PBKDF2 retained only for verifying hashes created before Argon2 was chosen.
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# ---------------------------------------------------------------------------
# Sessions & cookies (session auth; secure on both targets in production)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_USE_SESSIONS = False  # CSRF cookie + header (the JSON sync API needs it)
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (vendored locally: Bootstrap 6 alpha1, HTMX, EmbedPDF 2.15.1)
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Media / book storage (target modules may override STORAGES)
# ---------------------------------------------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Library limits (shared contract for upload, reading, annotations)
# ---------------------------------------------------------------------------
MAX_PDF_SIZE_MB = int(os.environ.get("MAX_PDF_SIZE_MB", "200"))
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", "5000"))
PAGE_SIZE = 48  # hard cap: D1 allows 100 bound parameters per query
LIBRARY_COVER_WIDTH = 480

ANNOTATION_MAX_PAYLOAD_BYTES = 64 * 1024        # per annotation payload
ANNOTATION_MAX_OPS_PER_REQUEST = 50             # per ops/ call
ANNOTATION_MAX_PER_USER_BOOK = 5000             # hard cap per user per book
ANNOTATION_OPS_PER_MINUTE = int(os.environ.get("ANNOTATION_OPS_PER_MINUTE", "120"))
ANNOTATION_FLUSH_MS = 750                        # client batch window (500-1000)
CHANGE_HORIZON_DAYS = int(os.environ.get("CHANGE_HORIZON_DAYS", "30"))

# Reader polling cadence (ms) — see docs/COLLABORATION.md
POLL_INTERVAL_ACTIVE_MS = 3000   # others present, tab visible
POLL_INTERVAL_ALONE_MS = 10000   # alone, tab visible
POLL_INTERVAL_HIDDEN_MS = 30000  # tab hidden

# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
UPLOAD_TO_R2_DIRECT = False  # True only on the cloudflare target (presigned)

# ---------------------------------------------------------------------------
# Security headers / CSP (config.middleware.SecurityHeadersMiddleware)
# ---------------------------------------------------------------------------
# 'wasm-unsafe-eval' is required to compile the PDF engine's WebAssembly; the
# engine worker falls back to a blob worker when workers are unavailable.
CSP_DIRECTIVES = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'wasm-unsafe-eval'"],
    "worker-src": ["'self'", "blob:"],
    "style-src": ["'self'", "'unsafe-inline'"],  # EmbedPDF injects runtime styles
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'"],
    "object-src": ["'none'"],
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
}

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# ---------------------------------------------------------------------------
# Rate limits (requests per minute per user/session) — runtime.RateLimiter
# ---------------------------------------------------------------------------
RATE_LIMITS = {
    "login": (10, 60),          # (attempts, seconds)
    "search": (60, 60),
    "download": (120, 60),
    "upload": (10, 60),
    "annotation_ops": (ANNOTATION_OPS_PER_MINUTE, 60),
}

# ---------------------------------------------------------------------------
# Defaults that matter on both targets
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"  # integer PKs keep D1 lean
USE_THOUSAND_SEPARATOR = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

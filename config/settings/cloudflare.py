"""Cloudflare target: Python Workers + D1 + R2.

Secrets come from Worker secrets (``wrangler secret put``), exposed to Python
through ``workers.env``. Never hard-code credentials here (see .env.example for
the names only).
"""
import os

from .base import *  # noqa: F401,F403

DEBUG = False

try:  # The workers runtime only exists inside a Worker (or pywrangler dev).
    from workers import env as _worker_env
except Exception:  # pragma: no cover - import guard for tooling on the host
    _worker_env = None


def _secret(name: str, default: str = "") -> str:
    """Read a Worker secret; fall back to an env var for management tooling."""
    if _worker_env is not None:
        value = getattr(_worker_env, name, None)
        if value is not None:
            return str(value)
    return os.environ.get(name, default)


SECRET_KEY = _secret("DJANGO_SECRET_KEY")
if not SECRET_KEY:  # fail closed: sessions/CSRF must not run with an empty key
    raise RuntimeError("DJANGO_SECRET_KEY Worker secret is required")

ALLOWED_HOSTS = [
    h.strip()
    for h in _secret("ALLOWED_HOSTS", "localhost").split(",")
    if h.strip()
]

# ---------------------------------------------------------------------------
# D1 database (sync ORM over the async D1 binding via django-cf)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django_cf.db.backends.d1",
        "CLOUDFLARE_BINDING": _secret("D1_BINDING", "DB"),
    }
}

# ---------------------------------------------------------------------------
# R2 storage (books/… and covers/… keys; blobs never pass through the DB)
# ---------------------------------------------------------------------------
UPLOAD_TO_R2_DIRECT = True

STORAGES["default"] = {  # noqa: F405
    "BACKEND": "django_cf.storage.R2Storage",
    "OPTIONS": {
        "binding": _secret("R2_BINDING", "BUCKET"),
        "location": "media",
        "allow_overwrite": False,
    },
}

# Presigned direct-to-R2 uploads (library.upload.presign) need the R2 S3 API
# credentials; provided as Worker secrets, never committed.
R2_ACCOUNT_ID = _secret("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = _secret("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _secret("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = _secret("R2_BUCKET_NAME")
R2_PUBLIC_HOST = _secret("R2_PUBLIC_HOST")  # optional custom domain for presign

# Static files are served by Workers static assets (see wrangler.jsonc);
# Django's staticfiles backend only collects them at build time.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Cookie hardening in production.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = False  # the Worker terminates TLS; don't loop redirects

# Worker CPU budget: keep heavy work bounded (metadata extraction is capped in
# library.metadata via MAX_METADATA_SECONDS).
FEATURE_REALTIME_PUSH = False  # WebSockets from Python Workers are unverified

# Trust the first proxy hop for scheme/host (Workers terminate TLS).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

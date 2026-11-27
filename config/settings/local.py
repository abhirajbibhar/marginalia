"""Local development / self-hosted target: SQLite + local filesystem."""
import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = os.environ.get("DEBUG", "1") == "1"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        # The same "small atomic writes" contract as on D1; kept honest locally.
        "OPTIONS": {"timeout": 20},
    }
}

# Local storage keeps keys relative to MEDIA_ROOT; the DB stores only keys.
STORAGES["default"] = {  # noqa: F405
    "BACKEND": "django.core.files.storage.FileSystemStorage",
    "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},  # noqa: F405
}

# Serve media through Django only in development; production local deployments
# should put nginx (or similar) in front — see docs/DEPLOY_LOCAL.md.
if DEBUG:
    # Uploaded PDFs need Range support (the viewer streams them).
    # reading.views.serve_book_file implements authenticated, ranged serving.
    pass

# Local-only convenience: allow all hosts in dev unless specified.
if DEBUG and not os.environ.get("ALLOWED_HOSTS"):
    ALLOWED_HOSTS = ["*"]  # noqa: F405

# Realtime: SSE endpoint available locally behind the capability flag.
FEATURE_REALTIME_PUSH = os.environ.get("FEATURE_REALTIME_PUSH", "0") == "1"

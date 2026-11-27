"""
Capability flags: what the current deployment target supports.

Everything target-specific is expressed here (and only consulted through this
module), so the rest of the codebase stays identical on both targets.
"""
from django.conf import settings


def _target() -> str:
    return getattr(settings, "DEPLOYMENT_TARGET", "local")


def is_cloudflare() -> bool:
    return _target() == "cloudflare"


def is_local() -> bool:
    return _target() == "local"


# -- storage ---------------------------------------------------------------
def storage_backend() -> str:
    """'local' (filesystem) or 'r2' (Cloudflare R2)."""
    return "r2" if is_cloudflare() else "local"


def supports_direct_upload() -> bool:
    """Presigned direct-to-R2 uploads (bypass Worker request size/time)."""
    return bool(getattr(settings, "UPLOAD_TO_R2_DIRECT", False))


def supports_range_reads() -> bool:
    """Both targets support ranged reads (local file slicing / R2 ranged get)."""
    return True


# -- database --------------------------------------------------------------
def supports_transactions() -> bool:
    """D1 has no interactive transactions; local SQLite does."""
    return is_local()


def max_bind_params() -> int:
    return 90  # D1: 100 bound params/query, keep headroom


# -- realtime --------------------------------------------------------------
def supports_realtime_push() -> bool:
    """SSE locally / (future) Durable Object WebSockets — behind a flag."""
    flag = getattr(settings, "FEATURE_REALTIME_PUSH", False)
    return flag in (True, 1, "1") and is_local()


def poll_intervals() -> dict:
    """Client poll cadence (ms) — see docs/COLLABORATION.md."""
    return {
        "active": getattr(settings, "POLL_INTERVAL_ACTIVE_MS", 3000),
        "alone": getattr(settings, "POLL_INTERVAL_ALONE_MS", 10000),
        "hidden": getattr(settings, "POLL_INTERVAL_HIDDEN_MS", 30000),
    }


# -- misc ------------------------------------------------------------------
def background_jobs() -> str:
    """'cron' on Cloudflare (Cron Triggers → /manage/tasks/), 'cron' locally."""
    return "cron"


def describe() -> dict:
    """Machine-readable capability snapshot (used by the admin dashboard)."""
    return {
        "target": _target(),
        "storage": storage_backend(),
        "direct_upload": supports_direct_upload(),
        "transactions": supports_transactions(),
        "realtime_push": supports_realtime_push(),
        "background_jobs": background_jobs(),
    }

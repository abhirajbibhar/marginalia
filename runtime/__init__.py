"""
Runtime services: caching and background work, target-aware.

* Cache  — per-isolate dict on Cloudflare (a Worker isolate is short-lived and
           state is cheap to rebuild), local-memory locally. Never required for
           correctness: everything cached is recomputable.
* Background work — no threads on Cloudflare. Periodic work is triggered by
           management commands (local cron / Cloudflare Cron Triggers hitting
           the /manage/tasks/ endpoint with a shared secret).
"""
import os
import time

from django.conf import settings


class RuntimeCache:
    """Tiny dict cache with TTL. Deliberately not Django's cache framework —
    we do not want a Redis-shaped interface inviting infrastructure we can't
    run on both targets."""

    def __init__(self):
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str, default=None):
        item = self._store.get(key)
        if not item:
            return default
        expires, value = item
        if time.monotonic() > expires:
            self._store.pop(key, None)
            return default
        return value

    def set(self, key: str, value, ttl_seconds: int = 60) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


cache = RuntimeCache()


def periodic_task_secret() -> str:
    """Shared secret for the cron-triggered maintenance endpoint."""
    return os.environ.get("TASKS_SECRET", "")


def maintenance_due() -> bool:
    """True when periodic maintenance has not run within the horizon window."""
    last = cache.get("maintenance:last")
    interval = int(getattr(settings, "MAINTENANCE_INTERVAL_S", 3600))
    return last is None or (time.monotonic() - float(last)) > interval


def mark_maintenance_done() -> None:
    cache.set("maintenance:last", time.monotonic(), ttl_seconds=10**9)

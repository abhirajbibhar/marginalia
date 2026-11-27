"""
Rate limiting and cache primitives that work on both targets.

No Redis, no external services. The default store is a small SQLite/D1 table
(``runtime.RateLimitBucket``) so limits survive isolate restarts on Workers;
for the local target a process-memory fallback is used when the table is not
yet migrated (tests, management commands).

Limits are expressed as (max_events, window_seconds) and enforced with a fixed
window counter: simple, cheap (one read + one upsert), and good enough for
login/search/download/upload/ops throttling.
"""
import time

from django.conf import settings
from django.db import connection
from django.utils import timezone


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds its budget inside the current window."""


class RateLimiter:
    """Fixed-window counter over the database, with an in-memory fallback."""

    def __init__(self):
        self._memory: dict[str, tuple[int, float]] = {}

    # -- public API ---------------------------------------------------------
    def check(self, key: str, max_events: int, window_seconds: int) -> None:
        """Raise RateLimitExceeded if ``key`` is over budget in this window."""
        if self.allow(key, max_events, window_seconds) is False:
            raise RateLimitExceeded(key)

    def allow(self, key: str, max_events: int, window_seconds: int) -> bool:
        now = time.time()
        window = int(now // window_seconds)
        bucket_key = f"{key}:{window}"
        return self._hit(bucket_key, max_events, window_seconds, now)

    # -- storage backends ---------------------------------------------------
    def _hit(self, bucket_key: str, max_events: int, window_seconds: int, now: float) -> bool:
        if self._db_available():
            return self._hit_db(bucket_key, max_events, window_seconds, now)
        return self._hit_memory(bucket_key, max_events, now)

    def _hit_db(self, bucket_key: str, max_events: int, window_seconds: int, now: float) -> bool:
        from runtime.models import RateLimitBucket

        expires = timezone.now() + timezone.timedelta(seconds=window_seconds * 2)
        try:
            bucket, _created = RateLimitBucket.objects.get_or_create(
                key=bucket_key, defaults={"count": 0, "expires_at": expires}
            )
        except Exception:  # table missing (fresh checkout) → memory fallback
            return self._hit_memory(bucket_key, max_events, now)
        if bucket.count >= max_events:
            return False
        # Single-statement increment: portable and race-tolerant (a rare extra
        # request under concurrency is acceptable for a rate limiter).
        RateLimitBucket.objects.filter(pk=bucket.pk, count__lt=max_events).update(
            count=bucket.count + 1
        )
        return True

    def _hit_memory(self, bucket_key: str, max_events: int, now: float) -> bool:
        count, expires = self._memory.get(bucket_key, (0, 0.0))
        if now > expires:
            count, expires = 0, now + 3600.0
        if count >= max_events:
            return False
        self._memory[bucket_key] = (count + 1, expires)
        return True

    @staticmethod
    def _db_available() -> bool:
        try:
            connection.ensure_connection()
            return True
        except Exception:
            return False


def limit_for(name: str) -> tuple[int, int]:
    """Look up a named limit from settings.RATE_LIMITS with a safe default."""
    return getattr(settings, "RATE_LIMITS", {}).get(name, (60, 60))


def purge_expired() -> int:
    """Delete expired buckets (management command / cron)."""
    from runtime.models import RateLimitBucket

    return RateLimitBucket.objects.filter(expires_at__lt=timezone.now()).delete()[0]

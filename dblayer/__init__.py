"""
Database portability layer.

Both targets run a SQLite-family engine (real SQLite locally, Cloudflare D1 on
Workers) behind Django's synchronous ORM. D1 differences that this module
neutralizes:

* **100 bound parameters per query** — every IN()-style fan-out must be chunked
  (``chunked`` / ``chunked_pks``).
* **No interactive transactions** — ``transaction.atomic`` is a no-op on D1 and
  rollback will not work. Writes are small atomic units, or idempotent
  sequences that can be replayed safely (see annotations.services).
* **Round trips are precious** — helpers to keep query counts flat
  (``chunked`` prefetch patterns, ``values_flat`` id lists).

No module below this one may contain DB-specific raw SQL.
"""
from django.db.models import QuerySet

# D1 hard limit: 100 bound parameters per statement. Leave headroom for
# annotations written inline in the same statement.
MAX_BIND_PARAMS = 90


def chunked(items, size: int = MAX_BIND_PARAMS):
    """Yield lists of at most ``size`` items (D1-safe batch sizes)."""
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def chunked_pks(qs: QuerySet, size: int = MAX_BIND_PARAMS):
    """Yield PK chunks for a queryset without loading full rows."""
    yield from chunked(qs.values_list("pk", flat=True), size)


def in_chunks(field_lookup: str, values, size: int = MAX_BIND_PARAMS):
    """
    Build a portable OR-chain for a big IN() lookup.

    Usage::

        books = in_chunks("pk__in", ids).map(Book.objects.filter)  # not this
        from django.db.models import Q
        query = in_chunks("pk__in", ids, )  # returns list[Q]
    """
    from django.db.models import Q

    parts = [Q(**{field_lookup: chunk}) for chunk in chunked(values, size)]
    combined = Q()
    for part in parts:
        combined |= part
    return combined


class AtomicWrite:
    """
    Context manager that is a *real* transaction on SQLite and a documented
    no-op boundary on D1.

    Use it to express intent for local correctness, but never rely on rollback
    for multi-row invariants on Cloudflare — instead make each write idempotent
    and ordered so a partial failure can be retried (the annotation ops pipeline
    does exactly this).
    """

    def __init__(self, using: str | None = None):
        self.using = using
        self._ctx = None

    def __enter__(self):
        from django.db import transaction

        self._ctx = transaction.atomic(using=self.using)
        return self._ctx.__enter__()

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)

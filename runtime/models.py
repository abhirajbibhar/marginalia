"""
Runtime persistence: the rate-limit bucket table.

Kept in its own app so the runtime-services layer has exactly one model and
zero coupling to library data. (The brief's app list gains one small infra app;
everything else stays where the brief puts it.)
"""
from django.db import models


class RateLimitBucket(models.Model):
    """Fixed-window counter row: one row per (key, window)."""

    key = models.CharField(max_length=200, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["expires_at"])]

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.key} ({self.count})"

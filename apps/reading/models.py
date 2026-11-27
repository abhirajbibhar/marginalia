"""
Reading state: bookmarks, progress, reviews.

ReadingProgress is written from the reader through the JSON sync endpoint (the
only non-HTMX XHR surface) because it is driven by viewer page events.
"""
from django.conf import settings
from django.db import models

from apps.library.models import Book


class Bookmark(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="bookmarks")
    page_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "book", "page_number"], name="uniq_bookmark_user_book_page"
            )
        ]
        indexes = [models.Index(fields=["user", "book"])]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.book_id}@{self.page_number}"


class ReadingProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="progress"
    )
    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name="progress"
    )
    percentage = models.FloatField(default=0.0)
    last_position = models.PositiveIntegerField(default=0)  # page (1-based)
    last_read = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "reading progress"
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="uniq_progress_user_book")
        ]
        indexes = [models.Index(fields=["user", "-last_read"])]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.book_id} p{self.last_position}"


class DownloadAudit(models.Model):
    """Audit row per PDF download/stream request (security requirement)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="download_audit"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="download_audit")
    bytes_sent = models.PositiveBigIntegerField(default=0)
    range_request = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["book", "-created_at"]), models.Index(fields=["user", "-created_at"])]


class Review(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()  # 1..5
    review_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="uniq_review_user_book"),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_range",
            ),
        ]
        indexes = [models.Index(fields=["book", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.user_id}→{self.book_id}: {self.rating}"

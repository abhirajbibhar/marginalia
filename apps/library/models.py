"""
Library catalogue: books, categories, tags.

Storage discipline: the DB stores only **keys** (``file_path`` → books/…,
``cover_path`` → covers/…). Blobs live in local storage or R2, chosen at
runtime through ``library.storage.get_storage()``.
"""
from django.db import models

from apps.authors.models import Author
from apps.series.models import Series

PDF_FORMAT = "pdf"  # the only accepted format; everything else is rejected


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    name_norm = models.CharField(max_length=120, db_index=True, blank=True)
    slug = models.SlugField(max_length=140, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name_norm"]

    def save(self, *args, **kwargs):
        self.name_norm = self.name.lower().strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=120, unique=True)
    name_norm = models.CharField(max_length=120, db_index=True, blank=True)
    slug = models.SlugField(max_length=140, unique=True)

    class Meta:
        ordering = ["name_norm"]

    def save(self, *args, **kwargs):
        self.name_norm = self.name.lower().strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    """A PDF book. Format is fixed to PDF — the app rejects everything else."""

    title = models.CharField(max_length=500)
    title_norm = models.CharField(max_length=500, db_index=True, blank=True)
    subtitle = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    isbn = models.CharField(max_length=32, blank=True, db_index=True)
    language = models.CharField(max_length=32, blank=True, default="en")
    publication_date = models.DateField(null=True, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    pages = models.PositiveIntegerField(default=0)

    # Storage keys — never blobs.
    file_path = models.CharField(max_length=255, unique=True)   # books/…
    cover_path = models.CharField(max_length=255, blank=True)   # covers/…
    file_format = models.CharField(max_length=8, default=PDF_FORMAT, editable=False)
    file_size = models.PositiveBigIntegerField(default=0)

    # Search: one normalized column for DB-only search (title, author, series,
    # isbn, category) — no Elasticsearch on either target.
    search_text = models.TextField(blank=True, db_index=True)

    authors = models.ManyToManyField(Author, related_name="books", blank=True)
    categories = models.ManyToManyField(Category, related_name="books", blank=True)
    tags = models.ManyToManyField(Tag, related_name="books", blank=True)
    series = models.ForeignKey(
        Series, null=True, blank=True, on_delete=models.SET_NULL, related_name="books"
    )
    series_order = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )

    uploaded_by = models.ForeignKey(
        "accounts.Profile", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="uploaded_books",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title_norm"]
        indexes = [
            models.Index(fields=["title_norm"]),
            models.Index(fields=["series", "series_order"]),
            models.Index(fields=["created_at"]),
        ]

    def save(self, *args, **kwargs):
        self.title_norm = self.title.lower().strip()
        self.file_format = PDF_FORMAT
        super().save(*args, **kwargs)
        self.refresh_search_text()

    def refresh_search_text(self) -> None:
        """Rebuild the normalized search column (portable, cheap)."""
        parts = [self.title, self.subtitle, self.isbn, self.publisher]
        parts.extend(self.authors.values_list("name", flat=True))
        if self.series_id:
            parts.append(self.series.name)
        parts.extend(self.categories.values_list("name", flat=True))
        text = " ".join(p for p in parts if p).lower()
        if text != self.search_text:
            Book.objects.filter(pk=self.pk).update(search_text=text)
            self.search_text = text

    @property
    def cover_url(self) -> str:
        from apps.library.storage import get_storage

        return get_storage().url(self.cover_path) if self.cover_path else ""

    def __str__(self) -> str:
        return self.title

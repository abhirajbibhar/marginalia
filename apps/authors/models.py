"""Authors of books (M2M from Book)."""
from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=255)
    name_norm = models.CharField(max_length=255, db_index=True, blank=True)
    sort_name = models.CharField(max_length=255, blank=True)
    biography = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_name", "name"]
        indexes = [models.Index(fields=["name_norm"])]

    def save(self, *args, **kwargs):
        self.name_norm = self.name.lower().strip()
        if not self.sort_name:
            self.sort_name = self.name_norm
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

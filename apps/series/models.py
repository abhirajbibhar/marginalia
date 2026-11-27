"""Book series (optional FK on Book plus ordering)."""
from django.db import models


class Series(models.Model):
    name = models.CharField(max_length=255)
    name_norm = models.CharField(max_length=255, db_index=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "series"
        ordering = ["name_norm"]
        indexes = [models.Index(fields=["name_norm"])]

    def save(self, *args, **kwargs):
        self.name_norm = self.name.lower().strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

"""
Collections: user-curated shelves.

Visibility:
* private — only the owner sees it
* public  — everyone can browse it
* shared  — owner + members (M2M) can see it
"""
from django.conf import settings
from django.db import models

from apps.library.models import Book


class Visibility(models.TextChoices):
    PRIVATE = "private", "Private"
    PUBLIC = "public", "Public"
    SHARED = "shared", "Shared"


class Collection(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collections"
    )
    visibility = models.CharField(
        max_length=8, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    books = models.ManyToManyField(Book, related_name="collections", blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="shared_collections", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_collection_owner_name")
        ]

    def is_visible_to(self, user) -> bool:
        if self.visibility == Visibility.PUBLIC:
            return True
        if not user.is_authenticated:
            return False
        if self.owner_id == user.pk:
            return True
        return self.visibility == Visibility.SHARED and self.members.filter(pk=user.pk).exists()

    def __str__(self) -> str:
        return self.name

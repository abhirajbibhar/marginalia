"""Library admin."""
from django.contrib import admin

from apps.library.models import Book, Category, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "pages", "file_size", "created_at")
    list_filter = ("language", "categories", "series")
    search_fields = ("title", "isbn", "search_text")
    filter_horizontal = ("authors", "categories", "tags")
    # file_path/cover_path are storage keys; never edit blobs here.
    readonly_fields = ("file_path", "cover_path", "file_format", "file_size",
                       "search_text", "created_at", "updated_at")

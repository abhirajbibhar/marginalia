"""Annotation admin — moderation surface only.

Private annotations (room is NULL) are visible to their author only; even
Admins cannot read private notes (they may delete user data). The admin list
therefore defaults to room annotations and shows comment text only for those.
"""
from django.contrib import admin

from apps.annotations.models import Annotation, AnnotationChange


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ("uid", "book", "room", "author", "subtype", "page_index", "updated_at")
    list_filter = ("subtype", "room")
    search_fields = ("uid", "book__title", "text")
    readonly_fields = ("payload", "revision", "created_at", "updated_at")

    def get_queryset(self, request):
        # Privacy: hide private-layer annotations from the admin surface.
        return super().get_queryset(request).filter(room__isnull=False)


@admin.register(AnnotationChange)
class AnnotationChangeAdmin(admin.ModelAdmin):
    list_display = ("id", "op", "annotation_uid", "book", "room", "actor", "created_at")
    list_filter = ("op",)
    readonly_fields = ("annotation_uid", "book", "room", "op", "revision", "actor", "created_at")

    def has_add_permission(self, request):
        return False

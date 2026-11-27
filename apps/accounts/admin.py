"""Profile admin (role management)."""
from django.contrib import admin

from apps.accounts.models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "display_name", "default_layer", "updated_at")
    list_filter = ("role", "default_layer")
    search_fields = ("user__username", "user__email", "display_name")
    # Privacy: admins may delete user data but must not read private
    # annotations — the model layer has no admin surface for annotations'
    # payload contents beyond moderation tools.

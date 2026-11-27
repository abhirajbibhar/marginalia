"""Signal wiring: every user gets a Profile automatically."""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        # Register post_save → Profile creation. Without this, users created
        # outside the app (createsuperuser, django.contrib.admin) crash every
        # page that touches request.user.profile.
        from apps.accounts import signals  # noqa: F401

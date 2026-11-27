"""Authors app config."""
from django.apps import AppConfig


class AuthorsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.authors"
    label = "authors"

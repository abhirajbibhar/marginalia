"""Reading app config."""
from django.apps import AppConfig


class ReadingConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.reading"
    label = "reading"

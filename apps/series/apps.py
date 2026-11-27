"""Series app config."""
from django.apps import AppConfig


class SeriesConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.series"
    label = "series"

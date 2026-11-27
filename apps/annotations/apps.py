"""Annotations app config."""
from django.apps import AppConfig


class AnnotationsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.annotations"
    label = "annotations"

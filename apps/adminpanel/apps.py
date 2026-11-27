"""Admin panel app config."""
from django.apps import AppConfig


class AdminpanelConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.adminpanel"
    label = "adminpanel"

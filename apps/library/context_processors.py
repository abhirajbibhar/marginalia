"""Template context available on every page (target + pinned viewer version)."""
from django.conf import settings

from apps.library import capabilities


def library_globals(request):
    return {
        "DEPLOYMENT_TARGET": capabilities.describe(),
        "EMBEDPDF_VERSION": getattr(settings, "EMBEDPDF_VERSION", "2.15.1"),
    }

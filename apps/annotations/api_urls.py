"""JSON sync API URLs (mounted at /api/reading/)."""
from django.urls import path

from apps.annotations import api_views

app_name = "annotation_api"

urlpatterns = [
    path("<int:book_id>/annotations/", api_views.snapshot, name="snapshot"),
    path("<int:book_id>/annotations/ops/", api_views.ops, name="ops"),
    path("<int:book_id>/annotations/changes/", api_views.changes, name="changes"),
    path("<int:book_id>/annotations/presence/", api_views.presence, name="presence"),
]

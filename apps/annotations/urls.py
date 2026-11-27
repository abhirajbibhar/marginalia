"""Annotation page URLs (My Annotations)."""
from django.urls import path

from apps.annotations import views

app_name = "annotations"

urlpatterns = [
    path("", views.mine, name="mine"),
]

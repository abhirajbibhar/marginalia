"""
Admin dashboard: active target, pinned EmbedPDF version, annotation and room
counts, plus the cron-triggered maintenance endpoint.
"""
import hmac

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

from apps.annotations.models import Annotation, AnnotationChange
from apps.library import capabilities
from apps.library.models import Book
from apps.rooms.models import ReadingRoom
from apps.accounts.models import Profile
from runtime import mark_maintenance_done, periodic_task_secret

app_name = "adminpanel"


@login_required
@require_GET
def dashboard(request):
    if not request.user.profile.is_admin:
        return render(request, "403.html", status=403)
    stats = {
        "books": Book.objects.count(),
        "users": Profile.objects.count(),
        "annotations": Annotation.objects.filter(deleted_at=None).count(),
        "private_annotations": Annotation.objects.filter(room__isnull=True, deleted_at=None).count(),
        "room_annotations": Annotation.objects.filter(room__isnull=False, deleted_at=None).count(),
        "rooms": ReadingRoom.objects.count(),
        "active_rooms": ReadingRoom.objects.filter(is_active=True).count(),
        "changes": AnnotationChange.objects.count(),
    }
    return render(request, "adminpanel/dashboard.html", {
        "nav": "admin", "stats": stats, "caps": capabilities.describe(),
        "embedpdf_version": getattr(settings, "EMBEDPDF_VERSION", "2.15.1"),
    })


@require_POST
def tasks(request):
    """Cron Trigger / cron entrypoint for periodic maintenance."""
    secret = periodic_task_secret()
    provided = request.headers.get("X-Tasks-Secret", "")
    if not secret or not hmac.compare_digest(secret, provided):
        return HttpResponseForbidden("bad secret")
    from django.core.management import call_command

    call_command("compact_annotation_changes")
    from runtime import ratelimit

    ratelimit.purge_expired()
    mark_maintenance_done()
    return HttpResponse("ok")


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("tasks/", tasks, name="tasks"),
]

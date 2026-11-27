"""Dashboard: library KPIs, recent activity, continue reading."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import render
from django.urls import path

from apps.annotations.models import Annotation, AnnotationChange
from apps.library.models import Book
from apps.reading.models import ReadingProgress
from apps.rooms.models import ReadingRoom

app_name = "dashboard"


@login_required
def home(request):
    user = request.user

    # KPIs — flat aggregates; one query per stat keeps D1 round trips low.
    stats = {
        "books": Book.objects.count(),
        "authors": Book.objects.aggregate(n=Count("authors", distinct=True))["n"],
        "rooms": ReadingRoom.objects.filter(is_active=True).count(),
        "annotations": Annotation.objects.filter(author=user, deleted_at=None).count(),
    }

    # Recent activity: room activity across the user's circles.
    recent_changes = (
        AnnotationChange.objects.select_related("actor", "book")
        .filter(room__isnull=False)
        .order_by("-id")[:8]
    )
    my_recent = (
        Annotation.objects.select_related("book")
        .filter(author=user, deleted_at=None)
        .order_by("-updated_at")[:8]
    )

    # "Today and next" becomes Continue Reading.
    continue_reading = (
        ReadingProgress.objects.select_related("book")
        .filter(user=user)
        .order_by("-last_read")[:6]
    )

    rooms = (
        ReadingRoom.objects.filter(members__user=user, is_active=True)
        .select_related("book", "owner")
        .distinct()[:6]
    )

    return render(request, "dashboard/home.html", {
        "nav": "dashboard",
        "stats": stats,
        "recent_changes": recent_changes,
        "my_recent": my_recent,
        "continue_reading": continue_reading,
        "rooms": rooms,
    })


urlpatterns = [
    path("", home, name="home"),
]

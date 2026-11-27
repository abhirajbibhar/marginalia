"""My Annotations: filterable list linking into the reader at the right page."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.urls import path

from apps.annotations.models import Annotation, AnnotationSubtype

app_name = "annotations"


@login_required
def mine(request):
    qs = (
        Annotation.objects.select_related("book", "room", "author", "author__profile")
        .filter(author=request.user, deleted_at=None)
    )
    book_id = request.GET.get("book")
    if book_id:
        qs = qs.filter(book_id=book_id)
    subtype = request.GET.get("type")
    if subtype in AnnotationSubtype.values:
        qs = qs.filter(subtype=subtype)
    text = (request.GET.get("text") or "").strip()
    if text:
        qs = qs.filter(Q(text__icontains=text) | Q(book__title__icontains=text))
    layer = request.GET.get("layer")
    if layer == "private":
        qs = qs.filter(room__isnull=True)
    elif layer == "room":
        qs = qs.filter(room__isnull=False)

    qs = qs.order_by("-updated_at")
    page_obj = Paginator(qs, 48).get_page(request.GET.get("page") or 1)

    context = {
        "nav": "annotations",
        "page_obj": page_obj,
        "filters": request.GET,
        "subtypes": AnnotationSubtype.choices,
        "books": request.user.annotations.order_by("book__title").values_list(
            "book_id", "book__title"
        ).distinct()[:100],
    }
    if request.headers.get("HX-Request"):
        return render(request, "annotations/_list.html", context)
    return render(request, "annotations/mine.html", context)


urlpatterns = [
    path("", mine, name="mine"),
]

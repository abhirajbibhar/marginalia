"""Series browse pages."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.urls import path

from apps.series.models import Series

app_name = "series"
PAGE_SIZE = 48


@login_required
def series_list(request):
    qs = Series.objects.annotate(n_books=Count("books", distinct=True)).order_by("name_norm")
    q = (request.GET.get("q") or "").strip().lower()
    if q:
        qs = qs.filter(name_norm__contains=q)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page") or 1)
    return render(request, "series/list.html", {"nav": "series", "page_obj": page_obj, "q": q})


@login_required
def series_detail(request, pk):
    series = get_object_or_404(Series, pk=pk)
    books = series.books.prefetch_related("authors").order_by("series_order", "title_norm")
    return render(request, "series/detail.html", {
        "nav": "series", "series": series, "books": books,
    })


urlpatterns = [
    path("", series_list, name="list"),
    path("<int:pk>/", series_detail, name="detail"),
]

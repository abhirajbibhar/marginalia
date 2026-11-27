"""Author browse pages."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.urls import path

from apps.authors.models import Author

app_name = "authors"
PAGE_SIZE = 48


@login_required
def author_list(request):
    qs = Author.objects.annotate(n_books=Count("books", distinct=True)).order_by("sort_name")
    q = (request.GET.get("q") or "").strip().lower()
    if q:
        qs = qs.filter(name_norm__contains=q)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page") or 1)
    return render(request, "authors/list.html", {"nav": "authors", "page_obj": page_obj, "q": q})


@login_required
def author_detail(request, pk):
    author = get_object_or_404(Author, pk=pk)
    books = author.books.select_related("series").prefetch_related("authors")[:100]
    return render(request, "authors/detail.html", {
        "nav": "authors", "author": author, "books": books,
    })


urlpatterns = [
    path("", author_list, name="list"),
    path("<int:pk>/", author_detail, name="detail"),
]

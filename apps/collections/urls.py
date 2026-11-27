"""Collection CRUD."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.views.decorators.http import require_POST

from apps.collections.forms import CollectionForm
from apps.collections.models import Collection

app_name = "collections"


@login_required
def collection_list(request):
    qs = Collection.objects.filter(
        Q(owner=request.user) | Q(visibility="public") | Q(members=request.user)
    ).distinct().prefetch_related("books")
    return render(request, "collections/list.html", {"nav": "collections", "collections": qs})


@login_required
def collection_detail(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    if not collection.is_visible_to(request.user):
        return render(request, "403.html", status=403)
    books = collection.books.select_related("series").prefetch_related("authors")
    return render(request, "collections/detail.html", {
        "nav": "collections", "collection": collection, "books": books,
    })


@login_required
def collection_create(request):
    if request.method == "POST":
        form = CollectionForm(request.POST)
        if form.is_valid():
            collection = form.save(commit=False)
            collection.owner = request.user
            collection.save()
            form.save_m2m()
            messages.success(request, "Collection created.")
            return redirect("collections:detail", pk=collection.pk)
    else:
        form = CollectionForm()
    return render(request, "collections/form.html", {"form": form, "nav": "collections"})


@login_required
@require_POST
def add_book(request, pk):
    collection = get_object_or_404(Collection, pk=pk, owner=request.user)
    book_id = request.POST.get("book_id")
    if book_id:
        from apps.library.models import Book

        collection.books.add(get_object_or_404(Book, pk=book_id))
    return redirect(request.META.get("HTTP_REFERER", "/"))


urlpatterns = [
    path("", collection_list, name="list"),
    path("new/", collection_create, name="create"),
    path("<int:pk>/", collection_detail, name="detail"),
    path("<int:pk>/add-book/", add_book, name="add_book"),
]

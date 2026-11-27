"""
Library views: browse (grid/list + filters + infinite scroll), book details,
search, and the upload pipeline (presign → PUT → complete → review).

HTMX conventions: pages render full documents; HX-Request fragments return
only the swap target (checked per view). Every list page caps at
settings.PAGE_SIZE (48) for D1's 100-bound-parameter budget.
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Prefetch, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.authors.models import Author
from apps.library import capabilities
from apps.library.forms import BookForm
from apps.library.models import Book, Category, Tag
from apps.library.storage import book_key, get_storage
from apps.library.upload import presign_put_url
from apps.library.validation import validate_pdf
from apps.reading.models import Review
from apps.series.models import Series

app_name = "library"

PAGE_SIZE = getattr(settings, "PAGE_SIZE", 48)


def _book_queryset():
    return Book.objects.select_related("series").prefetch_related(
        "authors", "categories"
    ).annotate(
        avg_rating=Avg("reviews__rating"), n_reviews=Count("reviews", distinct=True)
    )


def _apply_filters(qs, params):
    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(search_text__contains=q.lower())
    for param, lookup in [
        ("category", "categories__slug"),
        ("author", "authors__slug"),
        ("tag", "tags__slug"),
        ("series", "series__slug"),
        ("language", "language__iexact"),
    ]:
        value = params.get(param)
        if value:
            qs = qs.filter(**{lookup: value})
    return qs.distinct()


@login_required
@require_GET
def browse(request):
    qs = _apply_filters(_book_queryset(), request.GET)
    order = request.GET.get("order", "title")
    if order == "recent":
        qs = qs.order_by("-created_at")
    elif order == "author":
        qs = qs.order_by("authors__sort_name", "title_norm")
    else:
        qs = qs.order_by("title_norm")

    paginator = Paginator(qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    context = {
        "nav": "library",
        "page_obj": page_obj,
        "view": "list" if request.GET.get("view") == "list" else "grid",
        "filters": request.GET,
        "categories": Category.objects.all()[:60],
        "authors": Author.objects.all()[:60],
        "series_list": Series.objects.all()[:60],
        "tags": Tag.objects.all()[:60],
    }
    if request.headers.get("HX-Request"):
        # Appendable fragment: items + the next Load-more control only.
        return render(request, "library/_book_items.html", context)
    return render(request, "library/browse.html", context)


@login_required
@require_GET
def detail(request, pk):
    book = get_object_or_404(
        _book_queryset(), pk=pk
    )
    reviews = book.reviews.select_related("user", "user__profile")[:20]
    user_review = book.reviews.filter(user=request.user).first()
    from apps.collections.models import Collection

    user_collections = Collection.objects.filter(
        Q(owner=request.user) | Q(members=request.user)
    ).distinct()
    from apps.rooms.models import ReadingRoom

    rooms = book.rooms.filter(is_active=True).select_related("owner")[:10]
    my_rooms = list(
        book.rooms.filter(is_active=True, members__user=request.user).values_list("pk", flat=True)
    )

    if request.headers.get("HX-Request"):
        return render(request, "library/_book_card.html", {"book": book})
    return render(request, "library/detail.html", {
        "nav": "library",
        "book": book,
        "reviews": reviews,
        "user_review": user_review,
        "user_collections": user_collections,
        "rooms": rooms,
        "my_rooms": my_rooms,
    })


@login_required
@require_GET
def search(request):
    q = (request.GET.get("q") or "").strip()
    results = Book.objects.none()
    if q:
        # DB-only search over normalized columns (title, author, category,
        # series, isbn) — no Elasticsearch on either target.
        results = _apply_filters(_book_queryset(), {"q": q}).order_by("title_norm")
    paginator = Paginator(results, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return render(request, "library/search.html", {
        "nav": "library", "q": q, "page_obj": page_obj,
    })


# ---------------------------------------------------------------------------
# Upload pipeline
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def upload(request):
    """Upload page: one form that presigns/puts/validates client-side steps."""
    if not request.user.profile.can_manage_library():
        return HttpResponseBadRequest("Librarian role required.")
    return render(request, "library/upload.html", {"nav": "library"})


@login_required
@require_POST
def upload_presign(request):
    """Return the storage key and upload URL for one PDF."""
    if not request.user.profile.can_manage_library():
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    filename = str(body.get("filename", ""))
    size = int(body.get("size", 0))
    if not filename.lower().endswith(".pdf"):
        return JsonResponse({"error": "only .pdf files are accepted"}, status=400)
    cap = int(getattr(settings, "MAX_PDF_SIZE_MB", 200)) * 1024 * 1024
    if size and size > cap:
        return JsonResponse({"error": "file too large"}, status=400)

    key = book_key(filename)
    if capabilities.supports_direct_upload():
        url = presign_put_url(key)
        if not url:
            return JsonResponse({"error": "presigning not configured"}, status=500)
        return JsonResponse({"key": key, "upload_url": url, "method": "PUT"})
    # Local target: authenticated PUT endpoint (small files are fine).
    return JsonResponse({
        "key": key,
        "upload_url": f"/library/upload/put/{key}/",
        "method": "PUT",
    })


@login_required
@require_http_methods(["PUT", "POST"])
def upload_put(request, key):
    """Local-target upload sink; writes bytes to LocalStorage."""
    if not request.user.profile.can_manage_library():
        return JsonResponse({"error": "forbidden"}, status=403)
    if not key.startswith("books/"):
        return JsonResponse({"error": "bad key"}, status=400)
    storage = get_storage()
    data = request.body
    cap = int(getattr(settings, "MAX_PDF_SIZE_MB", 200)) * 1024 * 1024
    if len(data) > cap:
        return JsonResponse({"error": "file too large"}, status=400)
    storage.save(key, data)
    return JsonResponse({"ok": True, "key": key, "size": len(data)})


@login_required
@require_POST
def upload_complete(request):
    """Validate the uploaded object, extract metadata, create the Book."""
    if not request.user.profile.can_manage_library():
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    key = body.get("key", "")
    if not key.startswith("books/"):
        return JsonResponse({"error": "bad key"}, status=400)

    storage = get_storage()
    if not storage.exists(key):
        return JsonResponse({"error": "upload not found"}, status=404)

    from apps.library.pdffile import reader_for

    reader = reader_for(storage, key)
    result = validate_pdf(reader, storage.size(key), filename=key)
    if not result.ok:
        storage.delete(key)
        return JsonResponse({"error": "; ".join(result.errors)}, status=400)

    from apps.library.metadata import extract_metadata

    reader.seek(0)
    meta = extract_metadata(reader)

    book = Book.objects.create(
        title=meta.title or "Untitled",
        file_path=key,
        file_size=storage.size(key),
        pages=meta.pages,
        uploaded_by=request.user.profile,
        publisher="",
        description="",
    )
    # Link extracted authors; librarian edits everything else afterwards.
    for name in meta.authors[:8]:
        author, _created = Author.objects.get_or_create(name=name)
        book.authors.add(author)
    book.refresh_search_text()

    warnings = result.warnings
    return JsonResponse({
        "ok": True,
        "book_id": book.pk,
        "edit_url": f"/library/{book.pk}/edit/",
        "warnings": warnings,
        "meta": {
            "title": meta.title, "authors": meta.authors, "pages": meta.pages,
        },
    })


@login_required
@require_POST
def upload_cover(request, pk):
    """Cover upload (JPEG/PNG rendered client-side from page 1)."""
    book = get_object_or_404(Book, pk=pk)
    if not request.user.profile.can_manage_library():
        return JsonResponse({"error": "forbidden"}, status=403)
    image = request.FILES.get("cover")
    if not image:
        return JsonResponse({"error": "no image"}, status=400)
    if image.size > 8 * 1024 * 1024:
        return JsonResponse({"error": "cover too large"}, status=400)
    ctype = image.content_type or ""
    if ctype not in {"image/jpeg", "image/png", "image/webp"}:
        return JsonResponse({"error": "cover must be jpeg/png/webp"}, status=400)

    from apps.library.storage import cover_key

    key = cover_key(book.pk, ext=".jpg" if ctype == "image/jpeg" else ".png")
    storage = get_storage()
    storage.save(key, image.read())
    if book.cover_path:
        try:
            storage.delete(book.cover_path)
        except Exception:
            pass
    book.cover_path = key
    book.save(update_fields=["cover_path", "updated_at"])
    return JsonResponse({"ok": True, "cover_url": book.cover_url})


@login_required
@require_http_methods(["GET", "POST"])
def edit_book(request, pk):
    """Librarian review form (pre-filled from extracted metadata)."""
    if not request.user.profile.can_manage_library():
        return HttpResponseBadRequest("Librarian role required.")
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        form = BookForm(request.POST, instance=book)
        if form.is_valid():
            form.save()
            messages.success(request, "Book updated.")
            return redirect("library:detail", pk=book.pk)
    else:
        form = BookForm(instance=book)
    return render(request, "library/edit.html", {"form": form, "book": book, "nav": "library"})


urlpatterns = [
    path("", browse, name="browse"),
    path("search/", search, name="search"),
    path("upload/", upload, name="upload"),
    path("upload/presign/", upload_presign, name="upload_presign"),
    path("upload/put/<path:key>/", upload_put, name="upload_put"),
    path("upload/complete/", upload_complete, name="upload_complete"),
    path("<int:pk>/", detail, name="detail"),
    path("<int:pk>/edit/", edit_book, name="edit"),
    path("<int:pk>/cover/", upload_cover, name="cover"),
]

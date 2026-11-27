"""
Reading views: the reader shell, Range-capable authenticated file serving,
bookmarks, reviews and history.

PDF files never touch a public URL. `/read/<id>/file/` checks the session,
serves byte ranges (the viewer streams), and writes a download audit row.
"""
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import (
    FileResponse,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.library.models import Book
from apps.library.storage import get_storage
from apps.reading.models import Bookmark, DownloadAudit, ReadingProgress, Review

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

CHUNK = 256 * 1024


def _parse_range(header: str, size: int):
    """Return (start, end) inclusive, or None for a full response."""
    match = RANGE_RE.match(header or "")
    if not match or (match.group(1) == "" and match.group(2) == ""):
        return None
    start_s, end_s = match.groups()
    if start_s == "":
        # suffix range: last N bytes
        length = int(end_s or 0)
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


@login_required
@require_GET
def reader(request, pk):
    """The reader page (a normal page inside the Cadence shell)."""
    book = get_object_or_404(Book, pk=pk)
    progress = ReadingProgress.objects.filter(user=request.user, book=book).first()
    from apps.rooms.models import ReadingRoom

    rooms = list(
        ReadingRoom.objects.filter(
            book=book, is_active=True, members__user=request.user
        ).select_related("owner")
    )
    bookmarks = Bookmark.objects.filter(user=request.user, book=book)
    from apps.library import capabilities

    intervals = capabilities.poll_intervals()
    return render(request, "reading/reader.html", {
        "nav": "library",
        "reader_mode": True,        # topbar shows the reader controls
        "reader_book": book,
        "book": book,
        "resume_page": (progress.last_position if progress else 1) or 1,
        "progress": progress,
        "rooms": rooms,
        "bookmarks": bookmarks,
        "POLL_ACTIVE_MS": intervals["active"],
        "POLL_ALONE_MS": intervals["alone"],
        "POLL_HIDDEN_MS": intervals["hidden"],
    })


@login_required
@require_GET
def serve_book_file(request, pk):
    """Authenticated, Range-capable PDF streaming. Audited per download."""
    book = get_object_or_404(Book, pk=pk)
    storage = get_storage()
    key = book.file_path
    try:
        size = book.file_size or storage.size(key)
    except FileNotFoundError:
        return HttpResponseBadRequest("Book file missing from storage.")

    DownloadAudit.objects.create(
        user=request.user, book=book, bytes_sent=0, range_request=bool(request.META.get("HTTP_RANGE"))
    )

    rng = _parse_range(request.META.get("HTTP_RANGE", ""), size)
    if rng:
        start, end = rng
        data = storage.open_range(key, start, end)
        resp = HttpResponse(data, status=206, content_type="application/pdf")
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp["Accept-Ranges"] = "bytes"
        resp["Content-Length"] = str(end - start + 1)
        resp["Cache-Control"] = "private, max-age=0, must-revalidate"
        return resp

    def stream():
        sent = 0
        while sent < size:
            chunk = storage.open_range(key, sent, min(sent + CHUNK - 1, size - 1))
            if not chunk:
                break
            sent += len(chunk)
            yield chunk

    resp = StreamingHttpResponse(stream(), content_type="application/pdf")
    resp["Content-Length"] = str(size)
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "private, max-age=0, must-revalidate"
    return resp


@login_required
@require_GET
def serve_cover(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if not book.cover_path:
        return HttpResponse(status=404)
    storage = get_storage()
    try:
        data = storage.open_range(book.cover_path, 0, None)
    except FileNotFoundError:
        return HttpResponse(status=404)
    resp = HttpResponse(data, content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=300"
    return resp


@login_required
@require_POST
def toggle_bookmark(request, pk):
    book = get_object_or_404(Book, pk=pk)
    page = int(request.POST.get("page", 0) or 0)
    if page < 1:
        return HttpResponseBadRequest("page required")
    bookmark = Bookmark.objects.filter(user=request.user, book=book, page_number=page).first()
    if bookmark:
        bookmark.delete()
        created = False
    else:
        Bookmark.objects.create(user=request.user, book=book, page_number=page)
        created = True
    if request.headers.get("HX-Request"):
        return render(request, "reading/_bookmark_state.html", {
            "book": book, "page": page, "created": created,
        })
    return redirect("reading:reader", pk=book.pk)


@login_required
@require_POST
def save_progress(request, pk):
    """Also reachable via the JSON sync API; kept for HTMX fallbacks."""
    book = get_object_or_404(Book, pk=pk)
    page = max(1, int(request.POST.get("page", 1) or 1))
    _update_progress(request.user, book, page)
    return JsonResponse({"ok": True})


def _update_progress(user, book, page: int) -> ReadingProgress:
    pages = book.pages or 1
    pct = round(min(100.0, max(0.0, (page / pages) * 100)), 2)
    progress, _created = ReadingProgress.objects.get_or_create(
        user=user, book=book, defaults={"last_position": page, "percentage": pct}
    )
    progress.last_position = page
    progress.percentage = pct
    progress.last_read = timezone.now()
    progress.save(update_fields=["last_position", "percentage", "last_read"])
    return progress


@login_required
@require_http_methods(["GET", "POST"])
def review(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        rating = int(request.POST.get("rating", 0) or 0)
        text = (request.POST.get("review_text") or "").strip()[:4000]
        if not 1 <= rating <= 5:
            return HttpResponseBadRequest("rating must be 1..5")
        rev, _created = Review.objects.update_or_create(
            user=request.user, book=book,
            defaults={"rating": rating, "review_text": text},
        )
        if request.headers.get("HX-Request"):
            return render(request, "reading/_review.html", {"review": rev, "book": book})
        return redirect("library:detail", pk=book.pk)
    return redirect("library:detail", pk=book.pk)


@login_required
@require_GET
def history(request):
    qs = ReadingProgress.objects.select_related("book").filter(user=request.user).order_by("-last_read")
    page_obj = Paginator(qs, 48).get_page(request.GET.get("page") or 1)
    bookmarks = Bookmark.objects.select_related("book").filter(user=request.user)[:20]
    return render(request, "reading/history.html", {
        "nav": "history", "page_obj": page_obj, "bookmarks": bookmarks,
    })

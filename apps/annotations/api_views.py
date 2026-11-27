"""
JSON annotation sync API — the only non-HTMX XHR surface in the app.

    GET  /api/reading/<book>/annotations/?room=<id|none>&page=<n>
    POST /api/reading/<book>/annotations/ops/
    GET  /api/reading/<book>/annotations/changes/?room=&after=

CSRF header (X-CSRFToken) required on POST; rate limited per user; the author
is always taken from the session (see serializers). This exception to the
"everything HTMX" rule is documented in docs/COLLABORATION.md.
"""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from apps.annotations import services
from apps.annotations.serializers import (
    PayloadError,
    annotation_to_public,
    change_to_public,
    validate_ops,
)
from apps.library.models import Book
from apps.rooms.models import ReadingRoom, RoomMember
from django.utils import timezone

from runtime.ratelimit import RateLimiter, RateLimitExceeded, limit_for

_limiter = RateLimiter()


def _layer(request, book, raw=None):
    """Resolve the target layer: room id or the user's private layer (None)."""
    if raw is None:
        raw = request.GET.get("room") or request.POST.get("room") or "none"
    if raw == "none":
        return None
    try:
        room_id = int(raw)
    except ValueError:
        return None
    room = get_object_or_404(ReadingRoom, pk=room_id, book=book, is_active=True)
    if not room.can_view(request.user):
        return None
    return room


def _touch_presence(request, room):
    """
    Presence piggybacks on the poll — throttled writes (page change or >60s),
    so 500 users polling every 3s do not exhaust the D1 write budget.
    """
    if room is None:
        return
    member = RoomMember.objects.filter(room=room, user=request.user).first()
    if member is None:
        return  # not a member (viewers added on join); presence is best-effort
    try:
        page = int(request.GET.get("page") or 0)
    except ValueError:
        page = 0
    stale = (
        member.last_seen is None
        or (timezone.now() - member.last_seen).total_seconds() > 60
    )
    if stale or (page and page != member.last_page):
        member.last_seen = timezone.now()
        if page:
            member.last_page = page
        member.save(update_fields=["last_seen", "last_page"])


def _participants(room):
    if room is None:
        return []
    return [
        {
            "user_id": m.user_id,
            "name": m.user.profile.label,
            "role": m.role,
            "page": m.last_page,
            "last_seen": m.last_seen.isoformat() if m.last_seen else None,
        }
        for m in room.members.select_related("user", "user__profile")[:50]
    ]


def _display_name(user) -> str:
    return user.profile.label


@login_required
@require_GET
def snapshot(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    room = _layer(request, book)
    try:
        page_index = int(request.GET.get("page") or 0) - 1
    except ValueError:
        page_index = 0
    want_page = request.GET.get("page")
    qs = services.layer_annotations(book, request.user, room)
    if want_page is not None:
        qs = qs.filter(page_index=max(0, page_index))
    rows = qs[:200]
    _touch_presence(request, room)
    return JsonResponse({
        "annotations": [
            annotation_to_public(
                a, a.author.profile.label,
                read_only=(room is not None and a.author_id != request.user.pk),
            )
            for a in rows
        ],
        "cursor": services._layer_cursor(book, room),
        "participants": _participants(room),
        "reset": False,
    })


@login_required
@require_http_methods(["POST"])
def ops(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    room = _layer(request, book, raw=str(body.get("room", "none")))
    if room is not None and not room.can_annotate(request.user):
        return JsonResponse({"error": "read-only room"}, status=403)
    raw_ops = body.get("ops")
    try:
        clean_ops = validate_ops(raw_ops)
    except PayloadError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    try:
        _limiter.check(
            f"annops:{request.user.pk}", *limit_for("annotation_ops")
        )
    except RateLimitExceeded:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)

    # Per-user-per-book cap (create ops only count new rows; check before apply).
    from apps.annotations.models import Annotation

    if any(op["op"] == "create" for op in clean_ops):
        count = Annotation.objects.filter(
            book=book, author=request.user, deleted_at=None
        ).count()
        if count >= int(getattr(settings, "ANNOTATION_MAX_PER_USER_BOOK", 5000)):
            return JsonResponse({"error": "annotation cap reached for this book"}, status=409)

    result = services.apply_ops(
        book=book, user=request.user, room=room,
        ops=clean_ops, display_name=_display_name(request.user),
    )
    _touch_presence(request, room)
    return JsonResponse(result.as_dict(_display_name(request.user)))


@login_required
@require_GET
def changes(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    room = _layer(request, book)
    try:
        after = int(request.GET.get("after") or 0)
    except ValueError:
        after = 0

    rows, cursor, reset = services.changes_since(
        book, room, after, request.user, services.change_horizon_id()
    )
    names = {}
    annotations_by_uid = {}
    if rows:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        ids = {r.actor_id for r in rows if r.actor_id}
        names = {
            u.pk: u.profile.label
            for u in User.objects.filter(pk__in=ids).select_related("profile")
        }
        # Attach the full object for create/update rows so the client can
        # import directly (deletes carry only the uid).
        from apps.annotations.models import Annotation

        live_uids = {
            r.annotation_uid for r in rows if r.op in {"create", "update"}
        }
        live = Annotation.objects.filter(
            book=book, uid__in=list(live_uids), deleted_at=None
        ).select_related("author", "author__profile")
        for annotation in live:
            annotations_by_uid[annotation.uid] = annotation_to_public(
                annotation, annotation.author.profile.label,
                read_only=(room is not None and annotation.author_id != request.user.pk),
            )
    _touch_presence(request, room)
    return JsonResponse({
        "cursor": cursor,
        "changes": [
            change_to_public(
                r, names.get(r.actor_id, "Someone"),
                annotation=annotations_by_uid.get(r.annotation_uid),
            )
            for r in rows
        ],
        "participants": _participants(room),
        "reset": reset,
    })


@login_required
@require_http_methods(["POST"])
def presence(request, book_id):
    """Explicit presence heartbeat (page change) — same throttled write."""
    book = get_object_or_404(Book, pk=book_id)
    room = _layer(request, book)
    _touch_presence(request, room)
    return JsonResponse({"participants": _participants(room)})

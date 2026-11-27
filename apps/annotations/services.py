"""
The annotation ops engine: applies client batches idempotently.

Conflict rules (docs/COLLABORATION.md):

* **create** — a uid may only be created once per (book, layer). Replaying the
  same create (reconnect) is a no-op. Creating someone else's uid conflicts.
* **update** — applies only when ``base_rev`` matches the server revision
  (optimistic concurrency). On mismatch the server copy is returned and the
  client re-imports it.
* **delete** — tombstones (``deleted_at``); deleting a parent tombstones its
  replies in one batch. Repeated deletes are no-ops.

Every applied mutation appends one AnnotationChange row (the poll cursor).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from apps.annotations.models import Annotation, AnnotationChange, ChangeOp
from apps.annotations.serializers import annotation_to_public
from apps.rooms.models import ReadingRoom


@dataclass
class OpsResult:
    applied: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    cursor: int = 0

    def as_dict(self, display_name: str) -> dict:
        # Conflicts carry full server copies for client re-import.
        return {
            "applied": self.applied,
            "conflicts": self.conflicts,
            "cursor": self.cursor,
        }


def _public(annotation: Annotation, display_name: str, viewer_id: int) -> dict:
    name = annotation.author.profile.label if annotation.author_id else display_name
    read_only = annotation.room_id is not None and annotation.author_id != viewer_id
    return annotation_to_public(annotation, name, read_only=read_only)


def apply_ops(*, book, user, room: ReadingRoom | None, ops: list[dict], display_name: str) -> OpsResult:
    """Apply a batch of validated ops. Small atomic units; idempotent writes."""
    result = OpsResult()
    now = timezone.now()

    for op in ops:
        kind = op["op"]
        uid = op["uid"]
        qs = Annotation.objects.filter(book=book, uid=uid)
        qs = qs.filter(room=room) if room else qs.filter(room__isnull=True)
        existing = qs.first()

        if kind == "create":
            _apply_create(result, op, existing, book, user, room, display_name)
        elif kind == "update":
            _apply_update(result, op, existing, user, now, display_name)
        elif kind == "delete":
            _apply_delete(result, op, existing, user, now, display_name)

    result.cursor = _layer_cursor(book, room)
    return result


def _layer_cursor(book, room) -> int:
    qs = AnnotationChange.objects.filter(book=book)
    qs = qs.filter(room=room) if room else qs.filter(room__isnull=True)
    return qs.order_by("-id").values_list("id", flat=True).first() or 0


def _log_change(annotation: Annotation, op: str, actor) -> None:
    AnnotationChange.objects.create(
        annotation=annotation,
        annotation_uid=annotation.uid,
        book_id=annotation.book_id,
        room_id=annotation.room_id,
        op=op,
        revision=annotation.revision,
        actor=actor,
    )


def _apply_create(result, op, existing, book, user, room, display_name):
    if existing is None:
        annotation = Annotation.objects.create(
            uid=op["uid"],
            book=book,
            room=room,
            author=user,
            page_index=op["page_index"],
            subtype=op["subtype"],
            parent_uid=op["parent_uid"],
            text=op["text"],
            payload=op["payload"],
            revision=1,
        )
        _log_change(annotation, ChangeOp.CREATE, user)
        result.applied.append(op["uid"])
        return
    if existing.author_id == user.pk and existing.deleted_at is None:
        # Idempotent replay of our own create (e.g. after a reconnect).
        result.applied.append(op["uid"])
        return
    result.conflicts.append(_public(existing, display_name, user.pk))


def _apply_update(result, op, existing, user, now, display_name):
    if existing is None or existing.deleted_at is not None:
        result.conflicts.append({"uid": op["uid"], "deleted": True, "revision": 0})
        return
    if existing.author_id != user.pk and not user.profile.can_moderate_rooms():
        result.conflicts.append(_public(existing, display_name, user.pk))
        return
    if op["base_rev"] is not None and op["base_rev"] != existing.revision:
        result.conflicts.append(_public(existing, display_name, user.pk))
        return
    existing.page_index = op["page_index"]
    existing.subtype = op["subtype"]
    existing.parent_uid = op["parent_uid"]
    existing.text = op["text"]
    existing.payload = op["payload"]
    existing.revision += 1
    existing.updated_at = now
    existing.save(update_fields=[
        "page_index", "subtype", "parent_uid", "text", "payload",
        "revision", "updated_at",
    ])
    _log_change(existing, ChangeOp.UPDATE, user)
    result.applied.append(op["uid"])


def _apply_delete(result, op, existing, user, now, display_name):
    if existing is None:
        # Deleting something unknown is a no-op (idempotent).
        result.applied.append(op["uid"])
        return
    if existing.author_id != user.pk and not user.profile.can_moderate_rooms():
        result.conflicts.append(_public(existing, display_name, user.pk))
        return
    if existing.deleted_at is None:
        existing.deleted_at = now
        existing.revision += 1
        existing.save(update_fields=["deleted_at", "revision", "updated_at"])
        _log_change(existing, ChangeOp.DELETE, user)
        # Parent delete tombstones its replies in the same batch.
        replies = Annotation.objects.filter(
            book_id=existing.book_id, parent_uid=existing.uid, deleted_at=None
        )
        for reply in replies:
            reply.deleted_at = now
            reply.revision += 1
            reply.save(update_fields=["deleted_at", "revision", "updated_at"])
            _log_change(reply, ChangeOp.DELETE, user)
    result.applied.append(op["uid"])


def layer_annotations(book, user, room: ReadingRoom | None, page_index: int | None = None):
    """Snapshot queryset for one layer (private: own rows only)."""
    qs = Annotation.objects.filter(book=book, deleted_at=None).select_related(
        "author", "author__profile"
    )
    if room:
        qs = qs.filter(room=room)
    else:
        qs = qs.filter(room__isnull=True, author=user)
    if page_index is not None:
        qs = qs.filter(page_index=page_index)
    return qs.order_by("page_index", "id")


def changes_since(book, room, after: int, user, horizon_id: int):
    """
    The poll query: change rows after ``after`` for the layer.

    Returns (rows, cursor, reset). If the client cursor predates the compaction
    horizon the client gets reset=True and must do a full resync.
    """
    qs = AnnotationChange.objects.filter(book=book, id__gt=after)
    qs = qs.filter(room=room) if room else qs.filter(room__isnull=True, actor=user)
    if not room:
        # Private layer: only the user's own change rows are ever visible.
        qs = qs.filter(actor=user)
    rows = list(qs.order_by("id")[:200])
    cursor = rows[-1].id if rows else after
    reset = bool(after and after < horizon_id)
    return rows, cursor, reset


def change_horizon_id() -> int:
    """
    Lowest surviving change id.

    Compaction deletes old rows, so the minimum id rises over time. A client
    whose cursor predates it missed rows and must do a full resync
    (``reset: true``). 0 when the feed is empty or never compacted.
    """
    return (
        AnnotationChange.objects.order_by("id").values_list("id", flat=True).first() or 0
    )

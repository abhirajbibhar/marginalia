"""
Annotations: the private layer and the room layers, plus the append-only
change log that powers collaboration sync.

Design (validated in docs/PHASE0.md §3/§5):

* ``uid`` is the engine annotation id (EmbedPDF keeps it stable across
  export/import), so client and server key the same way.
* Replies are ordinary annotations with ``parent_uid`` set (engine field
  ``inReplyToId``). Deleting a parent tombstones its replies in one batch.
* ``text`` mirrors the engine's ``contents`` (comment text) for search and
  server-side rendering; ``payload`` stores the full annotation object so a
  reload re-imports without loss (golden test: export → store → import).
* ``revision`` implements optimistic concurrency: updates apply only when the
  client's ``base_rev`` matches; deletes are tombstones (``deleted_at``) so
  late syncs converge.
* ``AnnotationChange`` is the cursor-based change feed (its autoincrement id is
  the cursor). Rows older than the compaction horizon are pruned by the
  ``compact_annotation_changes`` command.
"""
from django.conf import settings
from django.db import models

from apps.library.models import Book


class AnnotationSubtype(models.TextChoices):
    """Whitelisted annotation kinds (validated server-side)."""

    MARKUP = "markup", "Markup"          # highlight/underline/strikeout/squiggly
    INK = "ink", "Ink"
    SHAPE = "shape", "Shape"            # square/circle/line/arrow/polygon/polyline
    FREE_TEXT = "free_text", "Free text"
    TEXT_NOTE = "text_note", "Sticky note"
    STAMP = "stamp", "Stamp"            # size-capped


class Annotation(models.Model):
    uid = models.CharField(max_length=64)  # engine annotation id
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="annotations")
    room = models.ForeignKey(
        "rooms.ReadingRoom", null=True, blank=True, on_delete=models.CASCADE,
        related_name="annotations",
    )  # NULL = the author's private layer
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="annotations"
    )
    page_index = models.PositiveIntegerField(default=0)  # 0-based engine page index
    subtype = models.CharField(max_length=16, choices=AnnotationSubtype.choices)
    parent_uid = models.CharField(max_length=64, blank=True, default="")  # reply parent
    text = models.TextField(blank=True)  # engine `contents` (comment text)
    payload = models.JSONField(default=dict)  # full PdfAnnotationObject
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["book", "room", "deleted_at"]),
            models.Index(fields=["author", "book"]),
            models.Index(fields=["parent_uid"]),
        ]
        constraints = [
            # unique (book, room, uid) — two partial unique indexes because
            # NULL room rows must also be unique (SQLite treats NULLs as
            # distinct in plain UNIQUE constraints).
            models.UniqueConstraint(
                fields=["book", "room", "uid"],
                condition=models.Q(room__isnull=False),
                name="uniq_annotation_book_room_uid",
            ),
            models.UniqueConstraint(
                fields=["book", "uid"],
                condition=models.Q(room__isnull=True),
                name="uniq_annotation_book_uid_private",
            ),
        ]

    @property
    def is_reply(self) -> bool:
        return bool(self.parent_uid)

    @property
    def layer_key(self) -> str:
        return f"room:{self.room_id}" if self.room_id else "none"

    def __str__(self) -> str:
        where = self.layer_key
        return f"{self.uid} [{where}] p{self.page_index}"


class ChangeOp(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"


class AnnotationChange(models.Model):
    """
    Append-only change feed. ``id`` is the sync cursor.

    ``annotation_uid`` is denormalized so change rows stay meaningful after the
    annotation itself is tombstoned (and after compaction of old rows).
    """

    id = models.BigAutoField(primary_key=True)  # the cursor
    annotation = models.ForeignKey(
        Annotation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="changes",
    )
    annotation_uid = models.CharField(max_length=64)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="changes")
    room = models.ForeignKey(
        "rooms.ReadingRoom", null=True, blank=True, on_delete=models.CASCADE,
        related_name="changes",
    )
    op = models.CharField(max_length=8, choices=ChangeOp.choices)
    revision = models.PositiveIntegerField(default=1)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="annotation_changes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["book", "id"]),   # hot poll path
            models.Index(fields=["room", "id"]),   # room poll (covering-ish)
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"#{self.id} {self.op} {self.annotation_uid}"

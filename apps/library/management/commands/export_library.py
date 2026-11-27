"""
export_library — full data export (JSON), chunked so it works on D1.

Exports catalogue (books, authors, series, categories, tags), collections,
reading state (progress, bookmarks, reviews), annotations (incl. replies and
payloads) and rooms (incl. members). Storage keys are exported verbatim — blobs
travel with `scripts/r2_sync.py` (or by copying media/ locally).

Usage:
    python manage.py export_library > library.json
    python manage.py export_library --output library.json
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import ManyToManyField
from django.forms.models import model_to_dict

CHUNK = 200  # stays well under D1's read/param budgets


def serialize(instance) -> dict:
    """model_to_dict with M2M fields exported as pk lists (JSON-safe)."""
    item = model_to_dict(instance)
    for field in instance._meta.get_fields():
        if isinstance(field, ManyToManyField) and field.name in item:
            item[field.name] = [related.pk for related in getattr(instance, field.name).all()]
    return item


def chunked(qs):
    last = 0
    while True:
        rows = list(qs.filter(pk__gt=last).order_by("pk")[:CHUNK])
        if not rows:
            return
        yield rows
        last = rows[-1].pk


class Command(BaseCommand):
    help = "Export the whole library (metadata + annotations + rooms) as JSON."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="-")

    def handle(self, *args, **options):
        from apps.accounts.models import Profile
        from apps.annotations.models import Annotation, AnnotationChange
        from apps.authors.models import Author
        from apps.collections.models import Collection
        from apps.library.models import Book, Category, Tag
        from apps.reading.models import Bookmark, ReadingProgress, Review
        from apps.rooms.models import ReadingRoom, RoomMember
        from apps.series.models import Series

        data = {
            "format": "marginalia-export-v1",
            "users": [],
            "authors": [], "series": [], "categories": [], "tags": [], "books": [],
            "collections": [], "progress": [], "bookmarks": [], "reviews": [],
            "rooms": [], "room_members": [], "annotations": [],
        }
        for rows in chunked(Profile.objects.all()):
            for profile in rows:
                data["users"].append(
                    serialize(profile)
                    | {"username": profile.user.username, "email": profile.user.email}
                )

        def dump(qs, key, fields=None):
            for rows in chunked(qs):
                for row in rows:
                    item = serialize(row)
                    if fields:
                        item = {f: item.get(f) for f in fields}
                    data[key].append(item)

        dump(Author.objects.all(), "authors")
        dump(Series.objects.all(), "series")
        dump(Category.objects.all(), "categories")
        dump(Tag.objects.all(), "tags")
        dump(Book.objects.all(), "books")
        dump(Collection.objects.all(), "collections")
        dump(ReadingProgress.objects.all(), "progress")
        dump(Bookmark.objects.all(), "bookmarks")
        dump(Review.objects.all(), "reviews")
        dump(ReadingRoom.objects.all(), "rooms")
        dump(RoomMember.objects.all(), "room_members")
        dump(Annotation.objects.all(), "annotations")

        output = options["output"]
        text = json.dumps(data, indent=1, default=str)
        if output == "-":
            self.stdout.write(text)
        else:
            with open(output, "w") as fh:
                fh.write(text)
            self.stderr.write(self.style.SUCCESS(f"Wrote {output}"))

"""
import_library — restore an export produced by `export_library`.

Writes in small idempotent chunks (D1-safe: no transactions, no big
multi-row statements). Existing rows (matched by natural keys) are updated,
missing rows created — import can be re-run safely.

Usage:
    python manage.py import_library library.json
"""
import json

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Import a library export (JSON) — chunked and idempotent."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        from apps.accounts.models import Profile
        from apps.annotations.models import Annotation
        from apps.authors.models import Author
        from apps.collections.models import Collection
        from apps.library.models import Book, Category, Tag
        from apps.reading.models import Bookmark, ReadingProgress, Review
        from apps.rooms.models import ReadingRoom, RoomMember
        from apps.series.models import Series

        with open(options["path"]) as fh:
            data = json.load(fh)
        if data.get("format") != "marginalia-export-v1":
            raise SystemExit("not a margialia export")

        User = get_user_model()
        users_by_pk = {}
        for item in data.get("users", []):
            user, _ = User.objects.get_or_create(
                username=item["username"], defaults={"email": item.get("email", "")}
            )
            profile, _ = Profile.objects.get_or_create(user=user)
            for field in ("role", "display_name", "avatar", "theme", "default_layer"):
                if item.get(field):
                    setattr(profile, field, item[field])
            profile.save()
            users_by_pk[item["id"]] = profile

        def upsert(model, rows, key_fields, m2m=None):
            from django.db.models import ForeignKey

            m2m = m2m or []
            fk_names = {
                f.name for f in model._meta.get_fields() if isinstance(f, ForeignKey)
            }
            for item in rows:
                lookup = {f: item[f] for f in key_fields}
                defaults = {}
                for k, v in item.items():
                    if k in key_fields or k == "id" or k in m2m:
                        continue
                    # model_to_dict returns raw pks for FKs; map to <name>_id.
                    if k in fk_names and not hasattr(v, "pk"):
                        defaults[f"{k}_id"] = v
                    else:
                        defaults[k] = v
                obj, _ = model.objects.update_or_create(**lookup, defaults=defaults)
                for field in m2m:
                    ids = item.get(field) or []
                    getattr(obj, field).set(ids)

        upsert(Author, data.get("authors", []), ["name"])
        upsert(Series, data.get("series", []), ["name"])
        upsert(Category, data.get("categories", []), ["name"])
        upsert(Tag, data.get("tags", []), ["name"])
        upsert(Book, data.get("books", []), ["file_path"],
               m2m=["authors", "categories", "tags", "collections"])
        upsert(Collection, data.get("collections", []), ["owner", "name"],
               m2m=["books", "members"])
        upsert(ReadingProgress, data.get("progress", []), ["user", "book"])
        upsert(Bookmark, data.get("bookmarks", []), ["user", "book", "page_number"])
        upsert(Review, data.get("reviews", []), ["user", "book"])
        upsert(ReadingRoom, data.get("rooms", []), ["book", "name"])
        upsert(RoomMember, data.get("room_members", []), ["room", "user"])

        # Annotations: uid is the natural key (book, layer, uid).
        for item in data.get("annotations", []):
            lookup = {"book_id": item["book"], "uid": item["uid"]}
            if item.get("room"):
                lookup["room_id"] = item["room"]
            defaults = {
                "author_id": users_by_pk[item["author"]].user_id
                if item["author"] in users_by_pk else item["author"],
                "page_index": item.get("page_index", 0),
                "subtype": item.get("subtype", "markup"),
                "parent_uid": item.get("parent_uid", ""),
                "text": item.get("text", ""),
                "payload": item.get("payload", {}),
                "revision": item.get("revision", 1),
                "deleted_at": item.get("deleted_at"),
            }
            Annotation.objects.update_or_create(**lookup, defaults=defaults)

        self.stderr.write(self.style.SUCCESS("Import complete."))

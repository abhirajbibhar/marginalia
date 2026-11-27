"""
BookStorage: the single boundary between the app and blob storage.

Two implementations, chosen by target:

* LocalStorage — the filesystem under MEDIA_ROOT (books/…, covers/…)
* R2Storage    — Cloudflare R2 through the django-cf storage backend + binding

The database only ever stores **keys** (Book.file_path / Book.cover_path).
Blobs never pass through the DB and never through Worker memory except in
bounded, ranged chunks (see pdffile.RangeReader).
"""
from __future__ import annotations

import os
from typing import BinaryIO, Protocol

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def book_key(filename: str) -> str:
    """Random, collision-free storage key under books/."""
    import secrets

    stem, ext = os.path.splitext(filename)
    safe = "".join(c for c in stem.lower() if c.isalnum() or c in "-_")[:40] or "book"
    return f"books/{safe}-{secrets.token_hex(8)}{ext.lower() or '.pdf'}"


def cover_key(book_key_or_id, ext: str = ".jpg") -> str:
    import secrets

    return f"covers/{book_key_or_id}-{secrets.token_hex(6)}{ext}"


class BookStorage(Protocol):
    """The interface every storage backend implements."""

    def save(self, key: str, content: BinaryIO | bytes) -> str: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int: ...
    def delete(self, key: str) -> None: ...
    def url(self, key: str) -> str: ...
    def open_range(self, key: str, start: int, end: int | None) -> bytes: ...
    def presign_put(self, key: str, expires_seconds: int = 900) -> str | None: ...


class LocalStorage:
    """Filesystem storage (self-hosted target)."""

    def save(self, key: str, content: BinaryIO | bytes) -> str:
        data = content if isinstance(content, (bytes, bytearray)) else content.read()
        if default_storage.exists(key):
            default_storage.delete(key)
        return default_storage.save(key, ContentFile(data))

    def exists(self, key: str) -> bool:
        return default_storage.exists(key)

    def size(self, key: str) -> int:
        return default_storage.size(key)

    def delete(self, key: str) -> None:
        default_storage.delete(key)

    def url(self, key: str) -> str:
        return default_storage.url(key)

    def open_range(self, key: str, start: int, end: int | None) -> bytes:
        with default_storage.open(key, "rb") as fh:
            fh.seek(start)
            if end is None:
                return fh.read()
            return fh.read(end - start + 1)

    def presign_put(self, key: str, expires_seconds: int = 900) -> str | None:
        # Local uploads go through the Django upload endpoint instead.
        return None


class R2Storage:
    """
    Cloudflare R2 through the binding (django_cf.storage.R2Storage manages
    standard storage calls; ranged reads and presigning are implemented here
    against the same keys).
    """

    def __init__(self):
        self._storage = default_storage

    def save(self, key: str, content: BinaryIO | bytes) -> str:
        data = content if isinstance(content, (bytes, bytearray)) else content.read()
        if self._storage.exists(key):
            self._storage.delete(key)
        return self._storage.save(key, ContentFile(data))

    def exists(self, key: str) -> bool:
        return self._storage.exists(key)

    def size(self, key: str) -> int:
        return self._storage.size(key)

    def delete(self, key: str) -> None:
        self._storage.delete(key)

    def url(self, key: str) -> str:
        # The bucket is private. Files are served through authenticated views
        # (/read/<id>/file/); storage URLs are never exposed to the browser.
        return f"/media/{key}"

    def open_range(self, key: str, start: int, end: int | None) -> bytes:
        from workers import env  # noqa: import inside function: Worker-only

        binding_name = getattr(settings, "R2_BINDING", "BUCKET")
        bucket = getattr(env, binding_name)
        full_key = key if not key.startswith("media/") else key
        options = {}
        if end is not None:
            options["range"] = {"offset": start, "length": end - start + 1}
        elif start:
            options["range"] = {"offset": start}
        obj = bucket.get(full_key, options=options) if options else bucket.get(full_key)
        if obj is None:
            raise FileNotFoundError(key)
        return obj.array_buffer().to_bytes() if hasattr(obj, "array_buffer") else bytes(obj)

    def presign_put(self, key: str, expires_seconds: int = 900) -> str | None:
        from apps.library.upload import presign_put_url

        return presign_put_url(key, expires_seconds)


def get_storage() -> BookStorage:
    """Return the storage implementation for the active target."""
    from apps.library import capabilities

    return R2Storage() if capabilities.storage_backend() == "r2" else LocalStorage()

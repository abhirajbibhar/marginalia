"""
PDF metadata extraction with pypdf (pure Python → runs under Pyodide and
CPython alike).

Bounds: pypdf only needs the trailer/xref/info dict; RangeReader enforces I/O
budgets, and extraction is wrapped so any pypdf failure degrades to empty
metadata instead of a 500. Never trust extracted values — the librarian
reviews the pre-filled form.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BookMetadata:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    subject: str = ""
    keywords: str = ""
    pages: int = 0
    encrypted: bool = False
    producer: str = ""
    creation_date: str = ""


def extract_metadata(fh) -> BookMetadata:
    """Extract bounded metadata from a seekable PDF file object."""
    meta = BookMetadata()
    try:
        from pypdf import PdfReader
    except Exception:
        return meta

    try:
        reader = PdfReader(fh, strict=False)
        meta.encrypted = reader.is_encrypted
        if meta.encrypted:
            return meta  # never decrypt; the caller flags encrypted files
        meta.pages = len(reader.pages)
        info = reader.metadata
        if info:
            meta.title = _clean(info.get("/Title"))
            meta.subject = _clean(info.get("/Subject"))
            meta.producer = _clean(info.get("/Producer"))
            raw_author = _clean(info.get("/Author"))
            if raw_author:
                # Split common multi-author conventions.
                for part in raw_author.replace(";", ",").split(","):
                    name = part.strip()
                    if name:
                        meta.authors.append(name[:200])
            date = info.get("/CreationDate")
            if date:
                meta.creation_date = _clean(str(date))[:40]
            keywords = _clean(info.get("/Keywords"))
            if keywords:
                meta.keywords = keywords[:500]
    except Exception:
        # Any parse failure → treat as "no metadata"; validation separately
        # decides whether the file is acceptable.
        return BookMetadata()
    return meta


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    return text[:500]

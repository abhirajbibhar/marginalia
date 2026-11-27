"""
Server-side PDF validation.

Checks (in order, all bounded):

1. extension must be ``.pdf``
2. ``%PDF-`` magic bytes near the start of the stream
3. size cap ``MAX_PDF_SIZE_MB``
4. page cap ``MAX_PDF_PAGES`` (cheaply, via pypdf metadata extraction)
5. encrypted files are rejected (flagged, never decrypted)
6. dangerous constructs are flagged by a streaming scan: ``/JavaScript``,
   ``/Launch``, ``/EmbeddedFiles``

The scan reads in fixed windows through a file-like object, so it works for
local files and R2 objects alike without loading the whole file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from django.conf import settings

MAGIC = b"%PDF-"
DANGEROUS_TOKENS = (b"/JavaScript", b"/Launch", b"/EmbeddedFiles")
SCAN_WINDOW = 1024 * 1024


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    encrypted: bool = False

    def fail(self, message: str) -> "ValidationResult":
        self.ok = False
        self.errors.append(message)
        return self


def validate_filename(filename: str) -> ValidationResult:
    result = ValidationResult()
    if not filename.lower().endswith(".pdf"):
        result.fail("Only .pdf files are accepted.")
    if os.path.basename(filename).startswith("."):
        result.fail("Hidden files are not accepted.")
    return result


def validate_magic(fh, result: ValidationResult | None = None) -> ValidationResult:
    result = result or ValidationResult()
    head = fh.read(1024)
    if MAGIC not in head[:1024]:
        result.fail("File does not look like a PDF (missing %PDF- header).")
    fh.seek(0)
    return result


def validate_size(size: int, result: ValidationResult | None = None) -> ValidationResult:
    result = result or ValidationResult()
    cap_mb = int(getattr(settings, "MAX_PDF_SIZE_MB", 200))
    if size <= 0:
        result.fail("Empty file.")
    elif size > cap_mb * 1024 * 1024:
        result.fail(f"File exceeds the {cap_mb} MB limit.")
    return result


def scan_dangerous(fh, result: ValidationResult | None = None) -> ValidationResult:
    """Streaming scan for dangerous constructs (bounded by window reads)."""
    result = result or ValidationResult()
    fh.seek(0)
    overlap = b""
    while True:
        chunk = fh.read(SCAN_WINDOW)
        if not chunk:
            break
        data = overlap + chunk
        for token in DANGEROUS_TOKENS:
            if token in data:
                result.warnings.append(
                    f"Flagged construct {token.decode()} present; manual review required."
                )
                # de-duplicate and keep scanning cheaply
                DANGEROUS = set(result.warnings)
                result.warnings = sorted(DANGEROUS)
                return result
        overlap = data[-32:]
    fh.seek(0)
    return result


def validate_pdf(fh, size: int, filename: str = "upload.pdf") -> ValidationResult:
    """Run the full battery against a seekable binary file object."""
    result = validate_filename(filename)
    result = validate_size(size, result)
    if not result.ok:
        return result
    result = validate_magic(fh, result)
    if not result.ok:
        return result
    result = scan_dangerous(fh, result)

    # Page cap + encryption check via bounded metadata extraction.
    from apps.library.metadata import extract_metadata

    meta = extract_metadata(fh)
    result.encrypted = meta.encrypted
    result.pages = meta.pages
    if meta.encrypted:
        result.fail("Encrypted PDFs are not accepted.")
    if meta.pages and meta.pages > int(getattr(settings, "MAX_PDF_PAGES", 5000)):
        result.fail(f"PDF has {meta.pages} pages; the cap is {getattr(settings, 'MAX_PDF_PAGES')}.")
    return result

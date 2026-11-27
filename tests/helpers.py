"""Shared test helpers: users with roles, a fake PDF, book fixtures."""
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import override_settings

from apps.accounts.models import Profile, Role
from apps.library.models import Book

# A minimal, valid single-page PDF (hand-built; pypdf can parse it).
MINI_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
)


def make_user(username: str, role: str = Role.MEMBER) -> User:
    user = User.objects.create_user(username=username, password="test-password-123")
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.role = role
    profile.display_name = username.title()
    profile.save()
    # Django caches the reverse OneToOne on assignment; clear it so
    # user.profile reflects the saved row (same fix as accounts.profile_for).
    user.refresh_from_db()
    return user


def make_book(title: str = "Test Book", **kwargs) -> Book:
    return Book.objects.create(
        title=title,
        file_path=kwargs.pop("file_path", f"books/{title.lower().replace(' ', '-')}.pdf"),
        pages=kwargs.pop("pages", 10),
        **kwargs,
    )


def make_pdf_bytes(encrypted: bool = False, javascript: bool = False, pages: int = 1) -> bytes:
    if not encrypted and not javascript:
        return MINI_PDF
    data = MINI_PDF
    if javascript:
        data += b"\n% /JavaScript /Launch /EmbeddedFiles\n"
    return data

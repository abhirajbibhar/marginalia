"""
Storage + validation contract tests (run on every backend): real SQLite and a
temp directory locally; the same interface is exercised on D1/R2 via
`wrangler dev --local` in CI (docs/PARITY.md).

Also covers the PDF validation battery and the portability capability flags.
"""
import io
import os
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from apps.library import capabilities
from apps.library.pdffile import BudgetExceeded, RangeReader
from apps.library.storage import LocalStorage, book_key, cover_key, get_storage
from apps.library.validation import validate_pdf
from tests.helpers import MINI_PDF, make_pdf_bytes


class StorageContractTests(TestCase):
    """Every BookStorage implementation must satisfy this contract."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="marginalia-media-")
        self.override = override_settings(MEDIA_ROOT=self.tmp)
        self.override.enable()
        self.storage = LocalStorage()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_exists_size_delete_round_trip(self):
        key = book_key("Test Book.pdf")
        self.assertTrue(key.startswith("books/"))
        self.assertTrue(key.endswith(".pdf"))
        self.assertFalse(self.storage.exists(key))
        returned = self.storage.save(key, ContentFile(MINI_PDF))
        self.assertTrue(self.storage.exists(returned))
        self.assertEqual(self.storage.size(returned), len(MINI_PDF))
        self.assertEqual(self.storage.open_range(returned, 0, 3), b"%PDF")
        self.assertEqual(self.storage.open_range(returned, 2, None), MINI_PDF[2:])
        self.storage.delete(returned)
        self.assertFalse(self.storage.exists(returned))

    def test_keys_are_random(self):
        self.assertNotEqual(book_key("a.pdf"), book_key("a.pdf"))
        self.assertTrue(cover_key(42).startswith("covers/"))

    def test_presign_returns_none_locally(self):
        self.assertIsNone(self.storage.presign_put(book_key("x.pdf")))

    def test_get_storage_respects_target(self):
        self.assertIsInstance(get_storage(), LocalStorage)
        with override_settings(DEPLOYMENT_TARGET="cloudflare"):
            self.assertFalse(capabilities.supports_transactions())
            self.assertEqual(capabilities.storage_backend(), "r2")


class RangeReaderBudgetTests(SimpleTestCase):
    def test_budget_exceeded(self):
        class HugeStorage:
            def open_range(self, key, start, end):
                return b"x" * 100

        reader = RangeReader(HugeStorage(), "books/big.pdf", 10_000_000)
        with self.assertRaises(BudgetExceeded):
            reader.read(50_000_000)


class PdfValidationTests(SimpleTestCase):
    def test_accepts_valid_pdf(self):
        result = validate_pdf(io.BytesIO(MINI_PDF), len(MINI_PDF), "ok.pdf")
        self.assertTrue(result.ok, result.errors)

    def test_rejects_wrong_extension(self):
        result = validate_pdf(io.BytesIO(MINI_PDF), len(MINI_PDF), "evil.epub")
        self.assertFalse(result.ok)

    def test_rejects_bad_magic(self):
        result = validate_pdf(io.BytesIO(b"PK\x03\x04 not a pdf"), 16, "fake.pdf")
        self.assertFalse(result.ok)

    def test_rejects_oversized(self):
        with override_settings(MAX_PDF_SIZE_MB=1):
            result = validate_pdf(io.BytesIO(MINI_PDF), 2 * 1024 * 1024, "big.pdf")
            self.assertFalse(result.ok)

    def test_flags_dangerous_constructs(self):
        data = make_pdf_bytes(javascript=True)
        result = validate_pdf(io.BytesIO(data), len(data), "danger.pdf")
        self.assertTrue(result.ok)  # flagged, not necessarily rejected
        self.assertTrue(any("JavaScript" in w for w in result.warnings))

    def test_encrypted_rejected(self):
        # Encrypted detection goes through pypdf; simulate with a stub reader.
        import apps.library.metadata as metadata

        class FakeMeta:
            encrypted = True
            pages = 3

        original = metadata.extract_metadata
        metadata.extract_metadata = lambda fh: FakeMeta()
        try:
            result = validate_pdf(io.BytesIO(MINI_PDF), len(MINI_PDF), "locked.pdf")
        finally:
            metadata.extract_metadata = original
        self.assertFalse(result.ok)


class CapabilityTests(SimpleTestCase):
    def test_local_capabilities(self):
        with override_settings(DEPLOYMENT_TARGET="local", FEATURE_REALTIME_PUSH="0"):
            self.assertTrue(capabilities.is_local())
            self.assertTrue(capabilities.supports_transactions())
            self.assertEqual(capabilities.storage_backend(), "local")
            self.assertFalse(capabilities.supports_realtime_push())

    def test_cloudflare_capabilities(self):
        with override_settings(DEPLOYMENT_TARGET="cloudflare"):
            self.assertTrue(capabilities.is_cloudflare())
            self.assertFalse(capabilities.supports_transactions())
            self.assertEqual(capabilities.storage_backend(), "r2")
            self.assertFalse(capabilities.supports_realtime_push())
            caps = capabilities.describe()
            self.assertEqual(caps["target"], "cloudflare")

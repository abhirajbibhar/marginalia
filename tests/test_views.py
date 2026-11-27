"""
View tests: page smoke, HTMX partial (HX-Request), and the role-permission
matrix (Admin / Librarian / Member) for every sensitive surface.
"""
from django.test import TestCase

from apps.accounts.models import Role
from tests.helpers import make_book, make_user


class PageSmokeTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.user = make_user("membro", Role.MEMBER)
        self.client.force_login(self.user)

    def test_all_pages_render(self):
        urls = [
            "/", "/library/", f"/library/{self.book.pk}/", "/library/search/?q=test",
            "/authors/", "/series/", "/collections/", "/rooms/", "/annotations/",
            "/read/history/", "/accounts/profile/", f"/read/{self.book.pk}/",
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"{url} -> {response.status_code}")

    def test_reader_uses_contract_shell(self):
        response = self.client.get(f"/read/{self.book.pk}/")
        html = response.content.decode()
        self.assertIn('class="is-reader', html)          # body.is-reader
        self.assertIn("page page-reader", html)          # main#main class chain
        self.assertIn('id="pdf-viewer"', html)           # mount
        self.assertNotIn("page-head", html)              # .page-head omitted
        self.assertNotIn("reader-bar", html)             # no bar under the site header
        # Reader controls live in the one site header (topbar):
        self.assertIn('id="syncChip"', html)
        self.assertIn('id="bookmarkBtn"', html)
        self.assertIn("reader-layers", html)

    def test_htmx_partial_returns_fragment_only(self):
        response = self.client.get("/library/", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("book-card", html)                 # appendable items
        self.assertNotIn("<html", html)                  # fragment, not the full shell
        self.assertNotIn('id="book-results"', html)      # no nested results wrapper

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/library/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class RolePermissionMatrixTests(TestCase):
    """server-side role checks on every sensitive endpoint."""

    def setUp(self):
        self.book = make_book()
        self.admin = make_user("admin", Role.ADMIN)
        self.librarian = make_user("lib", Role.LIBRARIAN)
        self.member = make_user("mem", Role.MEMBER)

    def _as(self, user):
        self.client.force_login(user)
        return self.client

    def test_upload_page(self):
        for user, ok in [(self.admin, True), (self.librarian, True), (self.member, False)]:
            response = self._as(user).get("/library/upload/")
            self.assertEqual(response.status_code, 200 if ok else 400, user.username)

    def test_upload_presign(self):
        payload = '{"filename": "a.pdf", "size": 1000}'
        for user, ok in [(self.librarian, True), (self.member, False)]:
            response = self._as(user).post(
                "/library/upload/presign/", data=payload, content_type="application/json"
            )
            self.assertEqual(response.status_code, 200 if ok else 403, user.username)

    def test_admin_dashboard(self):
        for user, ok in [(self.admin, True), (self.librarian, False), (self.member, False)]:
            response = self._as(user).get("/manage/")
            self.assertEqual(response.status_code, 200 if ok else 403, user.username)

    def test_book_edit_is_librarian_only(self):
        for user, ok in [(self.librarian, True), (self.member, False)]:
            response = self._as(user).get(f"/library/{self.book.pk}/edit/")
            self.assertEqual(response.status_code, 200 if ok else 400, user.username)

    def test_tasks_endpoint_needs_secret(self):
        from django.test import Client

        client = Client()
        response = client.post("/manage/tasks/")
        self.assertEqual(response.status_code, 403)
        with self.settings():
            import os

            os.environ["TASKS_SECRET"] = "s3cret"
            from runtime import cache as runtime_cache

            runtime_cache.clear()  # ensure the module reads env fresh
            response = client.post("/manage/tasks/", HTTP_X_TASKS_SECRET="s3cret")
            self.assertEqual(response.status_code, 200)
            os.environ.pop("TASKS_SECRET")

    def test_private_annotations_hidden_from_admin_surface(self):
        """Admins may delete user data but must not read private notes."""
        from apps.annotations.models import Annotation

        Annotation.objects.create(
            uid="private-1", book=self.book, author=self.member,
            page_index=0, subtype="text_note", text="very private",
            payload={"id": "private-1"},
        )
        self.client.force_login(self.admin)
        response = self.client.get("/admin/annotations/annotation/")
        self.assertNotIn("very private", response.content.decode())


class FileServingTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.user = make_user("reader")
        self.client.force_login(self.user)

    def test_range_request_returns_206(self):
        from django.core.files.base import ContentFile

        from apps.library.storage import get_storage

        storage = get_storage()
        storage.save(self.book.file_path, ContentFile(b"0123456789"))
        self.book.file_size = 10
        self.book.save(update_fields=["file_size"])
        response = self.client.get(
            f"/read/{self.book.pk}/file/", HTTP_RANGE="bytes=2-5"
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"2345")
        self.assertEqual(response["Content-Range"], "bytes 2-5/10")

    def test_full_request_streams(self):
        from django.core.files.base import ContentFile

        from apps.library.storage import get_storage

        get_storage().save(self.book.file_path, ContentFile(b"abcdef"))
        self.book.file_size = 6
        self.book.save(update_fields=["file_size"])
        response = self.client.get(f"/read/{self.book.pk}/file/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"abcdef")

    def test_download_is_audited(self):
        from django.core.files.base import ContentFile

        from apps.library.storage import get_storage
        from apps.reading.models import DownloadAudit

        get_storage().save(self.book.file_path, ContentFile(b"abc"))
        self.book.file_size = 3
        self.book.save(update_fields=["file_size"])
        self.client.get(f"/read/{self.book.pk}/file/")
        self.assertEqual(DownloadAudit.objects.filter(user=self.user, book=self.book).count(), 1)

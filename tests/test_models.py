"""Model-layer tests: invariants, uniqueness, normalized search columns."""
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import Profile, Role, profile_for
from apps.annotations.models import Annotation, AnnotationChange, ChangeOp
from apps.library.models import Book
from apps.rooms.models import ReadingRoom, RoomMember, RoomRole
from tests.helpers import make_book, make_user


class ProfileTests(TestCase):
    def test_profile_auto_created_for_every_user(self):
        """Regression: createsuperuser/admin users must not crash .profile access."""
        from django.contrib.auth.models import User as AuthUser

        user = AuthUser.objects.create_user(username="nopfile")
        self.assertTrue(hasattr(user, "profile"))
        self.assertEqual(user.profile.role, Role.MEMBER)
        # And the pages that touch user.profile in Python code work:
        client = self.client
        client.force_login(user)
        response = client.get("/library/upload/")  # profile role check
        self.assertIn(response.status_code, (200, 400))  # member → 400 page, not 500

    def test_role_helpers(self):
        admin = make_user("admin", Role.ADMIN)
        librarian = make_user("lib", Role.LIBRARIAN)
        member = make_user("mem", Role.MEMBER)
        self.assertTrue(admin.profile.is_admin)
        self.assertTrue(admin.profile.can_delete_user_data())
        self.assertTrue(librarian.profile.can_manage_library())
        self.assertFalse(librarian.profile.can_delete_user_data())
        self.assertFalse(member.profile.can_manage_library())
        self.assertFalse(member.profile.is_admin)

    def test_profile_for_requires_auth(self):
        with self.assertRaises(ValueError):
            profile_for(User(username="anon"))

    def test_label_prefers_display_name(self):
        user = make_user("zoe")
        user.profile.display_name = "Zoë"
        user.profile.save()
        self.assertEqual(user.profile.label, "Zoë")


class BookTests(TestCase):
    def test_search_text_rebuilds_with_authors_and_series(self):
        from apps.authors.models import Author

        book = make_book("The Left Hand of Darkness")
        author = Author.objects.create(name="Ursula K. Le Guin")
        book.authors.add(author)
        book.refresh_search_text()
        self.assertIn("ursula k. le guin", book.search_text)
        self.assertIn("the left hand of darkness", book.search_text)

    def test_file_format_is_always_pdf(self):
        book = make_book()
        book.file_format = "epub"
        book.save()
        book.refresh_from_db()
        self.assertEqual(book.file_format, "pdf")


class AnnotationModelTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")
        self.bob = make_user("bob")

    def _annot(self, uid, user=None, room=None, parent=""):
        return Annotation.objects.create(
            uid=uid, book=self.book, room=room, author=user or self.alice,
            page_index=0, subtype="markup", parent_uid=parent,
            text="note", payload={"id": uid},
        )

    def test_uid_unique_per_layer(self):
        self._annot("uid-1")
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                self._annot("uid-1", user=self.bob)  # same private-layer uid space
        room = ReadingRoom.objects.create(book=self.book, owner=self.alice, name="r")
        # The same uid in a room layer is a different layer — allowed.
        a = self._annot("uid-1", room=room)
        self.assertEqual(a.layer_key, f"room:{room.pk}")

    def test_private_layer_uid_uniqueness_is_per_book(self):
        self._annot("uid-1")
        other = make_book("Other")
        Annotation.objects.create(
            uid="uid-1", book=other, author=self.alice,
            page_index=0, subtype="markup", payload={},
        )  # fine: different book

    def test_reply_flag(self):
        root = self._annot("root-1")
        reply = self._annot("reply-1", parent="root-1")
        self.assertFalse(root.is_reply)
        self.assertTrue(reply.is_reply)


class RoomModelTests(TestCase):
    def test_invite_rotation_and_revocation(self):
        book = make_book()
        owner = make_user("owner")
        room = ReadingRoom.objects.create(book=book, owner=owner, name="club")
        self.assertFalse(room.invite_valid)
        token = room.rotate_invite(ttl_days=1)
        self.assertTrue(room.invite_valid)
        room.revoke_invite()
        self.assertFalse(room.invite_valid)
        self.assertNotEqual(room.invite_token, token)

    def test_roles(self):
        book = make_book()
        owner = make_user("owner")
        editor = make_user("editor")
        viewer = make_user("viewer")
        outsider = make_user("outsider")
        room = ReadingRoom.objects.create(book=book, owner=owner, name="club")
        RoomMember.objects.create(room=room, user=editor, role=RoomRole.EDITOR)
        RoomMember.objects.create(room=room, user=viewer, role=RoomRole.VIEWER)
        self.assertEqual(room.member_role(owner), RoomRole.OWNER)
        self.assertTrue(room.can_annotate(editor))
        self.assertFalse(room.can_annotate(viewer))
        self.assertTrue(room.can_view(viewer))
        self.assertFalse(room.can_view(outsider))

"""
JSON sync API tests: the annotation round trip (golden test), payload
validation fuzzing, XSS in comment text, caps and rate limits.
"""
import json

from django.test import TestCase
from django.urls import reverse

from apps.annotations.models import Annotation
from tests.helpers import make_book, make_user


def op_body(ops):
    return json.dumps({"room": "none", "client_id": 1, "ops": ops})


class ApiTestBase(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")
        self.client.force_login(self.alice)

    def post_ops(self, ops, book=None):
        return self.client.post(
            f"/api/reading/{(book or self.book).pk}/annotations/ops/",
            data=op_body(ops),
            content_type="application/json",
            HTTP_X_CSRFTOKEN="test",
        )

    def _create(self, **overrides):
        base = {
            "op": "create", "uid": "ok-1", "base_rev": 0, "subtype": "markup",
            "page_index": 0, "parent_uid": "", "text": "x",
            "payload": {"id": "ok-1"},
        }
        base.update(overrides)
        return base


class GoldenRoundTripTests(ApiTestBase):
    """
    export → store → import without loss.

    The 'export' side is the engine object the client sends; 'store' is the
    server row; 'import' is the public payload the reader feeds back into
    importAnnotations(). All engine fields must survive the loop.
    """

    ENGINE_OBJECT = {
        "id": "golden-1",
        "type": 8,  # highlight (engine numeric type)
        "pageIndex": 3,
        "rect": {"origin": {"x": 100, "y": 200}, "size": {"width": 50, "height": 12}},
        "color": "#f9e79f",
        "opacity": 0.5,
        "contents": "a highlight with fine detail",
        "quads": [{"upperLeft": {"x": 100, "y": 200}, "lowerRight": {"x": 150, "y": 212}}],
        "author": "spoofed-by-client",  # must be rewritten server-side
        "inReplyToId": None,
    }

    def test_round_trip_preserves_engine_fields_and_rewrites_author(self):
        response = self.post_ops([{
            "op": "create", "uid": "golden-1", "base_rev": 0, "subtype": "markup",
            "page_index": 3, "parent_uid": "",
            "text": self.ENGINE_OBJECT["contents"],
            "payload": dict(self.ENGINE_OBJECT),
        }])
        self.assertEqual(response.status_code, 200, response.content)

        snapshot = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/?room=none"
        ).json()
        self.assertEqual(len(snapshot["annotations"]), 1)
        stored = snapshot["annotations"][0]
        payload = stored["payload"]

        # Lossless core geometry/state:
        self.assertEqual(payload["id"], "golden-1")
        self.assertEqual(payload["type"], 8)
        self.assertEqual(payload["pageIndex"], 3)
        self.assertEqual(payload["rect"], self.ENGINE_OBJECT["rect"])
        self.assertEqual(payload["quads"], self.ENGINE_OBJECT["quads"])
        self.assertEqual(payload["opacity"], 0.5)
        self.assertEqual(payload["contents"], self.ENGINE_OBJECT["contents"])
        # Server owns the author:
        self.assertEqual(payload["author"], "Alice")
        self.assertEqual(stored["author"], "Alice")

    def test_replies_round_trip_via_in_reply_to(self):
        self.post_ops([
            {"op": "create", "uid": "root-1", "base_rev": 0, "subtype": "text_note",
             "page_index": 0, "parent_uid": "", "text": "root",
             "payload": {"id": "root-1", "contents": "root"}},
            {"op": "create", "uid": "reply-1", "base_rev": 0, "subtype": "text_note",
             "page_index": 0, "parent_uid": "root-1", "text": "a reply",
             "payload": {"id": "reply-1", "contents": "a reply", "inReplyToId": "root-1",
                         "replyType": "R"}},
        ])
        snapshot = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/?room=none"
        ).json()
        by_uid = {a["uid"]: a for a in snapshot["annotations"]}
        self.assertEqual(by_uid["reply-1"]["parent_uid"], "root-1")
        self.assertEqual(by_uid["reply-1"]["payload"]["inReplyToId"], "root-1")
        self.assertEqual(by_uid["reply-1"]["payload"]["replyType"], "R")


class PayloadValidationTests(ApiTestBase):
    def test_rejects_unknown_subtype(self):
        response = self.post_ops([self._create(subtype="redaction")])
        self.assertEqual(response.status_code, 400)

    def test_rejects_bad_uid(self):
        response = self.post_ops([self._create(uid="../etc/passwd")])
        self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_payload(self):
        response = self.post_ops([self._create(payload={"id": "ok-1", "blob": "x" * 70000})])
        self.assertEqual(response.status_code, 400)

    def test_rejects_too_many_ops(self):
        ops = [self._create(uid=f"u-{i}") for i in range(60)]
        response = self.post_ops(ops)
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_object_ops(self):
        response = self.post_ops(["not-an-op"])
        self.assertEqual(response.status_code, 400)

    def test_fuzzing_random_junk_never_500s(self):
        fuzz = [
            [], {}, {"op": "?"}, {"op": "create"}, {"op": "create", "uid": ""},
            {"op": "create", "uid": "a" * 200}, {"op": "update", "uid": "x", "base_rev": -1},
            {"op": "create", "uid": "x", "subtype": "ink", "page_index": -5},
            {"op": "create", "uid": "x", "subtype": "ink", "text": 42},
            {"op": "create", "uid": "x", "subtype": "ink", "payload": []},
            {"op": "delete", "uid": ""},
        ]
        for bad in fuzz:
            response = self.post_ops([bad])
            self.assertIn(response.status_code, (400, 200), f"payload {bad!r} broke the API")

    def test_comment_text_is_stored_plain_and_escaped_at_render(self):
        evil = '<script>alert(1)</script>'
        self.post_ops([self._create(uid="xss-1", text=evil, payload={"id": "xss-1", "contents": evil})])
        row = Annotation.objects.get(uid="xss-1")
        self.assertEqual(row.text, evil)  # stored raw for the viewer round trip
        # Server-rendered pages escape it (My Annotations list):
        response = self.client.get("/annotations/")
        self.assertNotIn("<script>alert(1)</script>", response.content.decode())
        self.assertIn("&lt;script&gt;", response.content.decode())


class CapsAndRolesTests(ApiTestBase):
    def test_per_user_book_cap(self):
        from django.conf import settings

        small_cap = 3
        with self.settings(ANNOTATION_MAX_PER_USER_BOOK=small_cap):
            for i in range(small_cap):
                self.post_ops([self._create(uid=f"c-{i}")])
            response = self.post_ops([self._create(uid="c-over")])
            self.assertEqual(response.status_code, 409)

    def test_rate_limit_trips(self):
        with self.settings(ANNOTATION_OPS_PER_MINUTE=2), self.settings(
            RATE_LIMITS={"annotation_ops": (2, 60)}
        ):
            codes = [
                self.post_ops([self._create(uid=f"r-{i}")]).status_code for i in range(4)
            ]
        self.assertIn(429, codes)

    def test_viewer_role_rejected(self):
        from apps.rooms.models import ReadingRoom, RoomMember, RoomRole

        room = ReadingRoom.objects.create(book=self.book, owner=make_user("owner"), name="r")
        RoomMember.objects.create(room=room, user=self.alice, role=RoomRole.VIEWER)
        response = self.client.post(
            f"/api/reading/{self.book.pk}/annotations/ops/",
            data=json.dumps({"room": str(room.pk), "ops": [{
                "op": "create", "uid": "v-1", "base_rev": 0, "subtype": "markup",
                "page_index": 0, "parent_uid": "", "text": "x", "payload": {},
            }]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_header_required_for_posts(self):
        # Django's test client exempts CSRF by default; enforce it explicitly.
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        response = strict.post(
            f"/api/reading/{self.book.pk}/annotations/ops/",
            data=op_body([]), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class ChangeFeedTests(ApiTestBase):
    def test_changes_carry_full_annotation_for_create(self):
        self.post_ops([self._create(uid="cf-1")])
        data = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/changes/?room=none&after=0"
        ).json()
        self.assertEqual(len(data["changes"]), 1)
        change = data["changes"][0]
        self.assertEqual(change["op"], "create")
        self.assertIsNotNone(change["annotation"])
        self.assertEqual(change["annotation"]["uid"], "cf-1")

    def test_delete_changes_carry_uid_only(self):
        self.post_ops([self._create(uid="cf-2")])
        self.post_ops([{"op": "delete", "uid": "cf-2", "base_rev": 1}])
        data = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/changes/?room=none&after=1"
        ).json()
        self.assertEqual(data["changes"][0]["op"], "delete")
        self.assertIsNone(data["changes"][0]["annotation"])

    def test_cursor_advances(self):
        self.post_ops([self._create(uid="cf-3")])
        first = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/changes/?room=none&after=0"
        ).json()
        self.post_ops([self._create(uid="cf-4")])
        second = self.client.get(
            f"/api/reading/{self.book.pk}/annotations/changes/?room=none&after={first['cursor']}"
        ).json()
        self.assertGreater(second["cursor"], first["cursor"])
        self.assertEqual([c["uid"] for c in second["changes"]], ["cf-4"])

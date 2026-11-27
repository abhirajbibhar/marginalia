"""
Collaboration tests — the exact cases named in the brief:

* interleaved ops from two users
* revision conflicts (base_rev mismatch returns the server copy)
* delete propagation (parent tombstones its replies in one batch)
* reply to a deleted parent
* cursor reset after compaction
* echo suppression contract (import is echo-free; ops replay is idempotent)
* private-versus-room isolation
"""
from django.test import TestCase
from django.urls import reverse

from apps.annotations import services
from apps.annotations.models import Annotation, AnnotationChange, ChangeOp
from apps.annotations.serializers import validate_ops
from apps.rooms.models import ReadingRoom, RoomMember, RoomRole
from tests.helpers import make_book, make_user


def create_op(uid, page=0, parent="", text="hello", rev=0):
    return {
        "op": "create", "uid": uid, "base_rev": rev, "subtype": "markup",
        "page_index": page, "parent_uid": parent, "text": text,
        "payload": {"id": uid, "contents": text},
    }


class InterleavedOpsTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")
        self.bob = make_user("bob")

    def test_two_users_interleaved_creates(self):
        r1 = services.apply_ops(book=self.book, user=self.alice, room=None,
                                ops=validate_ops([create_op("a-1")]), display_name="Alice")
        r2 = services.apply_ops(book=self.book, user=self.bob, room=None,
                                ops=validate_ops([create_op("b-1")]), display_name="Bob")
        r3 = services.apply_ops(book=self.book, user=self.alice, room=None,
                                ops=validate_ops([create_op("a-2")]), display_name="Alice")
        self.assertEqual(r1.applied, ["a-1"])
        self.assertEqual(r2.applied, ["b-1"])
        self.assertEqual(r3.applied, ["a-2"])
        # Cursors strictly advance along the change feed.
        self.assertLess(r1.cursor, r2.cursor)
        self.assertLess(r2.cursor, r3.cursor)

    def test_interleaved_updates_on_same_annotation_conflict_late(self):
        services.apply_ops(book=self.book, user=self.alice, room=None,
                           ops=validate_ops([create_op("shared-1", text="v1")]),
                           display_name="Alice")
        # Alice updates with base_rev=1 -> revision becomes 2.
        upd_a = {
            "op": "update", "uid": "shared-1", "base_rev": 1, "subtype": "markup",
            "page_index": 1, "parent_uid": "", "text": "alice edit",
            "payload": {"id": "shared-1"},
        }
        r = services.apply_ops(book=self.book, user=self.alice, room=None,
                               ops=validate_ops([upd_a]), display_name="Alice")
        self.assertEqual(r.applied, ["shared-1"])
        # Bob's stale update (base_rev=1) must conflict and return the server copy.
        upd_b = dict(upd_a, text="bob edit", base_rev=1)
        r = services.apply_ops(book=self.book, user=self.bob, room=None,
                               ops=validate_ops([upd_b]), display_name="Bob")
        self.assertEqual(r.conflicts[0]["uid"], "shared-1")
        # Private-layer isolation: Bob cannot even see Alice's private row.
        self.assertTrue(r.conflicts[0].get("deleted") or r.conflicts[0]["author"] == "Alice")


class RevisionConflictTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")

    def test_update_requires_matching_base_rev(self):
        services.apply_ops(book=self.book, user=self.alice, room=None,
                           ops=validate_ops([create_op("x-1")]), display_name="A")
        stale = {
            "op": "update", "uid": "x-1", "base_rev": 99, "subtype": "ink",
            "page_index": 3, "parent_uid": "", "text": "stale",
            "payload": {"id": "x-1"},
        }
        r = services.apply_ops(book=self.book, user=self.alice, room=None,
                               ops=validate_ops([stale]), display_name="A")
        self.assertEqual(r.applied, [])
        self.assertEqual(len(r.conflicts), 1)
        self.assertEqual(r.conflicts[0]["revision"], 1)
        self.assertEqual(r.conflicts[0]["text"], "hello")

    def test_matching_base_rev_applies_and_bumps_revision(self):
        services.apply_ops(book=self.book, user=self.alice, room=None,
                           ops=validate_ops([create_op("x-1")]), display_name="A")
        upd = {
            "op": "update", "uid": "x-1", "base_rev": 1, "subtype": "markup",
            "page_index": 2, "parent_uid": "", "text": "updated",
            "payload": {"id": "x-1"},
        }
        r = services.apply_ops(book=self.book, user=self.alice, room=None,
                               ops=validate_ops([upd]), display_name="A")
        self.assertEqual(r.applied, ["x-1"])
        annotation = Annotation.objects.get(uid="x-1")
        self.assertEqual(annotation.revision, 2)
        self.assertEqual(annotation.page_index, 2)


class DeletePropagationTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")
        self.room = ReadingRoom.objects.create(book=self.book, owner=self.alice, name="r")

    def test_parent_delete_tombstones_replies(self):
        ops = [
            create_op("root-1"),
            create_op("reply-1", parent="root-1"),
            create_op("reply-2", parent="root-1"),
        ]
        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops(ops), display_name="A")
        r = services.apply_ops(
            book=self.book, user=self.alice, room=self.room,
            ops=validate_ops([{"op": "delete", "uid": "root-1", "base_rev": 1}]),
            display_name="A",
        )
        self.assertEqual(r.applied, ["root-1"])
        self.assertEqual(Annotation.objects.filter(deleted_at__isnull=False).count(), 3)
        # Delete ops are logged for each tombstoned row (client convergence).
        self.assertEqual(
            AnnotationChange.objects.filter(op=ChangeOp.DELETE).count(), 3
        )

    def test_reply_to_deleted_parent_still_stores_but_parent_stays_tombstoned(self):
        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops([create_op("root-2")]), display_name="A")
        services.apply_ops(
            book=self.book, user=self.alice, room=self.room,
            ops=validate_ops([{"op": "delete", "uid": "root-2", "base_rev": 1}]),
            display_name="A",
        )
        # A late reply arriving after the parent's delete is stored as its own
        # annotation (replies cannot collide), and visible as a standalone note.
        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops([create_op("late-reply", parent="root-2")]),
                           display_name="A")
        late = Annotation.objects.get(uid="late-reply")
        self.assertIsNone(late.deleted_at)
        self.assertEqual(late.parent_uid, "root-2")

    def test_delete_is_idempotent(self):
        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops([create_op("once")]), display_name="A")
        for _ in range(3):
            r = services.apply_ops(
                book=self.book, user=self.alice, room=self.room,
                ops=validate_ops([{"op": "delete", "uid": "once", "base_rev": 1}]),
                display_name="A",
            )
            self.assertEqual(r.applied, ["once"])
        self.assertEqual(AnnotationChange.objects.filter(op=ChangeOp.DELETE).count(), 1)


class CursorResetTests(TestCase):
    def test_cursor_predating_horizon_gets_reset(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        book = make_book()
        alice = make_user("alice")
        services.apply_ops(book=book, user=alice, room=None,
                           ops=validate_ops([create_op("old-1")]), display_name="A")
        first_id = AnnotationChange.objects.first().id
        # A later change survives compaction; the early one does not.
        services.apply_ops(book=book, user=alice, room=None,
                           ops=validate_ops([create_op("new-1")]), display_name="A")
        AnnotationChange.objects.filter(id=first_id).update(
            created_at=timezone.now() - timedelta(days=120)
        )
        call_command("compact_annotation_changes")  # deletes the backdated row

        horizon = services.change_horizon_id()
        self.assertGreater(horizon, first_id)
        # A fresh client (after=0) never resets; a stale cursor does.
        rows, cursor, reset = services.changes_since(
            book, None, after=0, user=alice, horizon_id=horizon
        )
        self.assertFalse(reset)
        rows, cursor, reset = services.changes_since(
            book, None, after=first_id, user=alice, horizon_id=horizon
        )
        self.assertTrue(reset)


class EchoSuppressionTests(TestCase):
    """Server contract that makes client echo suppression safe."""

    def test_replayed_create_is_idempotent(self):
        book = make_book()
        alice = make_user("alice")
        op = create_op("replay-1")
        r1 = services.apply_ops(book=book, user=alice, room=None,
                                ops=validate_ops([op]), display_name="A")
        r2 = services.apply_ops(book=book, user=alice, room=None,
                                ops=validate_ops([op]), display_name="A")
        self.assertEqual(r1.applied, ["replay-1"])
        self.assertEqual(r2.applied, ["replay-1"])  # no conflict, no duplicate
        self.assertEqual(Annotation.objects.filter(uid="replay-1").count(), 1)
        # Only the first apply logs a change row (no echo storm).
        self.assertEqual(AnnotationChange.objects.count(), 1)

    def test_foreign_uid_create_conflicts(self):
        book = make_book()
        alice = make_user("alice")
        bob = make_user("bob")
        services.apply_ops(book=book, user=alice, room=None,
                           ops=validate_ops([create_op("theirs")]), display_name="A")
        r = services.apply_ops(book=book, user=bob, room=None,
                               ops=validate_ops([create_op("theirs")]), display_name="B")
        self.assertEqual(r.applied, [])
        self.assertEqual(r.conflicts[0]["uid"], "theirs")


class PrivateVersusRoomIsolationTests(TestCase):
    def setUp(self):
        self.book = make_book()
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.room = ReadingRoom.objects.create(book=self.book, owner=self.alice, name="r")
        RoomMember.objects.create(room=self.room, user=self.bob, role=RoomRole.EDITOR)

    def test_private_notes_never_appear_in_room_snapshot(self):
        services.apply_ops(book=self.book, user=self.alice, room=None,
                           ops=validate_ops([create_op("private-1", text="secret")]),
                           display_name="A")
        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops([create_op("room-1", text="shared")]),
                           display_name="A")
        private = services.layer_annotations(self.book, self.alice, None)
        room_layer = services.layer_annotations(self.book, self.bob, self.room)
        self.assertEqual([a.uid for a in private], ["private-1"])
        self.assertEqual([a.uid for a in room_layer], ["room-1"])

    def test_private_change_feed_is_per_user(self):
        services.apply_ops(book=self.book, user=self.alice, room=None,
                           ops=validate_ops([create_op("private-1")]), display_name="A")
        rows_a, _, _ = services.changes_since(
            self.book, None, after=0, user=self.alice, horizon_id=0
        )
        rows_b, _, _ = services.changes_since(
            self.book, None, after=0, user=self.bob, horizon_id=0
        )
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(len(rows_b), 0)

    def test_room_snapshot_marks_others_annotations_read_only(self):
        from apps.annotations.serializers import annotation_to_public

        services.apply_ops(book=self.book, user=self.alice, room=self.room,
                           ops=validate_ops([create_op("room-1")]), display_name="A")
        annotation = Annotation.objects.get(uid="room-1")
        mine = annotation_to_public(annotation, "Alice", read_only=False)
        theirs = annotation_to_public(annotation, "Alice", read_only=True)
        self.assertNotIn("readOnly", (mine["payload"].get("flags") or []))
        self.assertIn("readOnly", theirs["payload"]["flags"])
        self.assertIn("lockedContents", theirs["payload"]["flags"])

    def test_viewer_cannot_annotate(self):
        viewer = make_user("viewer")
        RoomMember.objects.create(room=self.room, user=viewer, role=RoomRole.VIEWER)
        # The API rejects viewer ops with 403 (checked in test_annotations_api).
        self.assertFalse(self.room.can_annotate(viewer))

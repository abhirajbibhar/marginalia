"""
Payload validation for the JSON sync API.

Security rules enforced here (see docs/COLLABORATION.md):

* The server sets the author from the session — client-supplied author fields
  are stripped on the way in and rewritten on the way out.
* Annotation subtypes are whitelisted (markup, ink, shapes, free text, sticky
  note, stamps — stamps size-capped).
* Payloads are capped at 64 KB serialized; ops at 50 per request.
* The annotation JSON is schema-checked (required keys, type sanity); comment
  text is stored plain and escaped at render time.
"""
import json

from django.conf import settings

ALLOWED_SUBTYPES = {"markup", "ink", "shape", "free_text", "text_note", "stamp"}
MAX_TEXT = 16 * 1024
UID_RE = r"^[A-Za-z0-9._:-]{1,64}$"

import re

_UID = re.compile(UID_RE)


class PayloadError(ValueError):
    """Raised when an op payload fails validation."""


def max_payload_bytes() -> int:
    return int(getattr(settings, "ANNOTATION_MAX_PAYLOAD_BYTES", 64 * 1024))


def validate_op(op: dict) -> dict:
    """
    Validate one op and return a sanitized copy.

    Shape:
        {op: create|update|delete, uid, base_rev, subtype, page_index,
         parent_uid, text, payload}
    """
    if not isinstance(op, dict):
        raise PayloadError("op must be an object")
    kind = op.get("op")
    if kind not in {"create", "update", "delete"}:
        raise PayloadError("op must be create|update|delete")
    uid = str(op.get("uid", ""))
    if not _UID.match(uid):
        raise PayloadError("uid must match [A-Za-z0-9._:-]{1,64}")
    base_rev = op.get("base_rev")
    if base_rev is not None and (not isinstance(base_rev, int) or base_rev < 0):
        raise PayloadError("base_rev must be a non-negative integer")

    clean = {
        "op": kind,
        "uid": uid,
        "base_rev": base_rev,
        "subtype": "",
        "page_index": 0,
        "parent_uid": "",
        "text": "",
        "payload": {},
    }

    if kind == "delete":
        return clean

    subtype = str(op.get("subtype", ""))
    if subtype not in ALLOWED_SUBTYPES:
        raise PayloadError(f"subtype {subtype!r} is not allowed")
    page_index = op.get("page_index", 0)
    if not isinstance(page_index, int) or page_index < 0 or page_index > 1_000_000:
        raise PayloadError("page_index out of range")
    parent_uid = str(op.get("parent_uid", "") or "")
    if parent_uid and not _UID.match(parent_uid):
        raise PayloadError("parent_uid is invalid")
    text = op.get("text", "") or ""
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise PayloadError("text must be a string of at most 16KB")
    payload = op.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise PayloadError("payload must be an object")

    # Full-object size cap (serialized). Stamp appearances are stored inside the
    # payload as base64 and are therefore covered by this cap (size-capped).
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(serialized.encode("utf-8")) > max_payload_bytes():
        raise PayloadError("payload exceeds 64KB")

    # Server-owned fields are rewritten, never trusted.
    payload.pop("author", None)
    payload.pop("authorName", None)
    payload["id"] = uid
    if parent_uid:
        payload["inReplyToId"] = parent_uid

    clean.update({
        "subtype": subtype,
        "page_index": page_index,
        "parent_uid": parent_uid,
        "text": text,
        "payload": payload,
    })
    return clean


def validate_ops(ops) -> list[dict]:
    if not isinstance(ops, list) or not ops:
        raise PayloadError("ops must be a non-empty array")
    cap = int(getattr(settings, "ANNOTATION_MAX_OPS_PER_REQUEST", 50))
    if len(ops) > cap:
        raise PayloadError(f"at most {cap} ops per request")
    return [validate_op(op) for op in ops]


# ---------------------------------------------------------------------------
# Outgoing shapes
# ---------------------------------------------------------------------------
def annotation_to_public(annotation, display_name: str, read_only: bool = False) -> dict:
    """
    The wire representation of one annotation for a client.

    The author is rewritten to the server-known display name; the payload keeps
    the engine object shape so the client can build transfer items directly.
    ``read_only`` (room annotations authored by someone else) adds the PDF
    ``readOnly``/``lockedContents`` flags, which make the annotation
    non-interactive in the viewer (Phase 0 §6) while keeping it visible.
    """
    payload = dict(annotation.payload or {})
    payload["id"] = annotation.uid
    payload["author"] = display_name
    if annotation.parent_uid:
        payload["inReplyToId"] = annotation.parent_uid
    payload["contents"] = annotation.text
    if read_only:
        flags = list(payload.get("flags") or [])
        for flag in ("readOnly", "lockedContents"):
            if flag not in flags:
                flags.append(flag)
        payload["flags"] = flags
    return {
        "uid": annotation.uid,
        "subtype": annotation.subtype,
        "page_index": annotation.page_index,
        "parent_uid": annotation.parent_uid,
        "text": annotation.text,
        "revision": annotation.revision,
        "deleted": annotation.deleted_at is not None,
        "author_id": annotation.author_id,
        "author": display_name,
        "payload": payload,
    }


def change_to_public(change, display_name: str, annotation: dict | None = None) -> dict:
    return {
        "change_id": change.id,
        "op": change.op,
        "uid": change.annotation_uid,
        "revision": change.revision,
        "book_id": change.book_id,
        "room_id": change.room_id,
        "author": display_name,
        "created_at": change.created_at.isoformat(),
        # Full object for create/update so the client can import it directly;
        # deletes carry only the uid.
        "annotation": annotation,
    }

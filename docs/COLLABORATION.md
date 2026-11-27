# Collaboration — sync protocol, conflict rules, limits

Near-real-time co-reading ("at the same time" ≈ 2–3 s), implemented with
**polling** that works identically on SQLite and D1. No Redis. Realtime push
(SSE / Durable Object WebSockets) is an optional capability flag
(`realtime_push`, off on both targets — Phase 0 §9).

## Layers

Every annotation belongs to exactly one **layer** per book:

- **Private** (`room IS NULL`) — the author's own notes. Visible only to the
  author, including from Admins.
- **Room** (`room = <id>`) — shared. Members see each other's annotations and
  replies in the same viewer. Role `viewer` is read-only; `owner`/`editor` may
  annotate and reply.

The reader-bar layer switch decides where **new** annotations go. The author
label shown is always the server-known display name.

## Endpoints (JSON; the only non-HTMX XHR in the app)

All require a session; POSTs require the `X-CSRFToken` header. Rationale for
the exception: annotation payloads are structured engine objects (geometry,
quads, stamp appearance buffers) — a poor fit for HTML fragments. Everything
else uses HTMX.

```
GET  /api/reading/<book>/annotations/?room=<id|none>&page=<n>
     → { annotations: [PublicAnnotation], cursor, participants, reset }

POST /api/reading/<book>/annotations/ops/
     { room, client_id, ops: [Op…] }        (≤50 ops)
     → { applied: [uid…], conflicts: [PublicAnnotation…], cursor }

GET  /api/reading/<book>/annotations/changes/?room=&after=<cursor>&page=<n>
     → { cursor, changes: [Change], participants, reset }
```

`PublicAnnotation` = `{uid, subtype, page_index, parent_uid, text, revision,
deleted, author_id, author, payload}` where `payload` is the full engine
object (`PdfAnnotationObject`) with `id`, `author` and `contents` rewritten by
the server.

`Change` = `{change_id, op: create|update|delete, uid, revision, author,
created_at, annotation?}` — `annotation` carries the full `PublicAnnotation`
for create/update so the client can import it directly; deletes carry only the
uid.

## Client behaviour (static/js/reader.js)

1. **Open** → snapshot of the active layer → `importAnnotations()` (echo-free).
2. **Local events** (`onAnnotationEvent`: create/update/delete) → ops queued
   in memory + localStorage backup (per user+book), flushed in ~750 ms batches
   (500–1000 ms window), also on `visibilitychange`/`pagehide` (`keepalive`).
   Offline batches replay from the backup on reconnect.
3. **Poll** `changes?after=<cursor>` every ~3 s when tab visible & others
   present, ~10 s when alone, ~30 s when hidden; exponential backoff on errors.
   Presence (`page=<n>`) piggybacks on the poll.
4. **Apply remote changes** with `importAnnotations` / `deleteAnnotation`
   inside an `applyingRemote` guard (import itself is echo-free — verified in
   the shipped bundle, Phase 0 §7 — but updates/deletes emit events).
5. **Sync chip**: Saved · Syncing… · Offline (n pending).

## Conflict rules

- **Optimistic revision.** Every annotation has `revision` (starts at 1).
  An update op carries `base_rev`; it applies **only** on a match
  (compare-and-set style single statement). On mismatch the server returns its
  copy in `conflicts` and the client re-imports it (last-writer-wins toward
  the server's state; no merge UI).
- **Creates are keyed by uid** per *(book, layer)*. Replaying our own create
  (reconnect) is a no-op; someone else's uid conflicts and returns the copy.
- **Deletes are tombstones** (`deleted_at`), so late syncs converge. Deleting
  a parent tombstones its replies in the same batch. A reply arriving after
  its parent's delete stores fine as a standalone annotation (replies cannot
  collide — they are separate annotations with `parent_uid`).
- **Replies** are annotations with `parent_uid` = parent `uid`
  (engine: `inReplyToId` + `replyType`); comment text lives in `text`/`contents`.

## Cursor & compaction

- The cursor is `AnnotationChange.id` (append-only autoincrement).
- `compact_annotation_changes` prunes rows older than `CHANGE_HORIZON_DAYS`.
- A client whose `after` predates the horizon receives `reset: true` and does
  a full resync (fresh snapshot + new cursor). Fresh clients (`after=0`) never
  reset.

## Presence

`RoomMember.last_seen` / `last_page` update on polls — **throttled** to page
changes or 60-second staleness so 500 users polling every 3 s fit D1's write
budget (Phase 0 §8). The reader bar shows avatars and "Ada · p. 12".

## Limits (server-enforced)

| Limit | Value | Where |
|---|---|---|
| Payload size (serialized annotation) | 64 KB | `annotations.serializers` |
| Ops per request | 50 | settings `ANNOTATION_MAX_OPS_PER_REQUEST` |
| Annotations per user per book | 5,000 | settings `ANNOTATION_MAX_PER_USER_BOOK` |
| Ops per minute per user | 120 | settings `ANNOTATION_OPS_PER_MINUTE` (rate limiter) |
| Comment text | 16 KB | `annotations.serializers` |
| Subtype whitelist | markup, ink, shape, free_text, text_note, stamp | `annotations.serializers` |
| Stamp appearance | covered by the 64 KB payload cap | — |
| Change rows per poll | 200 | `annotations.services.changes_since` |
| Page size everywhere | 48 | settings `PAGE_SIZE` (D1 param budget) |

## Security invariants

- The **server sets the author** from the session: client-supplied author
  fields are stripped on input and rewritten on output (display name only).
- Room membership + role checked on **every** call (viewers cannot post ops).
- Only the author may update/delete their annotation; Librarians/Admins may
  moderate **room** content; private notes are untouchable except by their
  author (Admins may delete whole user accounts but cannot read private notes).
- Any editor may reply to any annotation visible in the room layer.
- Comment text is stored raw (round-trip fidelity) and **escaped at every
  server-rendered surface** (XSS-tested). The viewer renders it as text.

## D1 budget model (500 users)

Per poll rows read = changes delivered + ~0–2 index-seek overhead → **0–5**
typical (0–1 idle). Worst case 166 polls/s → ≤ 3% of the Workers Paid
rows-read budget. Writes: ops (≈ edits/min) + throttled presence — inside the
paid write budget with the 60 s/Δpage throttle. Evidence & queries:
`docs/PHASE0.md` §8.

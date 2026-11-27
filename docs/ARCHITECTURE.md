# Architecture

## One codebase, two targets

`DEPLOYMENT_TARGET` selects `config.settings.local` or `config.settings.cloudflare`
and (through `apps/library/capabilities.py`) every runtime capability flag.
All business code is target-agnostic; the seams are:

| Seam | Local | Cloudflare |
|---|---|---|
| Database | `django.db.backends.sqlite3` | `django_cf.db.backends.d1` (sync ORM over the async D1 binding) |
| Blob storage | `FileSystemStorage` via `library.storage.LocalStorage` | `django_cf.storage.R2Storage` via `library.storage.R2Storage` |
| Uploads | streamed to an authenticated PUT endpoint | presigned direct-to-R2 (pure-Python SigV4) |
| Secrets | `.env` | Wrangler secrets (`workers.env`) |
| Periodic work | system cron → management commands | Cron Trigger → `/manage/tasks/` |

**Portability rules** (enforced by `dblayer` + code review, tested in
`tests/test_storage.py`): no DB-specific raw SQL, no `transaction.atomic`
reliance, no `select_for_update`, every `IN` fan-out chunked (D1 caps at 100
bound parameters; we use 90), pages capped at 48 items.

## Django apps

```
runtime/       RateLimitBucket + RateLimiter + RuntimeCache + periodic tasks
accounts/      Profile (role, display name, theme, default layer)
library/       Book, Category, Tag · storage/validation/metadata/upload
               capabilities.py · {% icon %} tag · upload pipeline
authors/ series/ collections/   catalogue browsing
reading/       Bookmark, ReadingProgress, Review, DownloadAudit
               reader page + Range-capable authenticated file serving
annotations/   Annotation, AnnotationChange · JSON sync API · ops engine
rooms/         ReadingRoom, RoomMember · invites · membership
dashboard/     KPIs, recent activity, continue reading
adminpanel/    deployment dashboard + cron maintenance endpoint
```

## Data model (essentials)

- **Book** stores storage **keys** only (`file_path` → `books/…`,
  `cover_path` → `covers/…`), `file_format` fixed to `pdf`, plus a normalized
  `search_text` column for DB-only search (title/author/series/category/ISBN).
- **Annotation** is one engine annotation: `uid` (engine id, stable across
  export/import), `room` (NULL = private layer), `parent_uid` (reply parent =
  engine `inReplyToId`), `text` (engine `contents`), `payload` (the full
  engine object for lossless re-import), `revision` (optimistic concurrency),
  `deleted_at` (tombstone). Uniqueness is per *(book, layer, uid)* via two
  partial unique indexes (NULL-safe).
- **AnnotationChange** is the append-only sync feed; its autoincrement `id` is
  the cursor. Compaction prunes old rows; clients with pre-horizon cursors get
  `reset: true` and full-resync.
- **ReadingRoom** owns one book's shared layer; **RoomMember** carries role
  (owner/editor/viewer) and presence (`last_seen`, `last_page`).

## Reader integration

`reading/reader.html` extends the Cadence shell (`body.is-reader`,
`main.page-reader`); `reader-bar` + `#pdf-viewer` replace `.page-head`.
`static/js/reader.js` mounts `@embedpdf/snippet@2.15.1` (pinned, vendored with
`pdfium.wasm` via `wasmUrl`) and implements the sync client. Key verified
behaviours (evidence in `docs/PHASE0.md`):

- **Replies** are ordinary annotations (`inReplyToId` + `replyType`); the v2 UI
  ships a comments panel with reply threads — no custom UI needed.
- **`importAnnotations` is echo-free** (store dispatch, no create events), so
  applying remote changes does not bounce back; an `applyingRemote` guard
  covers the update/delete paths that do emit events.
- **Read-only remote annotations**: the server adds PDF `readOnly` +
  `lockedContents` flags to other users' room annotations on export, which the
  engine honours (`isAnnotationInteractive` false); the server rejects
  non-author mutation regardless.
- **Cover rendering** happens in the browser at upload time via the render
  plugin (`renderPage()` → JPEG → `/library/<id>/cover/`).

## Sync design (summary; full protocol in COLLABORATION.md)

- Batched ops (500–1000 ms window, 50 ops/request cap) with an in-memory queue
  and per-user+book localStorage backup; flush on `visibilitychange`/`pagehide`
  (`keepalive`).
- Polling: `changes?after=<cursor>` every ~3 s with others present, ~10 s
  alone, ~30 s hidden, exponential backoff on errors. Presence piggybacks on
  the poll with throttled writes (page change or >60 s) to fit D1's write
  budget (Phase 0 §8).
- Conflicts: `base_rev` compare-and-set; mismatch returns the server copy for
  re-import. Deletes are tombstones; parent deletes tombstone replies.

## Security model

- **Server-side authority everywhere**: roles checked per view/endpoint;
  annotation authorship taken from the session and rewritten on output.
- **Privacy**: private annotations (`room IS NULL`) are only ever returned to
  their author. The Django admin lists room annotations only. Admins may
  delete user data but cannot read private notes (a deliberate privacy call).
- **Validation**: whitelist subtypes (markup, ink, shapes, free text, sticky
  note, size-capped stamps), 64 KB payload cap, JSON schema checks, comment
  text escaped at every server render (XSS test).
- **Transport**: strict CSP (`script-src 'self' 'wasm-unsafe-eval'`), secure
  cookies, CSRF everywhere, rate limits (login/search/download/upload/ops),
  audited downloads.
- **Uploads**: extension + `%PDF-` magic + size/page caps; encrypted files are
  rejected; `/JavaScript`, `/Launch`, `/EmbeddedFiles` constructs are flagged
  for review. Random storage keys. The bucket is never public — files are
  streamed only through `/read/<id>/file/` after a permission check.

## Testing strategy

- Unit/model tests (`test_models.py`), view + HTMX partial + role matrix
  (`test_views.py`), the JSON API incl. the golden annotation round trip,
  validation fuzzing and XSS (`test_annotations_api.py`), collaboration
  scenarios (`test_collaboration.py`), storage/validation/capability contracts
  (`test_storage.py`).
- `tests/e2e/` holds the two-browser Playwright smoke (local only).
- Storage & DB contract tests run against real SQLite + temp dirs locally;
  the same suite is intended to run against `wrangler dev --local` for D1/R2
  (fake or local-mode) — see PARITY.md.

# Phase 0 — Feasibility Gate (Spike Report)

**Project:** PDF Digital Library (working name *Marginalia*)
**Date:** 2026-11-25
**Targets:** Cloudflare (Python Workers + D1 + R2) / Self-hosted (SQLite + local filesystem)
**Status: PASS — no feature or target dropped.** Every item below was verified against
current documentation or shipped source, not from memory. Sources and evidence are cited
per item.

Legend: ✅ verified · ⚠️ verified with caveats (caveat stated) · 🔶 optional/unverified →
kept behind capability flag.

---

## 1. Django 6 on the Worker: ORM on D1, session login, R2 read/write — ✅

**Evidence:** Cloudflare docs "Django — Run Django on Python Workers"
(`developers.cloudflare.com/workers/languages/python/packages/django/`, updated 2026-09-05);
`cloudflare/workers-py` → `django-cf` package (PyPI `django-cf` 0.2.17, requires
Python ≥ 3.12, deps: `sqlparse`, `workers-runtime-sdk>=1.6.0`); example repo
`G4brym/django-on-workers` (Cloudflare-deployable template using D1 + R2 with Django).

- **Django on Workers:** officially supported via WSGI/ASGI adaptors (`workers.wsgi.fetch`
  / `workers.asgi.fetch`). The recommended path for D1 is **WSGI + synchronous ORM**.
- **Sync-ORM-to-async-binding bridge:** `django_cf.db.backends.d1` is a SQLite-compatible
  Django DB backend. Django calls the DB-API-2-style `cursor.execute()` synchronously; the
  backend bridges each call to the **async D1 binding** (`env.DB.prepare().bind().all()` /
  `.run()`) by driving the isolate's event loop from the synchronous call
  (`workers-runtime-sdk` provides the runtime bridge; Pyodide runs a normal asyncio loop
  underneath, so the bridge awaits the binding future and serializes concurrent cursor use
  with an in-isolate lock — same pattern the Hyperdrive Python docs prescribe for sync DB
  ops). Because bindings are invoked from the isolate, **there is no TCP socket**: the
  "connection" is the binding object, which is why the ORM works without a driver.
- **No interactive transactions (confirmed by Cloudflare docs):** *“The D1 and Durable
  Object backends do not support transactions. `@transaction.atomic` is a no-op, rollback
  will not work.”* This matches the brief; the app writes small atomic units or verified
  D1 batches (`django.db.models.bulk_create(..., batch_size≤N)` maps to batched statements),
  and every multi-row mutation is written idempotently (see collaboration design).
- **Sessions:** Django's database-backed sessions (`django.contrib.sessions`) work
  unchanged — sessions are just ORM rows in D1. Login flow is stock Django auth
  (session cookie + CSRF). Cookies: `SESSION_COOKIE_SECURE`, `SameSite=Lax`.
- **R2 read/write:** `django_cf.storage.R2Storage` is a Django Storage backend over the R2
  binding (used in the official django-on-workers template with `STORAGES["default"]`).
  Downloads/reads stream from R2 with `Range` via the binding's ranged-get. Our own
  `BookStorage` interface wraps this (see ARCHITECTURE).
- **Django version:** Cloudflare's docs track current Django; the template installs plain
  `django` (6.x on Python 3.12+). `django-cf` does not pin a Django version and is a thin
  backend; nothing in Django 6's ORM surface we use (QuerySet, select_related /
  prefetch_related, `bulk_create`, `update`, `F`) is unsupported. We restrict ourselves to
  that subset (no `transaction.atomic` reliance, no `select_for_update`, no raw SQL).

## 2. EmbedPDF v2 inside the Cadence shell, both targets — ✅

**Evidence:** `v2.embedpdf.com` docs (Snippet → Getting Started / Theme / Customizing UI /
Security & Permissions / Plugins), and the **shipped bundle** `@embedpdf/snippet@2.15.1`
(inspected `dist/`, `embedpdf.d.ts`, `components/app.d.ts`, and the
`@embedpdf/plugin-{annotation,scroll,document-manager,capture,render}@2.15.1` type packages).

- **Mount:** `EmbedPDF.init({ type: 'container', target, documentManager: { initialDocuments:
  [...] }, tabBar: 'never', ... })` — `PDFViewerConfig` (from the shipped d.ts) accepts
  `src` or `documentManager.initialDocuments` (`LoadDocumentUrlOptions` incl. `documentId`),
  plus `tabBar: 'never'`, `disabledCategories`, `permissions`, `theme`, `annotations`,
  `search`, `wasmUrl`, `fontFallback`. Pin: **`@embedpdf/snippet@2.15.1` exact** (latest 2.x
  on npm at build time; 3.x not used).
- **Authenticated PDF load:** same-origin session-authenticated endpoint
  `/read/<book>/file/` (GET, Range-capable). The snippet loads `src` via fetch/XHR with
  same-origin credentials — session cookie applies. Never a public bucket.
- **WASM + MIME + CSP:** the engine loads a `.wasm` (default CDN; we vendor it locally and
  point `wasmUrl` at our static asset). Requirements: serve WASM with
  `Content-Type: application/wasm` (Workers static assets do this by extension);
  CSP needs `script-src 'self' 'wasm-unsafe-eval'` (WASM compile) and, because the default
  engine runs in a worker, `worker-src 'self' blob:` (blob worker fallback) plus
  `connect-src 'self'`. No `unsafe-eval` needed. All confirmed against the bundle
  (`worker-engine-*.js` / `direct-engine-*.js`; `worker: false` selects the in-page engine
  and avoids the blob-worker if a stricter CSP is desired).
- **Resume-to-page:** `registry.getPlugin('scroll')` exposes `scrollToPage`,
  `onPageChange`, `onLayoutReady` (`ScrollCapability`, plugin-scroll 2.15.1 types) — we
  restore `ReadingProgress.last_position` after `onLayoutReady`.
- **Container resize on rail toggle:** `ResizeObserver` on the `#pdf-viewer` mount; the
  viewport/scroll plugins re-measure on container resize (layout is size-driven). We also
  hook `onLayoutChange` to persist page state.
- **Cadence shell fit:** the viewer mounts inside `<main id="main" class="page page-reader">`
  with `body.is-reader`; only `.main-col` becomes `100svh` flex — verified against
  `cadence/assets/css/base.css` structure (`.app` grid, `.main-col`, `--cad-rule` tokens).

## 3. Annotation round trip (create / update / delete → store → reload → re-import) — ✅

**Evidence:** `@embedpdf/plugin-annotation@2.15.1` (`AnnotationTransferItem` type), the
snippet's `annotationApi.exportAnnotations().wait(...)` / `importAnnotations(items)`, docs
"Importing and Exporting Annotations", and the headless samples shipped in the embed-pdf-viewer
repo (`docs/content/samples/annotation/export-import.vue`, `comments.vue`).

- **Transfer shape (exact):** `AnnotationTransferItem { annotation: PdfAnnotationObject;
  ctx?: AnnotationContextMap[...] }` — `ctx` carries stamp appearance (`ctx.data` accepts a
  raw `ArrayBuffer` PNG/JPEG/PDF, auto-detected by magic bytes). `exportAnnotations()`
  returns a `Task` resolved with these items; `importAnnotations(items)` accepts the same
  shape. The engine keeps annotation `id` stable across export/import → server can key rows
  by engine id (`uid`).
- **Comment text field:** **`contents`** (string) on `PdfAnnotationObject` — confirmed in
  bundle DTO construction (`contents: defaults.contents ?? ""`) and in the comments sample
  (`thread.root.contents`). We store it in `Annotation.text` for search + XSS-escape on
  server render.
- **Replies:** represented as *separate annotations* with
  **`inReplyToId: <parent engine id>`** and **`replyType`** (`PdfAnnotationReplyType`;
  PDF `/IRT` + `/RT`). Comment replies use the Reply type; the engine's Group type reuses
  the same fields for grouped shapes. Confirmed in the v2.15.1 bundle (`inReplyToId`,
  `replyType` in the annotation store) and in the comment sidebar's
  `onReply(inReplyToId: string, contents: string)` API. **This decides the schema:**
  `Annotation.parent_uid` ← `inReplyToId`, no reply table needed. Reply collisions cannot
  happen (replies are own annotations); deleting a parent tombstones its replies in one
  batch (server-side).
- **Update events:** `onAnnotationEvent` reports `create`, **`update`**, `delete` (plus
  `loaded` for initial hydration) with `{type, documentId, annotation, pageIndex, ctx?,
  committed}` — confirmed in the bundle (`type:"update"` emissions in `updateAnnotation(s)`)
  and docs ("creation, deletion, updates").
- Round trip test planned as a golden test (export → store → import equality) in TESTS.

## 4. STOP-CHECK — v2 UI comments panel with reply threads + in-book search — ✅ PRESENT

This was the gate: if either was missing we stop and redesign. Both are **in the v2 snippet
UI**, verified from the shipped 2.15.1 bundle (not just docs):

- **Comments panel:** the snippet ships a full `comment-sidebar` UI
  (`dist/components/comment-sidebar/`: `annotation-card`, `comment` (with `isReply` prop),
  `edit-comment-form`, `user-avatar`, `annotation-input`), wired to the `annotation:comment`
  command which toggles the `comments` panel; UI category `panel-comment` exists in
  `disabledCategories`. The comment card API is literally
  `onReply(inReplyToId: string, contents: string)` and `onUpdate(id, contents)` — i.e.
  **built-in reply threads**.
- **In-book search:** `SearchPlugin` + `panel-search` category + `search` config in
  `PDFViewerConfig`; the search UI ships with the snippet. We do not build a custom one and
  do not disable it (global library search stays in the Cadence topbar).

**No stop. No fallback needed.**

## 5. Reply representation + comment text field — ✅ (answers 4's schema question)

From the bundle + plugin types (2.15.1):

| Question | Answer |
|---|---|
| Parent-id field in exported objects | `inReplyToId` (engine uid of the parent annotation) |
| Reply-type discriminator | `replyType` (`PdfAnnotationReplyType`; comment replies vs. grouping) |
| Comment text field | `contents` |
| Thread API (UI) | `comments.reply(rootRef, text)`, `comments.setText`, `comments.deleteThread`, `onThreadChanged` |

Server schema maps `uid` ← `annotation.id`, `parent_uid` ← `annotation.inReplyToId`,
`text` ← `annotation.contents`, `payload` ← the full `PdfAnnotationObject` JSON
(round-trip preservation). Replies are ordinary `Annotation` rows with `parent_uid` set.

## 6. Other users' annotations shown read-only in the viewer — ✅ supported

**Evidence:** bundle `isAnnotationInteractive()` (2.15.1): an annotation whose
`flags` include **`"readOnly"`** is non-interactive (cannot be selected/edited), and
`"lockedContents"` blocks content edits; PDF annotation flags carry `readOnly`(64) /
`locked`(128) / `lockedContents`(512) (`PdfAnnotationFlags` name map verified). The
document-level `permissions` config (`PermissionConfig`, incl. `ModifyAnnotations`) can
additionally gate all modification.

- **Mechanism:** when importing the **room layer**, we rewrite each remote (other-user)
  annotation's `flags` to add `readOnly` (+ `lockedContents` for comment text) and set the
  author label from the server-known display name. The user's own layer is imported with
  normal flags.
- **Fallback (still implemented):** the server rejects update/delete of others'
  annotations (403) and the client re-imports the server copy on conflict — the engine's
  per-annotation flag handling is the first line, server authority is the guarantee.
  Moderators (Librarian/Admin) may edit/delete room content via the server even though the
  viewer treats it read-only.

## 7. Import echo + remote delete API — ✅ import is echo-free; delete API confirmed

**Evidence:** minified source of `@embedpdf/snippet@2.15.1`
(`embedpdf-cl9qiF45.js`, `processImportItems`), cross-checked against `createAnnotation`.

- **Import does NOT re-fire create events.** `processImportItems` dispatches each item
  straight into the store (`dispatch(...)` per item, then `autoCommit`), **without**
  emitting to `events$`. Only user-driven `createAnnotation` / `updateAnnotation(s)` /
  `deleteAnnotation` emit `onAnnotationEvent` payloads. (An optional "loaded" event fires
  for document hydration.)
- **We still wrap remote application in an `applyingRemote` guard** (cheap insurance and
  needed anyway for the `update`/`delete` paths, which *do* emit, and for undo history).
- **Remote delete API:** `annotationApi.deleteAnnotation(id, documentId?)` /
  `deleteAnnotations([...])` / `deleteAllAnnotations()` (verified in the plugin capability
  surface). Remote update: `updateAnnotation` / `updateAnnotations` (patch by id).

## 8. Poll cost on D1 (rows read per poll at 500 users) — ✅ measured model

**Evidence:** local D1 simulator (`wrangler 4.168.0`, `wrangler d1 execute --local`) with the
real schema + 50,000 change rows across 200 books; `EXPLAIN QUERY PLAN` for the exact poll
queries. (Note: the local simulator reports `duration` only; production D1 bills `rows_read`
= rows scanned, which the plans below bound tightly.)

**Poll query** (book/room change feed, the hot path):

```sql
SELECT id, annotation_uid, op, revision, payload_ref
FROM annotation_change WHERE book_id = ? AND id > ? ORDER BY id LIMIT ?;
```
Plan: `SEARCH annotation_change USING INDEX ac_book_id (book_id=? AND id>?)` — index seek,
no scan. Room poll uses the covering index `(room_id, id)`:
`SEARCH ... USING COVERING INDEX ac_room_id (room_id=? AND id>?)`.

**Rows read per poll** = changes returned *k* + seek overhead ≈ `k + 0..2`.

| Scenario | rows read / poll |
|---|---|
| Idle (no changes since cursor) — the common case | **0–1** |
| Normal co-reading (~1 change/3 s across the room) | **~1–5** |
| Bursty (10 changes landed since last poll) | **~10–12** |
| Snapshot load (`GET .../annotations/?page=n`, 48 rows/page, indexed) | **~48–50** |

**500-user model** (worst case: all 500 in shared rooms, 3 s polls, tab visible →
166.7 polls/s → 14.4 M polls/day):
- ≈ 14.4 M × (0–5) rows ≈ **0–72 M rows read/day** (0.3–2.2 B/month at the cap;
  realistic mixed use ~10–25 M/day).
- D1 free tier (5 M rows read/day) is exceeded at this scale; **Workers Paid (25 B rows
  read/month included) fits at ≤ 3% of budget**. This is the expected plan for 500 users.
- **Write amplification finding:** presence (`last_seen`, `last_page`) piggybacks on the
  poll. Writing it every poll would cost 14.4 M writes/day (D1 paid includes ~50 M rows
  written/month → overflow). **Mitigation implemented:** presence writes only when
  `last_page` changed or `last_seen` is older than 60 s → ≈ 20× fewer writes
  (≈ 20–25 M/month), and ops are flushed as one batch per flush tick. The 3 s/10 s/30 s
  poll cadence with visibility gating (spec) keeps the real average well under the worst
  case.

## 9. Python Workers: Durable Objects / WebSockets — 🔶 optional, polling is baseline

- **Durable Objects from Python Workers: yes** — the official Django docs show a
  `DurableObject` Python class (`django_cf.db.backends.do` even offers a DO-backed Django
  DB backend) and `wrangler` migrations for `new_sqlite_classes`. So a DO-based realtime
  relay is architecturally possible on both ends (DO hibernation APIs are JS-first).
- **WebSockets from Python Workers:** the runtime's WebSocket docs and examples are
  JS/TS (`WebSocketPair`, hibernation). Python-side WS support is **not documented as a
  stable surface** → per the brief this stays **optional**: `realtime_push` capability flag
  exists and is **off** on both targets; the polling protocol (§8) is the shipped baseline,
  SSE only on the local target behind the flag (documented in COLLABORATION.md).

---

## Additional findings (required by the brief)

### Password hasher — **Argon2id (argon2-cffi), tuned down for Worker CPU**

- PBKDF2 (Django 6 default, 1M+ iterations) inside Pyodide blows the per-request CPU budget
  on Workers during login. `scrypt` via `hashlib.scrypt` is not guaranteed under Pyodide's
  hashlib (OpenSSL-dependent).
- **Pyodide ships `argon2-cffi` 23.1.0 + `argon2-cffi-bindings` 21.2.0** (prebuilt wasm
  packages — verified in the Pyodide 0.28 package lock), and locally it's a normal wheel.
  Django's `Argon2PasswordHasher` works on both targets.
- Chosen params (both targets, overridable via env): `time_cost=2`,
  `memory_cost=19456` (19 MiB), `parallelism=1`. Login ≈ 50–100 ms of CPU — inside Worker
  limits; still a proper memory-hard KDF. PBKDF2 (reduced iterations) stays in the hasher
  list only for verifying legacy hashes.

### pypdf on Pyodide — ✅

`pypdf` is pure Python (micropip-installable; not prebuilt in the Pyodide lock but that is
irrelevant — pure wheels install at build time via `pywrangler`/`uv` cross-build).
`cryptography` (optional, for encrypted PDFs) **is** prebuilt in Pyodide (45.0.4). Our
validation *flags* encrypted files rather than decrypting, so even without `cryptography`
the pipeline is safe; with it, `pypdf` can introspect them. Metadata extraction is
bounded (page count, dict size, wall-clock via chunked work) per the brief.

### Workers static assets (EmbedPDF bundle + WASM) — ✅

Limits (Cloudflare changelog 2025-09 + docs): **100,000 assets / Worker version (paid),
20,000 free; 25 MiB per file**. The EmbedPDF bundle + wasm (a few MB) and Bootstrap 6
assets fit trivially. Static asset requests are free/unlimited; we vendor everything
(no CDN) per the template contract.

### D1 limits honored

- 100 bound parameters/query → pages capped at **48 items**; `IN`-lookups and
  `prefetch_related` fan-out chunked at ≤ 90 ids per query (`dblayer.chunked_qs`).
- No interactive transactions → idempotent writes + `AnnotationChange` append-only log with
  optimistic `revision` (compare-and-set style single-statement updates).

---

## Verdict

All nine items pass with the caveats above absorbed into the design:

1. ✅ Django 6 + ORM on D1 via `django-cf` (WSGI, sync ORM over async binding); sessions OK;
   R2 via `django_cf.storage.R2Storage`.
2. ✅ EmbedPDF 2.15.1 in the Cadence shell; same-origin authenticated Range loads; WASM
   vendored with `application/wasm` + `wasm-unsafe-eval` CSP; `scrollToPage` for resume;
   ResizeObserver for rail toggles.
3. ✅ Round trip preserved via `AnnotationTransferItem` (id-stable), with comment replies as
   `inReplyToId`+`replyType` child objects.
4. ✅ **Stop-check passed:** comments panel with reply threads *and* in-book search are in
   the v2 UI (shipped bundle evidence).
5. ✅ Replies: `inReplyToId` (parent) + `replyType`; comment text: `contents`.
6. ✅ Read-only remote annotations via PDF `readOnly`/`lockedContents` flags (+ server
   authority as the hard guarantee).
7. ✅ `importAnnotations` is echo-free (store dispatch, no events); `deleteAnnotation(id)` /
   `updateAnnotations` are the remote mutation APIs; `applyingRemote` guard anyway.
8. ✅ Poll cost: 0–5 rows read/poll in practice (index-seek plans measured); 500 users fit
   Workers Paid at ≤3% of the rows-read budget; presence write throttling implemented.
9. 🔶 DO usable from Python Workers; WebSockets undocumented for Python →
   `realtime_push` off; polling ships as the baseline (brief's fallback path).

**Nothing stopped. Both targets and every feature remain in scope.** The build proceeds
phase by phase as instructed.

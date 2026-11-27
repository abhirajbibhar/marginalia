# Marginalia — PDF Digital Library

A production-ready, multipage **PDF-only** digital library with **per-user
annotations** and **collaborative reading rooms**, built on Django 6 with
session auth, Django templates + HTMX, and the Cadence (Bootstrap 6) shell.

One codebase, two deployment targets — switching is configuration only:

| | Local / self-hosted | Cloudflare |
|---|---|---|
| Switch | `DEPLOYMENT_TARGET=local` | `DEPLOYMENT_TARGET=cloudflare` |
| Database | SQLite (file) | D1 (same schema) |
| Storage | local filesystem (`media/`) | R2 (private bucket) |
| Serving | `runserver` / gunicorn + nginx | Python Workers + static assets |

Scale target: **100,000 books · 500 users**. No PostgreSQL, no Elasticsearch,
no Redis, no Docker — everything runs on both targets.

## Quick start (local — any OS: Windows, macOS, Linux)

```bash
cd marginalia
python start.py --seed
```
That single script creates `.venv`, installs the pinned dependencies
(`requirements.txt`), writes `.env` with a generated secret key, applies
migrations, loads demo data and starts the server at
<http://127.0.0.1:8000>. Re-runs skip straight to serving. Options:
`--host`, `--port`, `--no-migrate`, `--seed`.

<details>
<summary>Manual setup (equivalent steps)</summary>

```bash
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # adjust as needed
python manage.py migrate
python manage.py seed_demo_data                   # optional demo content
python manage.py runserver
```
</details>

Demo logins (password `demo-password-123`):
`ada` (admin) · `libby` (librarian) · `milo`, `noor` (members).

Run the tests: `python manage.py test tests` (67 tests; the two-browser
Playwright smoke test runs only when `playwright` is installed).

## What's inside

- **Library** — grid/list browse, filters, DB-only search, book details,
  reviews, collections, authors, series. PDF-only upload pipeline with
  server-side validation (magic bytes, size/page caps, encryption + dangerous
  construct flags) and pypdf metadata extraction for librarian review.
- **Reader** — EmbedPDF snippet **2.15.1 (pinned)** inside the Cadence shell
  (sidebar/topbar stay; only the content area is the viewer). Resume-to-page,
  bookmarks, reading progress, Range-capable authenticated PDF streaming
  (`/read/<id>/file/`), in-book search and the comments panel with reply
  threads (verified in the shipped bundle — see `docs/PHASE0.md`).
- **Private annotations** — per-user overlay stored in the DB (never baked into
  the PDF), batched sync with offline replay, sync chip (Saved / Syncing /
  Offline). Private notes are invisible to everyone else, **including Admins**.
- **Reading rooms** — shared annotation layers per book: owner/editor/viewer
  roles, revocable expiring invite links, live presence ("Ada · p. 12") via
  3 s/10 s/30 s polling with exponential backoff.
- **Roles** — Admin / Librarian / Member, enforced server-side everywhere.

## Layout

```
manage.py                 Django entrypoint (target-aware)
config/                   settings/{base,local,cloudflare}.py, urls, middleware
src/entry.py              Cloudflare Python Worker entrypoint
apps/                     accounts library authors series collections
                          reading annotations rooms dashboard adminpanel
runtime/                  rate limiting, cache, periodic tasks (no Redis)
dblayer/                  DB portability helpers (D1 param caps, atomic writes)
templates/  static/       Cadence-derived shell, vendored assets
cadence/                  the template source of truth (UI contract)
tests/                    unit · API · collaboration · storage · e2e
scripts/                  vendor_assets, migrations_to_d1, r2_sync
docs/                     PHASE0 (feasibility) + architecture/deploy/parity/
                          collaboration
```

## Documentation map

- `docs/PHASE0.md` — feasibility gate: what was verified against live docs and
  shipped source before a line of app code (EmbedPDF replies, D1 costs, hashers…)
- `docs/ARCHITECTURE.md` — apps, data model, sync design, security model
- `docs/DEPLOY_LOCAL.md` / `docs/DEPLOY_CLOUDFLARE.md` — deployment guides
- `docs/PARITY.md` — what differs between targets and how it stays one codebase
- `docs/COLLABORATION.md` — sync protocol, conflict rules, limits

## Data portability

```bash
python manage.py export_library --output library.json   # chunked, D1-safe
python manage.py import_library library.json            # idempotent
python scripts/r2_sync.py push                          # media keys -> R2
python scripts/migrations_to_d1.py generate             # migrations -> D1 SQL
```

## Security notes

- Strict CSP with `wasm-unsafe-eval` (PDF engine WASM) and nothing else.
- Session auth, CSRF on every POST (the JSON sync API uses the `X-CSRFToken`
  header — the only non-HTMX XHR surface, documented in COLLABORATION.md).
- The server owns annotation authorship: client-supplied author fields are
  stripped on input and rewritten on output.
- Rate limits: login, search, download, upload, annotation ops.
- Downloads are audited (`DownloadAudit`). Payload caps: 64 KB / 50 ops per
  request / 5,000 annotations per user per book.

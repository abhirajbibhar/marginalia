# Parity — what differs between targets (and why it stays one codebase)

Everything not listed here is literally the same code running on both targets.
The differences are confined to **four seams**: settings, database backend,
storage backend, and capability flags.

## The seams

| Concern | Local (`DEPLOYMENT_TARGET=local`) | Cloudflare (`…=cloudflare`) | Where |
|---|---|---|---|
| DB engine | `django.db.backends.sqlite3` | `django_cf.db.backends.d1` | `config/settings/*` |
| Transactions | real (`AtomicWrite` commits) | none (`atomic` is a no-op) | `dblayer.AtomicWrite` |
| Bind params | unlimited | 90 max per statement | `dblayer.chunked*` |
| Storage | `FileSystemStorage` | `django_cf.storage.R2Storage` | `library.storage` |
| Ranged reads | file slicing | R2 ranged get (binding) | `BookStorage.open_range` |
| Uploads | authenticated PUT endpoint | presigned direct-to-R2 (SigV4) | `library.upload.presign_put_url` |
| File URLs | `MEDIA_URL` (dev only) | never exposed (streamed via `/read/…/file/`) | `BookStorage.url` |
| Secrets | `.env` | Wrangler secrets via `workers.env` | `config/settings/cloudflare.py` |
| Static | `runserver`/nginx | Workers static assets | `wrangler.jsonc` |
| Cron | system crontab | Cron Trigger → `/manage/tasks/` | `apps/adminpanel` |
| Realtime push | optional SSE behind flag | off (polling baseline) | `library.capabilities` |

## Rules that keep the ORM portable

1. **No `transaction.atomic` reliance.** Multi-row invariants are written as
   ordered, idempotent single statements (see the annotation ops engine:
   create → change row; replaying the same create is a no-op by design).
2. **No raw SQL.** All queries go through the ORM.
3. **Chunked `IN` lookups** (`dblayer.in_chunks`, ≤90 values) and 48-item pages
   — D1's bound-parameter cap.
4. **Integer PKs everywhere** (`DEFAULT_AUTO_FIELD = AutoField`) — keeps D1
   indexes compact and cursors cheap (`AnnotationChange.id` doubles as the
   sync cursor).
5. **No `select_for_update`, no `extra()`, no `annotate` with DB-specific
   functions.** Aggregations used (`Count`, `Avg`) exist on both engines.

## Pure-Python dependency policy

Everything in `pyproject.toml` must be pure Python or available as a Pyodide
wheel:

- `django` 6.x — pure Python (supported on Python Workers per Cloudflare docs)
- `pypdf` — pure Python (micropip-installable)
- `argon2-cffi` — **prebuilt Pyodide wheel** (23.1.0 + bindings, verified in
  the Pyodide package lock)
- `django-cf`, `workers-runtime-sdk` — Cloudflare target only (optional extra)

Forbidden by policy (and absent): PostgreSQL drivers, Elasticsearch clients,
Redis, subprocess-based tools.

## Feature capability flags

`apps/library/capabilities.py` is the single source of truth
(`capabilities.describe()` is shown on the admin dashboard):

```
target, storage, direct_upload, transactions, realtime_push, background_jobs
```

Code that would behave differently per target must consult this module — never
`settings.DEPLOYMENT_TARGET` directly (except settings modules themselves).

## Verifying parity

- `tests/test_storage.py` runs the storage/validation/capability contract on
  real SQLite + a temp directory.
- The same tests are intended to run against `wrangler dev --local` (D1/R2
  local mode) before deploying: `DEPLOYMENT_TARGET=cloudflare uv run pywrangler
  dev` serves the app; `python manage.py test` runs against local-mode D1 when
  the bindings are present.
- `docs/PHASE0.md` documents the per-target verifications (hashers, WASM/CSP,
  D1 budgets, WebSockets status).

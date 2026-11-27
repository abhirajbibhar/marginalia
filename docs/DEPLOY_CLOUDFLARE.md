# Deploy — Cloudflare (Python Workers + D1 + R2)

Target: serverless. `DEPLOYMENT_TARGET=cloudflare`. Django runs under Pyodide
inside a Python Worker (WSGI via `django-cf`), D1 holds the schema, R2 holds
PDFs and covers in a **private** bucket, static assets are served by Workers
static assets.

## 0. Prerequisites

- A Cloudflare account with Workers (paid plan recommended — Phase 0 §8 shows
  500 users fit comfortably inside the paid rows-read budget but exceed free).
- Node ≥ 20 (`npx wrangler`), Python 3.12+ with `uv`.

## 1. Create the backing services

```bash
npx wrangler d1 create marginalia           # paste the id into wrangler.jsonc
npx wrangler r2 bucket create marginalia-media
```

Apply the schema (converted from Django migrations):

```bash
python scripts/migrations_to_d1.py generate
npx wrangler d1 migrations apply marginalia --remote
```

## 2. Secrets

```bash
npx wrangler secret put DJANGO_SECRET_KEY
npx wrangler secret put ALLOWED_HOSTS          # library.example.com
npx wrangler secret put R2_ACCOUNT_ID
npx wrangler secret put R2_ACCESS_KEY_ID       # R2 S3 API token (write-only ok)
npx wrangler secret put R2_SECRET_ACCESS_KEY
npx wrangler secret put R2_BUCKET_NAME
npx wrangler secret put TASKS_SECRET
```

The R2 S3 credentials are only used to **presign direct uploads** (pure-Python
SigV4 in `apps/library/upload.py`); the bucket stays private and reads happen
through the R2 binding after a permission check.

## 3. Build & deploy

```bash
pip install -e ".[cloudflare]"         # django-cf, workers-runtime-sdk
bash scripts/vendor_assets.sh          # static/ incl. EmbedPDF + pdfium.wasm
python manage.py collectstatic --noinput
uv run pywrangler build                # Pyodide bundle (deps incl. pypdf,
                                       # argon2-cffi prebuilt wheels)
npx wrangler deploy
```

## 4. Cron maintenance

`wrangler.jsonc` ships a Cron Trigger (`17 * * * *`) that hits
`/manage/tasks/` with `X-Tasks-Secret`, which runs
`compact_annotation_changes` and purges rate-limit buckets.

## 5. First run

- Sign up flow: create the first user via `wrangler d1 execute` or promote one
  (`update accounts_profile set role='admin'`).
- Seed demo content locally against `wrangler dev --local` if desired.

## Cloudflare-specific notes (verified in docs/PHASE0.md)

- **No transactions**: D1 backends make `transaction.atomic` a no-op. All
  writes are small idempotent units; the annotation ops engine is replay-safe.
- **100 bound parameters / query**: pages cap at 48; `IN` lookups chunked at 90.
- **CPU budget**: Argon2id params are deliberately light
  (`time_cost=2, memory_cost=19MiB, parallelism=1`) so login fits the Worker
  budget; metadata extraction is I/O-bounded by `RangeReader` budgets.
- **WASM**: `pdfium.wasm` is served as a static asset (`application/wasm`) and
  the CSP allows `wasm-unsafe-eval`; the engine's worker uses `worker-src blob:`.
- **Asset limits**: 100k files / 25 MiB per file (paid) — the vendored bundle
  and WASM fit easily. All assets are local; no CDN dependencies
  (`fontFallback: null`).
- **Presence writes** are throttled (page change or 60 s) so the poll piggyback
  stays inside the D1 write budget at 500 users.

## Static assets & routing

`wrangler.jsonc` serves `staticfiles/` directly (`run_worker_first` keeps
`/api`, `/read`, `/accounts`, `/library`, `/rooms`, `/admin`, `/manage` on the
Django path). After any front-end change: `collectstatic` + `wrangler deploy`.

# Deploy — local / self-hosted

Target: one local server, SQLite + local filesystem (PDFs and database both
local). `DEPLOYMENT_TARGET=local`.

## 1. Install

```bash
cd marginalia
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # Django 6, pypdf, argon2-cffi, sqlparse
cp .env.example .env        # set DJANGO_SECRET_KEY, ALLOWED_HOSTS, TASKS_SECRET
```

## 2. Migrate & seed

```bash
python manage.py migrate
python manage.py seed_demo_data    # optional demo content
python manage.py runserver         # development
```

## 3. Production (gunicorn + nginx)

```bash
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

Nginx responsibilities (Django serves media only in `DEBUG`):

- Terminate TLS, set `X-Forwarded-Proto`.
- Serve `/static/` from `staticfiles/` (`python manage.py collectstatic`).
- Serve `/media/` **or** proxy it to Django (the app's `/read/<id>/file/` is
  the authenticated, audited path; `media/` in nginx is only acceptable for
  trusted private networks).
- Pass everything else to gunicorn.

Example:

```nginx
server {
  listen 443 ssl;
  server_name library.example.com;
  client_max_body_size 210m;          # MAX_PDF_SIZE_MB + headroom

  location /static/ { alias /srv/marginalia/staticfiles/; }
  location /media/  { alias /srv/marginalia/media/; }   # private network only

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 120s;
  }
}
```

## 4. Periodic maintenance

Cron (hourly) — compacts the change feed and purges rate-limit buckets:

```cron
17 * * * * cd /srv/marginalia && .venv/bin/python manage.py compact_annotation_changes
```

(Or POST `/manage/tasks/` with the `X-Tasks-Secret` header — the same endpoint
Cloudflare Cron Triggers use.)

## 5. Backups

- `db.sqlite3` — copy with `sqlite3 db.sqlite3 ".backup backup.sqlite3"`.
- `media/` — rsync/tar; keys in the DB match paths under `media/`.
- Portable snapshot: `python manage.py export_library --output library.json`.

## Notes

- **Range requests** (`/read/<id>/file/` supports `bytes=`) let the viewer
  stream large PDFs; ensure nginx does not swallow `Range` on proxied routes.
- **Argon2id** hashing params are tuned for modest CPUs
  (`ARGON2_*` env vars); raise them on beefier hardware.
- The two-context Playwright smoke test runs against this deployment:
  `E2E_BASE_URL=http://127.0.0.1:8000 python -m pytest tests/e2e -q`.

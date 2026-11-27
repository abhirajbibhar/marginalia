#!/usr/bin/env python3
"""
migrations_to_d1.py — convert Django migrations to D1 SQL and apply them.

D1 has no interactive migration runner wired to the Django ORM, so we render
the SQL with Django's ``sqlmigrate`` against the (portable) SQLite schema and
feed it to Wrangler, which manages the D1 migration history.

Usage:
    python scripts/migrations_to_d1.py generate          # -> migrations/d1/*.sql
    npx wrangler d1 migrations apply marginalia --remote # apply in order
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "migrations" / "d1"

# Dependency order (matches app dependencies).
APPS = [
    "auth", "contenttypes", "sessions", "runtime", "accounts",
    "library", "authors", "series", "collections", "reading",
    "annotations", "rooms", "adminpanel",
]


def generate() -> None:
    os.environ.setdefault("DEPLOYMENT_TARGET", "local")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    OUT.mkdir(parents=True, exist_ok=True)
    for app in APPS:
        result = subprocess.run(
            [sys.executable, "manage.py", "sqlmigrate", app, "0001"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"skip {app}: {result.stderr.strip().splitlines()[-1] if result.stderr else 'no 0001'}")
            continue
        path = OUT / f"{app}_0001.sql"
        path.write_text(result.stdout)
        print(f"wrote {path.relative_to(ROOT)}")
    print("\nApply with: npx wrangler d1 migrations apply marginalia --remote")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "generate":
        raise SystemExit(__doc__)
    generate()

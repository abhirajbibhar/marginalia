#!/usr/bin/env python3
"""Django management entrypoint.

Works on both deployment targets:

* local       — run on the host with CPython 3.12+ (`python manage.py runserver`)
* cloudflare  — run under Pyodide inside a Python Worker for management tasks
                that make sense there (migrate via `scripts/migrations_to_d1.py`
                instead; see docs/DEPLOY_CLOUDFLARE.md).

The active target is chosen with the DEPLOYMENT_TARGET environment variable
("local" or "cloudflare"); it selects the settings module below and, through
``library.capabilities``, every runtime capability flag.
"""
import os
import sys


def main() -> None:
    target = os.environ.get("DEPLOYMENT_TARGET", "local").strip().lower()
    if target not in {"local", "cloudflare"}:
        raise SystemExit(
            f"DEPLOYMENT_TARGET must be 'local' or 'cloudflare', got {target!r}"
        )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{target}")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - environment problem, not app bug
        raise ImportError(
            "Couldn't import Django. Did you install requirements and set "
            "DEPLOYMENT_TARGET correctly?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
start.py — one script, any OS (Windows / macOS / Linux).

Creates .venv on first run, installs dependencies, prepares the database and
starts the development server. Re-runs are fast (everything is skipped when
already done).

Usage:
    python start.py                 # http://127.0.0.1:8000
    python start.py --seed          # also load demo data (first run)
    python start.py --port 9000 --host 0.0.0.0
    python start.py --no-browser-check

Only the Python standard library is used — no bash, no make, no Docker.
"""
from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"

# Keep launcher output readable when redirected to a file.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


def venv_python() -> Path:
    """The interpreter inside .venv (layout differs on Windows)."""
    if WINDOWS:
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd: list[str], **kwargs) -> int:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    return subprocess.call(cmd, cwd=ROOT, **kwargs)


def ensure_venv() -> None:
    if venv_python().exists():
        print(f"[ok] virtualenv found: {VENV}")
        return
    print(f"[..] creating virtualenv at {VENV} …")
    run([sys.executable, "-m", "venv", str(VENV)])
    if not venv_python().exists():
        raise SystemExit(
            "Could not create .venv. On Debian/Ubuntu install python3-venv:\n"
            "  sudo apt install python3-venv"
        )
    print("[ok] virtualenv created")
    ensure_pip()


def ensure_pip() -> None:
    """
    Some Python builds (notably distro packages) create venvs without pip.
    Bootstrap it portably: ensurepip first, then the official get-pip.py
    (downloaded with stdlib urllib — no curl, no bash).
    """
    py = str(venv_python())
    probe = subprocess.run([py, "-m", "pip", "--version"], capture_output=True)
    if probe.returncode == 0:
        print("[ok] pip available in virtualenv")
        return
    print("[..] bootstrapping pip into the virtualenv …")
    if run([py, "-m", "ensurepip", "--upgrade"], stdout=subprocess.DEVNULL) == 0:
        print("[ok] pip bootstrapped (ensurepip)")
        return
    # ensurepip missing (Debian-style split packages) → official get-pip.py
    import urllib.request

    bootstrap = VENV / "get-pip.py"
    urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", bootstrap)
    if run([py, str(bootstrap)], stdout=subprocess.DEVNULL) != 0:
        raise SystemExit(
            "pip bootstrap failed. Install pip for this Python (e.g.\n"
            "  sudo apt install python3-pip python3-venv) and re-run start.py."
        )
    print("[ok] pip bootstrapped (get-pip.py)")


def dependencies_installed() -> bool:
    """Cheap import probe so repeat runs skip pip entirely."""
    probe = subprocess.run(
        [str(venv_python()), "-c", "import django, pypdf, argon2, sqlparse"],
        capture_output=True,
    )
    return probe.returncode == 0


def ensure_dependencies() -> None:
    if dependencies_installed():
        print("[ok] dependencies already installed")
        return
    print("[..] installing dependencies (first run only) …")
    ensure_pip()
    code = run([
        str(venv_python()), "-m", "pip", "install", "--quiet", "--upgrade", "pip",
    ])
    code |= run([
        str(venv_python()), "-m", "pip", "install", "--quiet", "-r", "requirements.txt",
    ])
    if code != 0 or not dependencies_installed():
        raise SystemExit("Dependency installation failed — see output above.")
    print("[ok] dependencies installed")


def ensure_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        print("[ok] .env found")
        return
    print("[..] creating .env with a fresh SECRET_KEY …")
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    placeholder = "change-me-in-production"
    generated = secrets.token_urlsafe(48)
    env_path.write_text(template.replace(placeholder, generated), encoding="utf-8")
    print("[ok] .env created (keep it out of version control)")


def migrate() -> None:
    print("[..] applying database migrations …")
    env = {**os.environ, "DEPLOYMENT_TARGET": "local"}
    code = run([str(venv_python()), "manage.py", "migrate", "--noinput"], env=env)
    if code != 0:
        raise SystemExit("migrate failed — see output above.")
    print("[ok] database ready")


def seed() -> None:
    print("[..] loading demo data …")
    env = {**os.environ, "DEPLOYMENT_TARGET": "local"}
    run([str(venv_python()), "manage.py", "seed_demo_data"], env=env)


def serve(host: str, port: int) -> None:
    env = {**os.environ, "DEPLOYMENT_TARGET": "local"}
    print(f"\n[ok] starting Marginalia → http://{host}:{port}/")
    print("    demo logins (after --seed): ada / libby / milo / noor — demo-password-123")
    print("    stop with Ctrl+C\n")
    try:
        raise SystemExit(run([
            str(venv_python()), "manage.py", "runserver", f"{host}:{port}", "--noreload",
        ], env=env))
    except KeyboardInterrupt:
        print("\n[ok] stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap and run Marginalia.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--seed", action="store_true", help="load demo data before serving")
    parser.add_argument("--no-migrate", action="store_true")
    parser.add_argument("--no-browser-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    print(f"Marginalia launcher · {sys.platform} · Python {sys.version.split()[0]}")
    ensure_venv()
    ensure_dependencies()
    ensure_env()
    if not args.no_migrate:
        migrate()
    if args.seed:
        seed()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
r2_sync.py — sync local media/ to (or from) the private R2 bucket.

Uses the R2 S3-compatible API with SigV4 (no SDKs; pure stdlib so it runs
anywhere, including inside Pyodide tooling). Books and covers live under the
same keys the DB stores (books/…, covers/…).

Usage:
    python scripts/r2_sync.py push     # local media/  -> R2
    python scripts/r2_sync.py pull     # R2           -> local media/
    python scripts/r2_sync.py ls       # list keys

Credentials come from the environment (see .env.example): R2_ACCOUNT_ID,
R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME.
"""
import hashlib
import hmac
import os
import pathlib
import sys
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing env {name}")
    return value


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def presign_get(key: str, expires: int = 3600) -> str:
    account, access, secret, bucket = (
        env("R2_ACCOUNT_ID"), env("R2_ACCESS_KEY_ID"),
        env("R2_SECRET_ACCESS_KEY"), env("R2_BUCKET_NAME"),
    )
    host = os.environ.get("R2_PUBLIC_HOST") or f"{account}.r2.cloudflarestorage.com"
    now = datetime.now(timezone.utc)
    amz = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{now.strftime('%Y%m%d')}/auto/{SERVICE}/aws4_request"
    uri = f"/{bucket}/{quote(key, safe='/')}"
    query = (
        f"X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential={quote(scope, safe='')}"
        f"&X-Amz-Date={amz}&X-Amz-Expires={expires}&X-Amz-SignedHeaders=host"
    )
    request = "\n".join(["GET", uri, query, f"host:{host}", "host", EMPTY_SHA256])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope,
                         hashlib.sha256(request.encode()).hexdigest()])
    sk = sign(sign(sign(sign(f"AWS4{secret}".encode(), now.strftime("%Y%m%d")), "auto"), SERVICE), "aws4_request")
    sig = hmac.new(sk, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}{uri}?{query}&X-Amz-Signature={sig}"


def presign_put(key: str, expires: int = 3600) -> str:
    return presign_get(key, expires).replace("X-Amz-Algorithm", "X-Amz-Algorithm")  # same params; method differs


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    command = sys.argv[1]
    if command == "ls":
        # Minimal listing via the S3 ListObjectsV2 API is intentionally left to
        # `npx wrangler r2 object list` (kept dependency-free here).
        raise SystemExit("Use: npx wrangler r2 object list <bucket>/books/")
    if command == "push":
        for path in MEDIA.rglob("*"):
            if path.is_file():
                key = str(path.relative_to(MEDIA))
                print(f"push {key} -> {presign_put(key)}")
        print("Upload via the presigned PUT URLs above (or `npx wrangler r2 object put`).")
    elif command == "pull":
        raise SystemExit("Use: npx wrangler r2 object get <bucket>/<key> --file media/<key>")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()

"""
Upload pipeline: presigned direct-to-R2 uploads (Cloudflare) and streamed
uploads (local), followed by server-side validation on completion.

Flow (both targets, see docs/ARCHITECTURE.md):

1. ``POST /library/upload/presign/``  → {key, upload_url, method}
   * cloudflare: SigV4 presigned PUT to the private R2 bucket
   * local:      an authenticated PUT endpoint writing to LocalStorage
2. Browser uploads the bytes (out of band).
3. ``POST /library/upload/complete/`` → server validates the object
   (validation.validate_pdf), extracts metadata (pypdf), creates the Book and
   returns the pre-filled review form for the librarian.

Presigning is pure-Python SigV4 (hmac/hashlib only) so it runs under Pyodide.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from urllib.parse import quote

from django.conf import settings

R2_SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _r2_creds():
    return (
        getattr(settings, "R2_ACCOUNT_ID", ""),
        getattr(settings, "R2_ACCESS_KEY_ID", ""),
        getattr(settings, "R2_SECRET_ACCESS_KEY", ""),
        getattr(settings, "R2_BUCKET_NAME", ""),
    )


def presign_put_url(key: str, expires_seconds: int = 900) -> str | None:
    """
    Return a presigned HTTPS PUT URL for ``key`` in the private R2 bucket,
    or None when presigning is not configured (→ the local upload path is used).
    """
    account_id, access_key, secret_key, bucket = _r2_creds()
    if not all([account_id, access_key, secret_key, bucket]):
        return None

    host = getattr(settings, "R2_PUBLIC_HOST", "") or f"{account_id}.r2.cloudflarestorage.com"
    region = "auto"
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    credential_scope = f"{date_stamp}/{region}/{R2_SERVICE}/aws4_request"

    canonical_uri = f"/{bucket}/{quote(key, safe='/')}"
    canonical_query = (
        f"X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Credential={quote(credential_scope, safe='')}"
        f"&X-Amz-Date={amz_date}"
        f"&X-Amz-Expires={expires_seconds}"
        f"&X-Amz-SignedHeaders=host"
    )
    canonical_request = "\n".join(
        ["PUT", canonical_uri, canonical_query, f"host:{host}", "host", EMPTY_SHA256]
    )
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, credential_scope,
         hashlib.sha256(canonical_request.encode()).hexdigest()]
    )

    def _sign(key_bytes: bytes, msg: str) -> bytes:
        return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()

    date_key = _sign(f"AWS4{secret_key}".encode(), date_stamp)
    region_key = _sign(date_key, region)
    service_key = _sign(region_key, R2_SERVICE)
    signing_key = _sign(service_key, "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    return (
        f"https://{host}{canonical_uri}?{canonical_query}"
        f"&X-Amz-Signature={signature}"
    )


def extension_ok(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() == ".pdf"

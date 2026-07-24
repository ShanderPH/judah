"""Provider signature validation shared by canonical webhook endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Protocol


class SignedRequest(Protocol):
    """Minimum request surface required for signature validation."""

    body: bytes
    method: str
    headers: object

    def build_absolute_uri(self) -> str: ...


HUBSPOT_V3_MAX_AGE_MS = 5 * 60 * 1000
_HUBSPOT_URI_DECODINGS = {
    "%3A": ":",
    "%2F": "/",
    "%3F": "?",
    "%40": "@",
    "%21": "!",
    "%24": "$",
    "%27": "'",
    "%28": "(",
    "%29": ")",
    "%2A": "*",
    "%2C": ",",
    "%3B": ";",
}


def _header(request: SignedRequest, name: str) -> str:
    return str(request.headers.get(name, ""))  # type: ignore[attr-defined]


def verify_hubspot_signature_v1(request: SignedRequest, secret: str) -> bool:
    """Verify the legacy SHA-256 app-secret plus raw-body signature."""
    signature = _header(request, "X-HubSpot-Signature")
    if not signature:
        return False
    expected = hashlib.sha256(secret.encode("utf-8") + request.body).hexdigest()
    return hmac.compare_digest(signature, expected)


def _decode_hubspot_v3_uri(uri: str) -> str:
    decoded = uri
    for encoded, plain in _HUBSPOT_URI_DECODINGS.items():
        decoded = decoded.replace(encoded, plain).replace(encoded.lower(), plain)
    return decoded


def verify_hubspot_signature_v3(
    request: SignedRequest,
    secret: str,
    *,
    now_ms: int | None = None,
) -> bool:
    """Verify HubSpot v3 HMAC, Base64 digest, URI decoding, and replay window."""
    signature = _header(request, "X-HubSpot-Signature-v3")
    timestamp = _header(request, "X-HubSpot-Request-Timestamp")
    if not signature or not timestamp:
        return False
    try:
        timestamp_ms = int(timestamp)
    except ValueError:
        return False

    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    age_ms = current_ms - timestamp_ms
    if age_ms < 0 or age_ms > HUBSPOT_V3_MAX_AGE_MS:
        return False

    method = request.method.upper()
    uri = _decode_hubspot_v3_uri(request.build_absolute_uri())
    source = method.encode("utf-8") + uri.encode("utf-8") + request.body + timestamp.encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), source, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(signature, expected)


def is_valid_hubspot_request(request: SignedRequest, secret: str) -> bool:
    """Accept a request when either the supported v1 or v3 signature matches."""
    return verify_hubspot_signature_v1(request, secret) or verify_hubspot_signature_v3(request, secret)


__all__ = [
    "HUBSPOT_V3_MAX_AGE_MS",
    "is_valid_hubspot_request",
    "verify_hubspot_signature_v1",
    "verify_hubspot_signature_v3",
]

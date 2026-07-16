"""Tests for canonical HubSpot request signature validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from apps.webhooks.signatures import verify_hubspot_signature_v3


@dataclass
class FakeRequest:
    body: bytes
    method: str
    uri: str
    headers: dict[str, str]

    def build_absolute_uri(self) -> str:
        return self.uri


def _signature(secret: str, method: str, uri: str, body: bytes, timestamp: str) -> str:
    source = method.encode() + uri.encode() + body + timestamp.encode()
    return base64.b64encode(hmac.new(secret.encode(), source, hashlib.sha256).digest()).decode()


def test_hubspot_v3_accepts_official_base64_contract() -> None:
    now_ms = 1_800_000_000_000
    timestamp = str(now_ms - 1_000)
    secret = "secret"
    body = b'{"event":"ok"}'
    uri = "https://example.test/api/v1/webhooks/hubspot/"
    request = FakeRequest(
        body=body,
        method="POST",
        uri=uri,
        headers={
            "X-HubSpot-Request-Timestamp": timestamp,
            "X-HubSpot-Signature-v3": _signature(secret, "POST", uri, body, timestamp),
        },
    )

    assert verify_hubspot_signature_v3(request, secret, now_ms=now_ms) is True


def test_hubspot_v3_rejects_replayed_timestamp() -> None:
    now_ms = 1_800_000_000_000
    timestamp = str(now_ms - 301_000)
    secret = "secret"
    body = b"{}"
    uri = "https://example.test/webhook"
    request = FakeRequest(
        body=body,
        method="POST",
        uri=uri,
        headers={
            "X-HubSpot-Request-Timestamp": timestamp,
            "X-HubSpot-Signature-v3": _signature(secret, "POST", uri, body, timestamp),
        },
    )

    assert verify_hubspot_signature_v3(request, secret, now_ms=now_ms) is False


def test_hubspot_v3_decodes_required_uri_characters() -> None:
    now_ms = 1_800_000_000_000
    timestamp = str(now_ms)
    secret = "secret"
    encoded_uri = "https://example.test/hooks/a%2Fb"
    decoded_uri = "https://example.test/hooks/a/b"
    body = b"{}"
    request = FakeRequest(
        body=body,
        method="POST",
        uri=encoded_uri,
        headers={
            "X-HubSpot-Request-Timestamp": timestamp,
            "X-HubSpot-Signature-v3": _signature(secret, "POST", decoded_uri, body, timestamp),
        },
    )

    assert verify_hubspot_signature_v3(request, secret, now_ms=now_ms) is True

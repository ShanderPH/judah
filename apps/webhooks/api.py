"""Django Ninja API endpoints for webhooks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import TYPE_CHECKING, Any

import structlog
from ninja import Body, Router

from apps.webhooks.services import process_webhook_event, record_webhook_event

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = structlog.get_logger(__name__)

router = Router()

_HUBSPOT_V3_MAX_AGE_MS = 5 * 60 * 1000
_HUBSPOT_V3_QUERY_DECODE_PATTERN = re.compile(
    r"%3A|%2F|%3F|%40|%21|%24|%27|%28|%29|%2A|%2C|%3B",
    flags=re.IGNORECASE,
)
_HUBSPOT_V3_QUERY_DECODE_MAP = {
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


def _verify_hubspot_signature_v1(request: HttpRequest, secret: str) -> bool:
    """Verify HubSpot v1 signature: SHA-256(client_secret + request_body).

    Sent in the ``X-HubSpot-Signature`` header for private apps.
    """
    signature = request.headers.get("X-HubSpot-Signature", "")
    if not signature:
        return False
    body = request.body.decode("utf-8")
    expected = hashlib.sha256((secret + body).encode("utf-8")).hexdigest()
    return hmac.compare_digest(signature, expected)


def _verify_hubspot_signature_v3(request: HttpRequest, secret: str) -> bool:
    """Verify HubSpot v3 signature: Base64 HMAC-SHA256(method + URL + body + timestamp).

    Sent in the ``X-HubSpot-Signature-v3`` header for newer private apps.
    """
    signature = request.headers.get("X-HubSpot-Signature-v3", "")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp", "")
    if not signature or not timestamp:
        return False

    try:
        timestamp_ms = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time() * 1000) - timestamp_ms) > _HUBSPOT_V3_MAX_AGE_MS:
        return False

    method = request.method.upper()
    url = _decode_hubspot_v3_uri(request.build_absolute_uri())
    body = request.body.decode("utf-8")
    source = f"{method}{url}{body}{timestamp}"
    digest = hmac.new(secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(signature, expected)


def _decode_hubspot_v3_uri(uri: str) -> str:
    """Decode only the query characters required by HubSpot signature v3."""
    uri = uri.split("#", maxsplit=1)[0]
    query_position = uri.find("?")
    if query_position == -1:
        return uri
    path = uri[: query_position + 1]
    query = uri[query_position + 1 :]
    decoded_query = _HUBSPOT_V3_QUERY_DECODE_PATTERN.sub(
        lambda match: _HUBSPOT_V3_QUERY_DECODE_MAP[match.group(0).upper()],
        query,
    )
    return path + decoded_query


def _is_valid_hubspot_request(request: HttpRequest, secret: str) -> bool:
    """Accept if either v1 or v3 signature matches."""
    return _verify_hubspot_signature_v1(request, secret) or _verify_hubspot_signature_v3(request, secret)


def _verify_jira_signature(request: HttpRequest, secret: str) -> bool:
    """Verify Jira webhook signature: HMAC-SHA256 of the raw body.

    Sent in the ``X-Hub-Signature`` header as ``sha256=<hmac>``.
    """
    signature_header = request.headers.get("x-hub-signature", "")
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    signature = signature_header[7:]
    expected = hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/hubspot/", response={202: dict}, auth=None, summary="HubSpot webhook receiver")
def hubspot_webhook(request: HttpRequest, payload: list[dict[str, Any]]) -> tuple[int, dict]:
    """Receive and queue HubSpot CRM webhook events.

    Events are always recorded to the database for auditing.
    Processing is skipped (with a warning) only when a secret is configured
    and neither the v1 nor v3 signature matches.
    """
    from django.conf import settings

    return _receive_hubspot_webhook(request, payload, settings.HUBSPOT_APP_SECRET or "", "production")


@router.post(
    "/hubspot/sandbox/",
    response={202: dict},
    auth=None,
    summary="HubSpot sandbox webhook receiver",
)
def hubspot_sandbox_webhook(request: HttpRequest, payload: list[dict[str, Any]]) -> tuple[int, dict]:
    """Receive sandbox events using the sandbox app's isolated HMAC secret."""
    from django.conf import settings

    return _receive_hubspot_webhook(
        request,
        payload,
        settings.HUBSPOT_SANDBOX_APP_SECRET or "",
        "sandbox",
    )


def _receive_hubspot_webhook(
    request: HttpRequest,
    payload: list[dict[str, Any]],
    secret: str,
    environment: str,
) -> tuple[int, dict]:
    """Verify, record, and dispatch HubSpot events for one app environment."""
    from django.conf import settings
    from ninja.errors import HttpError

    if not secret:
        # Fail-closed: only tolerate a missing secret in explicit local DEBUG mode.
        # In any other environment this is a misconfiguration that MUST reject
        # traffic — silently accepting unsigned webhooks would let anyone forge
        # HubSpot events against production.
        if not getattr(settings, "DEBUG", False):
            logger.error("hubspot_webhook_secret_missing", environment=environment)
            raise HttpError(500, f"HubSpot {environment} webhook secret not configured")
        signature_ok = True
    else:
        signature_ok = _is_valid_hubspot_request(request, secret)

    if not signature_ok:
        logger.warning(
            "hubspot_webhook_invalid_signature",
            environment=environment,
            has_v1_header=bool(request.headers.get("X-HubSpot-Signature")),
            has_v3_header=bool(request.headers.get("X-HubSpot-Signature-v3")),
        )

    events_queued = 0
    for item in payload:
        event_type = item.get("subscriptionType", "unknown")

        # Always persist the raw event for auditability
        event = record_webhook_event(source="hubspot", event_type=event_type, payload=item)

        if not signature_ok:
            logger.warning(
                "hubspot_webhook_event_skipped_bad_signature",
                event_type=event_type,
                object_id=item.get("objectId"),
                event_db_id=str(event.pk),
            )
            continue

        process_webhook_event(event.pk)
        events_queued += 1

    status = "accepted" if signature_ok else "signature_mismatch"
    return 202, {"status": status, "events_queued": events_queued, "events_received": len(payload)}


@router.post("/jira/", response={202: dict}, auth=None, summary="Jira webhook receiver")
def jira_webhook(request: HttpRequest, payload: Body[dict[str, Any]]) -> tuple[int, dict]:
    """Receive and queue Jira webhook events."""
    from django.conf import settings
    from ninja.errors import HttpError

    secret = getattr(settings, "JIRA_WEBHOOK_SECRET", "")
    if not secret:
        if not getattr(settings, "DEBUG", False):
            logger.error("jira_webhook_secret_missing")
            raise HttpError(500, "Jira webhook secret not configured")
        signature_ok = True
    else:
        signature_ok = _verify_jira_signature(request, secret)

    if not signature_ok:
        logger.warning("jira_webhook_invalid_signature", signature_header=request.headers.get("x-hub-signature", ""))
        raise HttpError(401, "Invalid Jira webhook signature")

    event_type = payload.get("webhookEvent", "unknown")
    event = record_webhook_event(source="jira", event_type=event_type, payload=payload)
    process_webhook_event(event.pk)
    return 202, {"status": "accepted", "event_id": str(event.pk)}

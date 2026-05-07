"""Django Ninja API endpoints for webhooks."""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Any

import structlog
from ninja import Body, Router

from apps.webhooks.services import process_webhook_event, record_webhook_event

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = structlog.get_logger(__name__)

router = Router()


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
    """Verify HubSpot v3 signature: HMAC-SHA256(timestamp + method + url + body).

    Sent in the ``X-HubSpot-Signature-v3`` header for newer private apps.
    """
    signature = request.headers.get("X-HubSpot-Signature-v3", "")
    timestamp = request.headers.get("X-HubSpot-Request-Timestamp", "")
    if not signature or not timestamp:
        return False
    method = request.method.upper()
    url = request.build_absolute_uri()
    body = request.body.decode("utf-8")
    source = f"{timestamp}{method}{url}{body}"
    expected = hmac.new(secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


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
    from ninja.errors import HttpError

    secret = settings.HUBSPOT_APP_SECRET or ""
    if not secret:
        # Fail-closed: only tolerate a missing secret in explicit local DEBUG mode.
        # In any other environment this is a misconfiguration that MUST reject
        # traffic — silently accepting unsigned webhooks would let anyone forge
        # HubSpot events against production.
        if not getattr(settings, "DEBUG", False):
            logger.error("hubspot_webhook_secret_missing")
            raise HttpError(500, "HubSpot webhook secret not configured")
        signature_ok = True
    else:
        signature_ok = _is_valid_hubspot_request(request, secret)

    if not signature_ok:
        logger.warning(
            "hubspot_webhook_invalid_signature",
            v1_header=request.headers.get("X-HubSpot-Signature", ""),
            v3_header=request.headers.get("X-HubSpot-Signature-v3", ""),
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

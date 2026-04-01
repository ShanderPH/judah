"""Django Ninja API endpoints for webhooks."""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Any

import structlog
from ninja import Router

from apps.webhooks.services import process_webhook_event, record_webhook_event

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = structlog.get_logger(__name__)

router = Router()


def _verify_hubspot_signature(request: HttpRequest, secret: str) -> bool:
    """Verify the HubSpot webhook signature (v1 format for private apps).

    Private apps use v1: SHA-256(client_secret + request_body).
    HubSpot sends this value in the ``X-HubSpot-Signature`` header.
    """
    signature = request.headers.get("X-HubSpot-Signature", "")
    if not signature:
        return False
    body = request.body.decode("utf-8")
    source = secret + body
    expected = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return hmac.compare_digest(signature, expected)


@router.post("/hubspot/", response={202: dict}, auth=None, summary="HubSpot webhook receiver")
def hubspot_webhook(request: HttpRequest, payload: list[dict[str, Any]]) -> tuple[int, dict]:
    """Receive and queue HubSpot CRM webhook events."""
    from django.conf import settings

    if settings.HUBSPOT_APP_SECRET and not _verify_hubspot_signature(request, settings.HUBSPOT_APP_SECRET):
        logger.warning("hubspot_webhook_invalid_signature")
        return 202, {"status": "ignored", "reason": "invalid signature"}

    events_queued = 0
    for item in payload:
        event_type = item.get("subscriptionType", "unknown")
        event = record_webhook_event(source="hubspot", event_type=event_type, payload=item)
        process_webhook_event(event.pk)
        events_queued += 1

    return 202, {"status": "accepted", "events_queued": events_queued}


@router.post("/jira/", response={202: dict}, auth=None, summary="Jira webhook receiver")
def jira_webhook(request: HttpRequest, payload: dict[str, Any]) -> tuple[int, dict]:
    """Receive and queue Jira webhook events."""
    event_type = payload.get("webhookEvent", "unknown")
    event = record_webhook_event(source="jira", event_type=event_type, payload=payload)
    process_webhook_event(event.pk)
    return 202, {"status": "accepted", "event_id": event.pk}

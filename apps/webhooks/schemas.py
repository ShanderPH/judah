"""Pydantic v2 schemas for webhook endpoints."""

from datetime import datetime
from typing import Any

from ninja import Schema


class WebhookEventResponse(Schema):
    """Public webhook event representation."""

    id: int
    source: str
    event_type: str
    status: str
    retry_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class HubSpotWebhookPayload(Schema):
    """Incoming HubSpot webhook payload envelope."""

    objectId: int
    propertyName: str | None = None
    propertyValue: str | None = None
    changeSource: str | None = None
    eventId: int | None = None
    subscriptionId: int | None = None
    portalId: int | None = None
    appId: int | None = None
    occurredAt: int | None = None
    subscriptionType: str | None = None


class JiraWebhookPayload(Schema):
    """Incoming Jira webhook payload envelope."""

    webhookEvent: str
    issue: dict[str, Any] | None = None
    user: dict[str, Any] | None = None
    changelog: dict[str, Any] | None = None

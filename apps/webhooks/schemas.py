"""Pydantic v2 schemas for webhook endpoints."""

from typing import TYPE_CHECKING, Any

from ninja import Schema
from pydantic import Field

if TYPE_CHECKING:
    from datetime import datetime


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

    model_config = {"populate_by_name": True}  # noqa: RUF012

    object_id: int = Field(alias="objectId")
    property_name: str | None = Field(None, alias="propertyName")
    property_value: str | None = Field(None, alias="propertyValue")
    change_source: str | None = Field(None, alias="changeSource")
    event_id: int | None = Field(None, alias="eventId")
    subscription_id: int | None = Field(None, alias="subscriptionId")
    portal_id: int | None = Field(None, alias="portalId")
    app_id: int | None = Field(None, alias="appId")
    occurred_at: int | None = Field(None, alias="occurredAt")
    subscription_type: str | None = Field(None, alias="subscriptionType")


class JiraWebhookPayload(Schema):
    """Incoming Jira webhook payload envelope."""

    model_config = {"populate_by_name": True}  # noqa: RUF012

    webhook_event: str = Field(alias="webhookEvent")
    issue: dict[str, Any] | None = None
    user: dict[str, Any] | None = None
    changelog: dict[str, Any] | None = None

"""Validation tests for the webhook Ninja schemas (pydantic v2)."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.webhooks.schemas import (
    HubSpotWebhookPayload,
    JiraWebhookPayload,
    WebhookEventResponse,
)


class TestHubSpotWebhookPayload:
    def test_accepts_hubspot_camelcase_aliases(self) -> None:
        payload = HubSpotWebhookPayload.model_validate(
            {
                "objectId": 42,
                "propertyName": "hs_pipeline_stage",
                "propertyValue": "939275052",
                "eventId": 7,
                "subscriptionType": "ticket.propertyChange",
            }
        )
        assert payload.object_id == 42
        assert payload.property_name == "hs_pipeline_stage"
        assert payload.subscription_type == "ticket.propertyChange"

    def test_accepts_snake_case_by_field_name(self) -> None:
        payload = HubSpotWebhookPayload.model_validate(
            {"object_id": 1, "property_name": "foo", "property_value": "bar"}
        )
        assert payload.object_id == 1
        assert payload.property_name == "foo"

    def test_optional_fields_default_to_none(self) -> None:
        payload = HubSpotWebhookPayload.model_validate({"objectId": 1})
        assert payload.property_name is None
        assert payload.property_value is None
        assert payload.portal_id is None


class TestJiraWebhookPayload:
    def test_webhook_event_alias(self) -> None:
        payload = JiraWebhookPayload.model_validate({"webhookEvent": "jira:issue_created", "issue": {"key": "X-1"}})
        assert payload.webhook_event == "jira:issue_created"
        assert payload.issue == {"key": "X-1"}

    def test_optional_sections_nullable(self) -> None:
        payload = JiraWebhookPayload.model_validate({"webhookEvent": "ping"})
        assert payload.issue is None
        assert payload.user is None
        assert payload.changelog is None


class TestWebhookEventResponse:
    def test_round_trip(self) -> None:
        now = datetime.now(tz=UTC)
        res = WebhookEventResponse(
            id=1,
            source="hubspot",
            event_type="ticket.propertyChange",
            status="processed",
            retry_count=0,
            created_at=now,
        )
        assert res.id == 1
        assert res.source == "hubspot"
        assert res.created_at == now

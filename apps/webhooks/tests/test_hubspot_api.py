"""Tests for production and sandbox HubSpot webhook authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

from apps.webhooks.models import WebhookEvent


@pytest.mark.django_db
class TestHubSpotWebhookAPI:
    """Verify secret isolation and HubSpot signature versions."""

    production_url = "/api/v1/webhooks/hubspot/"
    sandbox_url = "/api/v1/webhooks/hubspot/sandbox/"
    production_secret = "production-secret"
    sandbox_secret = "sandbox-secret"

    def setup_method(self) -> None:
        """Create an isolated Django test client and webhook payload."""
        self.client = Client()
        self.payload = [
            {
                "appId": 45639385,
                "eventId": 1,
                "objectId": 77,
                "subscriptionType": "conversation.newMessage",
            }
        ]

    @staticmethod
    def _v1_signature(secret: str, body: bytes) -> str:
        return hashlib.sha256(secret.encode("utf-8") + body).hexdigest()

    @staticmethod
    def _v3_signature(secret: str, method: str, uri: str, body: bytes, timestamp: str) -> str:
        source = method + uri + body.decode("utf-8") + timestamp
        digest = hmac.new(secret.encode("utf-8"), source.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    @override_settings(
        HUBSPOT_APP_SECRET=production_secret,
        HUBSPOT_SANDBOX_APP_SECRET=sandbox_secret,
        DEBUG=False,
    )
    @patch("apps.webhooks.api.process_webhook_event")
    def test_each_endpoint_accepts_only_its_v1_secret(self, process_webhook_event) -> None:
        body = json.dumps(self.payload).encode("utf-8")

        production_response = self.client.post(
            self.production_url,
            data=body,
            content_type="application/json",
            headers={"X-HubSpot-Signature": self._v1_signature(self.production_secret, body)},
        )
        sandbox_response = self.client.post(
            self.sandbox_url,
            data=body,
            content_type="application/json",
            headers={"X-HubSpot-Signature": self._v1_signature(self.sandbox_secret, body)},
        )

        assert production_response.status_code == 202
        assert production_response.json()["status"] == "accepted"
        assert sandbox_response.status_code == 202
        assert sandbox_response.json()["status"] == "accepted"
        assert process_webhook_event.call_count == 2

    @override_settings(
        HUBSPOT_APP_SECRET=production_secret,
        AI_ROUTING_ENABLED=True,
        SALOMAO_V1_BASE_URL="https://salomao.local",
        HUBSPOT_AI_TRIAGE_STAGE_ID="ai-triage",
        DEBUG=False,
    )
    def test_production_triage_stage_dispatches_salomao_supervisor(self) -> None:
        payload = [
            {
                "eventId": "event-triage",
                "objectId": "ticket-triage",
                "subscriptionType": "ticket.propertyChange",
                "propertyName": "hs_pipeline_stage",
                "propertyValue": "ai-triage",
            }
        ]
        body = json.dumps(payload).encode("utf-8")

        with (
            patch("apps.ai_agents.utils.business_rules.off_hours_reason", return_value=None),
            patch("apps.ai_agents.utils.business_rules.is_quinta_fire", return_value=False),
            patch("apps.ai_agents.utils.business_rules.is_business_hours", return_value=True),
            patch("apps.ai_agents.tasks.run_supervisor_pipeline_task.delay") as supervisor_task,
        ):
            response = self.client.post(
                self.production_url,
                data=body,
                content_type="application/json",
                headers={"X-HubSpot-Signature": self._v1_signature(self.production_secret, body)},
            )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        supervisor_task.assert_called_once_with("ticket-triage", False)

    @override_settings(
        HUBSPOT_APP_SECRET=production_secret,
        HUBSPOT_SANDBOX_APP_SECRET=sandbox_secret,
        DEBUG=False,
    )
    @patch("apps.webhooks.api.process_webhook_event")
    def test_sandbox_rejects_production_secret(self, process_webhook_event) -> None:
        body = json.dumps(self.payload).encode("utf-8")

        response = self.client.post(
            self.sandbox_url,
            data=body,
            content_type="application/json",
            headers={"X-HubSpot-Signature": self._v1_signature(self.production_secret, body)},
        )

        assert response.status_code == 202
        assert response.json()["status"] == "signature_mismatch"
        assert response.json()["events_queued"] == 0
        assert WebhookEvent.objects.filter(event_type="conversation.newMessage").exists()
        process_webhook_event.assert_not_called()

    @override_settings(HUBSPOT_SANDBOX_APP_SECRET=sandbox_secret, DEBUG=False)
    @patch("apps.webhooks.api.process_webhook_event")
    def test_sandbox_accepts_current_v3_signature(self, process_webhook_event) -> None:
        body = json.dumps(self.payload).encode("utf-8")
        timestamp = str(int(time.time() * 1000))
        uri = "http://testserver/api/v1/webhooks/hubspot/sandbox/"
        signature = self._v3_signature(self.sandbox_secret, "POST", uri, body, timestamp)

        response = self.client.post(
            self.sandbox_url,
            data=body,
            content_type="application/json",
            headers={
                "X-HubSpot-Request-Timestamp": timestamp,
                "X-HubSpot-Signature-v3": signature,
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        process_webhook_event.assert_called_once()

    @override_settings(HUBSPOT_SANDBOX_APP_SECRET=sandbox_secret, DEBUG=False)
    @patch("apps.webhooks.api.process_webhook_event")
    def test_sandbox_rejects_expired_v3_signature(self, process_webhook_event) -> None:
        body = json.dumps(self.payload).encode("utf-8")
        timestamp = str(int(time.time() * 1000) - 301_000)
        uri = "http://testserver/api/v1/webhooks/hubspot/sandbox/"
        signature = self._v3_signature(self.sandbox_secret, "POST", uri, body, timestamp)

        response = self.client.post(
            self.sandbox_url,
            data=body,
            content_type="application/json",
            headers={
                "X-HubSpot-Request-Timestamp": timestamp,
                "X-HubSpot-Signature-v3": signature,
            },
        )

        assert response.status_code == 202
        assert response.json()["status"] == "signature_mismatch"
        process_webhook_event.assert_not_called()

    @override_settings(HUBSPOT_SANDBOX_APP_SECRET="", DEBUG=False)
    def test_sandbox_fails_closed_without_secret(self) -> None:
        body = json.dumps(self.payload).encode("utf-8")

        response = self.client.post(self.sandbox_url, data=body, content_type="application/json")

        assert response.status_code == 500
        assert not WebhookEvent.objects.filter(event_type="conversation.newMessage").exists()

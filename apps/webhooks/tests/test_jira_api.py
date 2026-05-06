import hashlib
import hmac
import json
from django.test import Client, override_settings
import pytest
from apps.webhooks.models import WebhookEvent

@pytest.mark.django_db
class TestJiraWebhookAPI:
    def setup_method(self):
        self.client = Client()
        self.url = "/api/v1/webhooks/jira/"
        self.secret = "test-jira-secret"
        self.payload = {"webhookEvent": "jira:issue_created", "issue": {"key": "TEST-1"}}

    def _generate_signature(self, body: bytes) -> str:
        return "sha256=" + hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    @override_settings(JIRA_WEBHOOK_SECRET="test-jira-secret")
    def test_jira_webhook_valid_signature(self):
        body = json.dumps(self.payload).encode("utf-8")
        signature = self._generate_signature(body)
        
        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            headers={"x-hub-signature": signature}
        )
        
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        assert WebhookEvent.objects.filter(source="jira", event_type="jira:issue_created").exists()

    @override_settings(JIRA_WEBHOOK_SECRET="test-jira-secret")
    def test_jira_webhook_missing_signature(self):
        body = json.dumps(self.payload).encode("utf-8")
        
        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json"
        )
        
        assert response.status_code == 401
        assert not WebhookEvent.objects.filter(source="jira").exists()

    @override_settings(JIRA_WEBHOOK_SECRET="test-jira-secret")
    def test_jira_webhook_invalid_signature(self):
        body = json.dumps(self.payload).encode("utf-8")
        
        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json",
            headers={"x-hub-signature": "sha256=invalidhash"}
        )
        
        assert response.status_code == 401
        assert not WebhookEvent.objects.filter(source="jira").exists()

    @override_settings(JIRA_WEBHOOK_SECRET="", DEBUG=False)
    def test_jira_webhook_missing_secret_in_prod(self):
        body = json.dumps(self.payload).encode("utf-8")
        
        response = self.client.post(
            self.url,
            data=body,
            content_type="application/json"
        )
        
        assert response.status_code == 500
        assert not WebhookEvent.objects.filter(source="jira").exists()

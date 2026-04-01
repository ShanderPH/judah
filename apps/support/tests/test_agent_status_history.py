"""Tests for AgentStatusHistory creation and is_active=None agent inclusion.

Covers:
- Webhook handler creates AgentStatusHistory on status change
- Polling task creates AgentStatusHistory on status change
- updated_at is saved when status changes
- Agents with is_active=None are included (not excluded like is_active=False)
- Agents with is_active=False are excluded
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.support.models import Agent, AgentStatusHistory
from apps.support.tasks import task_poll_hubspot_agent_status
from apps.webhooks.handlers.hubspot_handler import _handle_agent_availability_change


def _make_agent(
    name: str,
    email: str,
    owner_id: int,
    status: str = "online",
    is_active: bool | None = True,
) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=email,
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Webhook handler — AgentStatusHistory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWebhookHandlerStatusHistory:
    def test_creates_status_history_on_change(self) -> None:
        agent = _make_agent("Diego", "diego@test.com", 10, status="away")

        _handle_agent_availability_change(
            hubspot_contact_id="10",
            availability_value="available",
            payload={"email": "diego@test.com"},
        )

        history = AgentStatusHistory.objects.filter(agent=agent)
        assert history.count() == 1
        record = history.first()
        assert record.old_status == "away"
        assert record.new_status == "online"
        assert record.sync_source == "hubspot_webhook"

    def test_no_history_when_status_unchanged(self) -> None:
        agent = _make_agent("Ester", "ester@test.com", 11, status="online")

        _handle_agent_availability_change(
            hubspot_contact_id="11",
            availability_value="available",
            payload={"email": "ester@test.com"},
        )

        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    def test_updates_updated_at_on_status_change(self) -> None:
        from django.utils.timezone import make_aware

        agent = _make_agent("Fred", "fred@test.com", 12, status="away")
        before = timezone.now()

        _handle_agent_availability_change(
            hubspot_contact_id="12",
            availability_value="available",
            payload={"email": "fred@test.com"},
        )

        agent.refresh_from_db()
        assert agent.updated_at is not None
        updated = agent.updated_at
        if updated.tzinfo is None:
            updated = make_aware(updated)
        assert updated >= before

    def test_includes_agent_with_is_active_null(self) -> None:
        agent = _make_agent("Gina", "gina@test.com", 13, status="away", is_active=None)

        _handle_agent_availability_change(
            hubspot_contact_id="13",
            availability_value="available",
            payload={"email": "gina@test.com"},
        )

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 1

    def test_excludes_agent_with_is_active_false(self) -> None:
        agent = _make_agent("Hugo", "hugo@test.com", 14, status="away", is_active=False)

        _handle_agent_availability_change(
            hubspot_contact_id="14",
            availability_value="available",
            payload={"email": "hugo@test.com"},
        )

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    def test_sets_away_creates_history(self) -> None:
        agent = _make_agent("Iris", "iris@test.com", 15, status="online")

        _handle_agent_availability_change(
            hubspot_contact_id="15",
            availability_value="away",
            payload={"email": "iris@test.com"},
        )

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        history = AgentStatusHistory.objects.filter(agent=agent).order_by("-changed_at").first()
        assert history is not None
        assert history.old_status == "online"
        assert history.new_status == "away"
        assert history.sync_source == "hubspot_webhook"


# ---------------------------------------------------------------------------
# Polling task — AgentStatusHistory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPollTaskStatusHistory:
    def _mock_users(self, email: str, status_enum: str) -> list[dict]:
        return [
            {
                "user_id": "u-test",
                "email": email,
                "availability_status": "available" if status_enum == "online" else "away",
                "status_enum": status_enum,
            }
        ]

    def test_creates_status_history_on_poll_change(self) -> None:
        agent = _make_agent("Jana", "jana@test.com", 20, status="away")

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("jana@test.com", "online")
            task_poll_hubspot_agent_status()

        history = AgentStatusHistory.objects.filter(agent=agent)
        assert history.count() == 1
        record = history.first()
        assert record.old_status == "away"
        assert record.new_status == "online"
        assert record.sync_source == "hubspot_poll"

    def test_no_history_when_poll_status_unchanged(self) -> None:
        agent = _make_agent("Karl", "karl@test.com", 21, status="online")

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("karl@test.com", "online")
            task_poll_hubspot_agent_status()

        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    def test_poll_includes_agent_with_is_active_null(self) -> None:
        agent = _make_agent("Lena", "lena@test.com", 22, status="away", is_active=None)

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("lena@test.com", "online")
            result = task_poll_hubspot_agent_status()

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert result["updated"] == 1
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 1

    def test_poll_excludes_agent_with_is_active_false(self) -> None:
        agent = _make_agent("Mario", "mario@test.com", 23, status="away", is_active=False)

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("mario@test.com", "online")
            result = task_poll_hubspot_agent_status()

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert result["not_found"] == 1
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    def test_poll_saves_updated_at_on_change(self) -> None:
        from django.utils.timezone import make_aware

        agent = _make_agent("Nina", "nina@test.com", 24, status="away")
        before = timezone.now()

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("nina@test.com", "online")
            task_poll_hubspot_agent_status()

        agent.refresh_from_db()
        assert agent.updated_at is not None
        updated = agent.updated_at
        if updated.tzinfo is None:
            updated = make_aware(updated)
        assert updated >= before

"""Tests for agent availability sync — polling task and webhook handler."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.support.models import Agent
from apps.support.tasks import task_poll_hubspot_agent_status
from apps.webhooks.handlers.hubspot_handler import _handle_agent_availability_change


def _make_agent(name: str, email: str, owner_id: int, status: str = "online") -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=email,
        hubspot_owner_id=owner_id,
        status_enum=status,
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=True,
    )


@pytest.mark.django_db
class TestTaskPollHubspotAgentStatus:
    def test_sets_agent_online_when_available(self) -> None:
        agent = _make_agent("Ana", "ana@test.com", 1, status="away")

        mock_users = [
            {"user_id": "u1", "email": "ana@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_poll_hubspot_agent_status()

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert result["updated"] == 1
        assert result["skipped"] == 0

    def test_sets_agent_away_when_away(self) -> None:
        agent = _make_agent("Bruno", "bruno@test.com", 2, status="online")

        mock_users = [
            {"user_id": "u2", "email": "bruno@test.com", "availability_status": "away", "status_enum": "away"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_poll_hubspot_agent_status()

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert result["updated"] == 1

    def test_skips_when_status_unchanged(self) -> None:
        _make_agent("Carla", "carla@test.com", 3, status="online")

        mock_users = [
            {"user_id": "u3", "email": "carla@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_poll_hubspot_agent_status()

        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_not_found_counted_for_unknown_emails(self) -> None:
        mock_users = [
            {"user_id": "u9", "email": "unknown@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_poll_hubspot_agent_status()

        assert result["not_found"] == 1
        assert result["updated"] == 0

    def test_skips_users_without_email(self) -> None:
        mock_users = [{"user_id": "u10", "email": "", "availability_status": "available", "status_enum": "online"}]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_poll_hubspot_agent_status()

        assert result["skipped"] == 1
        assert result["updated"] == 0


@pytest.mark.django_db
class TestHandleAgentAvailabilityChange:
    def test_sets_online_for_available(self) -> None:
        agent = _make_agent("Diego", "diego@test.com", 4, status="away")

        _handle_agent_availability_change(
            hubspot_contact_id="4",
            availability_value="available",
            payload={"email": "diego@test.com"},
        )

        agent.refresh_from_db()
        assert agent.status_enum == "online"

    def test_sets_away_for_away(self) -> None:
        agent = _make_agent("Ester", "ester@test.com", 5, status="online")

        _handle_agent_availability_change(
            hubspot_contact_id="5",
            availability_value="away",
            payload={"email": "ester@test.com"},
        )

        agent.refresh_from_db()
        assert agent.status_enum == "away"

    def test_no_op_when_email_missing_and_lookup_fails(self) -> None:
        agent = _make_agent("Fred", "fred@test.com", 6, status="online")

        with patch(
            "apps.integrations.hubspot.client.get_hubspot_client",
            side_effect=Exception("API error"),
        ):
            _handle_agent_availability_change(
                hubspot_contact_id="6",
                availability_value="away",
                payload={},
            )

        agent.refresh_from_db()
        assert agent.status_enum == "online"

    def test_no_op_for_unknown_agent(self) -> None:
        _handle_agent_availability_change(
            hubspot_contact_id="999",
            availability_value="available",
            payload={"email": "nobody@test.com"},
        )

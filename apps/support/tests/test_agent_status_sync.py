"""Tests for agent availability sync — SAT heartbeat and webhook handler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.support.models import Agent
from apps.support.tasks import task_sat_heartbeat


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
class TestSATHeartbeatAgentStatus:
    """Tests for the SAT heartbeat task (replaces task_poll_hubspot_agent_status)."""

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_sets_agent_online_when_available(self, mock_bh) -> None:
        agent = _make_agent("Ana", "ana@test.com", 1, status="away")

        mock_users = [
            {"user_id": "u1", "email": "ana@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            with patch("apps.support.tasks.task_matchmaker_drain_queue"):
                result = task_sat_heartbeat()

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert result["status_changes"] == 1

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_sets_agent_away_when_away(self, mock_bh) -> None:
        agent = _make_agent("Bruno", "bruno@test.com", 2, status="online")

        mock_users = [
            {"user_id": "u2", "email": "bruno@test.com", "availability_status": "away", "status_enum": "away"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_sat_heartbeat()

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert result["status_changes"] == 1

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_skips_when_status_unchanged(self, mock_bh) -> None:
        _make_agent("Carla", "carla@test.com", 3, status="online")

        mock_users = [
            {"user_id": "u3", "email": "carla@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_sat_heartbeat()

        assert result["status_changes"] == 0

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_unknown_email_not_tracked(self, mock_bh) -> None:
        mock_users = [
            {"user_id": "u9", "email": "unknown@test.com", "availability_status": "available", "status_enum": "online"}
        ]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_sat_heartbeat()

        assert result["status_changes"] == 0

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_skips_users_without_email(self, mock_bh) -> None:
        mock_users = [{"user_id": "u10", "email": "", "availability_status": "available", "status_enum": "online"}]
        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client_fn.return_value.get_all_owners_availability.return_value = mock_users
            result = task_sat_heartbeat()

        assert result["status_changes"] == 0


@pytest.mark.django_db
class TestHandleAgentAvailabilityChange:
    """Tests for webhook-triggered availability changes (now async via Celery)."""

    def test_dispatches_task_for_available(self) -> None:
        from apps.webhooks.handlers.hubspot_handler import _handle_agent_availability_change

        with patch("apps.support.tasks.task_handle_availability_change.delay") as mock_delay:
            _handle_agent_availability_change(
                hubspot_contact_id="4",
                availability_value="available",
                payload={"email": "diego@test.com"},
            )

        mock_delay.assert_called_once_with("4", "available", {"email": "diego@test.com"})

    def test_dispatches_task_for_away(self) -> None:
        from apps.webhooks.handlers.hubspot_handler import _handle_agent_availability_change

        with patch("apps.support.tasks.task_handle_availability_change.delay") as mock_delay:
            _handle_agent_availability_change(
                hubspot_contact_id="5",
                availability_value="away",
                payload={"email": "ester@test.com"},
            )

        mock_delay.assert_called_once_with("5", "away", {"email": "ester@test.com"})

    def test_dispatches_even_without_email_in_payload(self) -> None:
        from apps.webhooks.handlers.hubspot_handler import _handle_agent_availability_change

        with patch("apps.support.tasks.task_handle_availability_change.delay") as mock_delay:
            _handle_agent_availability_change(
                hubspot_contact_id="6",
                availability_value="away",
                payload={},
            )

        mock_delay.assert_called_once_with("6", "away", {})

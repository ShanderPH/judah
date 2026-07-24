"""Tests for SAT availability sync and ticket-triggered reconciliation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.support.models import Agent
from apps.support.tasks import task_matchmaker_assign_single, task_sat_heartbeat


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
class TestTicketWebhookAvailabilityReconciliation:
    """A real ticket webhook must refresh Users API state before assignment."""

    @patch("apps.support.sat_service.sat_heartbeat")
    @patch("apps.support.matchmaker_service.matchmaker_assign_next")
    @patch("apps.support.matchmaker_service.enqueue_new_ticket")
    def test_forces_uncached_users_read_before_assignment(
        self,
        mock_enqueue,
        mock_assign,
        mock_reconcile,
    ) -> None:
        mock_enqueue.return_value = object()
        mock_reconcile.return_value = {
            "agents_checked": 1,
            "status_changes": 1,
            "agents_came_online": 0,
        }
        mock_assign.return_value.value = "assigned"

        assert task_matchmaker_assign_single("T001") is True

        mock_reconcile.assert_called_once()
        assert mock_reconcile.call_args.kwargs["force_refresh"] is True
        mock_assign.assert_called_once_with("T001")

    @patch("apps.support.sat_service.sat_heartbeat")
    @patch("apps.support.matchmaker_service.matchmaker_assign_next")
    @patch("apps.support.matchmaker_service.enqueue_new_ticket")
    def test_users_api_failure_keeps_ticket_queued(
        self,
        mock_enqueue,
        mock_assign,
        mock_reconcile,
    ) -> None:
        mock_enqueue.return_value = object()
        mock_reconcile.return_value = {"error": "HubSpot unavailable"}

        assert task_matchmaker_assign_single("T002") is False

        mock_assign.assert_not_called()

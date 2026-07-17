"""Tests for agent_sync_service — business hours logic and optimized sync."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.support.agent_sync_service import (
    _DEFAULT_BUSINESS_HOURS,
    get_poll_interval_seconds,
    is_business_hours,
    sync_all_agents_status_and_counts_optimized,
)
from apps.support.models import Agent, AgentStatusHistory


class TestBusinessHoursLogic:
    """Test business hours detection and interval calculation."""

    @pytest.mark.parametrize(
        "weekday,hour,expected",
        [
            # Monday-Friday (0-4): 9h-18h is business hours
            (0, 8, False),  # Monday 8h - before hours
            (0, 9, True),  # Monday 9h - start of hours
            (0, 12, True),  # Monday 12h - during hours
            (0, 17, True),  # Monday 17h - during hours
            (0, 18, False),  # Monday 18h - end of hours
            (1, 9, True),  # Tuesday 9h
            (4, 17, True),  # Friday 17h
            # Saturday (5): 9h-13h
            (5, 8, False),  # Saturday 8h - before hours
            (5, 9, True),  # Saturday 9h - start
            (5, 12, True),  # Saturday 12h - during
            (5, 13, False),  # Saturday 13h - end
            (5, 14, False),  # Saturday 14h - after
            # Sunday (6): 8h-12h
            (6, 7, False),  # Sunday 7h - before
            (6, 8, True),  # Sunday 8h - start
            (6, 11, True),  # Sunday 11h - during
            (6, 12, False),  # Sunday 12h - end
        ],
    )
    def test_is_business_hours(self, weekday: int, hour: int, expected: bool) -> None:
        """Test business hours detection for various days and times."""
        # Create a datetime with the specified weekday and hour
        # January 2024: 1=Monday, 6=Saturday, 7=Sunday
        base_date = datetime(2024, 1, 1, hour, 0, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        # Adjust to the target weekday
        days_diff = weekday - base_date.weekday()
        target_date = base_date + timezone.timedelta(days=days_diff)

        with patch.object(timezone, "localtime", return_value=target_date):
            result = is_business_hours()
            assert result == expected

    def test_business_hours_config(self) -> None:
        """Verify _DEFAULT_BUSINESS_HOURS configuration is correct."""
        # Monday-Friday: 9-18
        for day in range(5):
            assert _DEFAULT_BUSINESS_HOURS[day] == (9, 18), f"Day {day} should be 9-18"

        # Saturday: 9-13
        assert _DEFAULT_BUSINESS_HOURS[5] == (9, 13)

        # Sunday: 8-12
        assert _DEFAULT_BUSINESS_HOURS[6] == (8, 12)

    def test_get_poll_interval_seconds_business_hours(self) -> None:
        """Test that interval is 30s during business hours."""
        with patch("apps.support.agent_sync_service.is_business_hours", return_value=True):
            assert get_poll_interval_seconds() == 30

    def test_get_poll_interval_seconds_outside_hours(self) -> None:
        """Test that interval is 3600s (1h) outside business hours."""
        with patch("apps.support.agent_sync_service.is_business_hours", return_value=False):
            assert get_poll_interval_seconds() == 3600


@pytest.mark.django_db
class TestSyncAllAgentsStatusAndCountsOptimized:
    """Test the optimized agent sync with status and conversation counts."""

    def _make_agent(
        self,
        name: str,
        email: str,
        owner_id: int,
        status: str = "online",
        current_chats: int = 0,
    ) -> Agent:
        return Agent.objects.create(
            name=name,
            agent_email=email,
            hubspot_owner_id=owner_id,
            status_enum=status,
            current_simultaneous_chats=current_chats,
            max_simultaneous_chats=5,
            auto_assign_enabled=True,
            is_active=True,
        )

    @override_settings(AGENT_STATUS_SYNC_ENABLED=False)
    def test_disabled_status_sync_preserves_status_and_reconciles_count(self) -> None:
        agent = self._make_agent(
            "Test Agent",
            "test@example.com",
            123,
            status="away",
            current_chats=0,
        )

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.count_active_tickets_by_owner.return_value = 3
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert agent.current_simultaneous_chats == 3
        assert result["status_changes"] == 0
        assert result["count_corrections"] == 1
        assert result["api_calls_made"] == 1
        mock_client.get_all_owners_availability.assert_not_called()

    def test_sync_updates_status_when_changed(self) -> None:
        """Test that agent status is updated when it changes."""
        agent = self._make_agent("Test Agent", "test@example.com", 123, status="away")

        mock_users = [
            {
                "user_id": "123",
                "email": "test@example.com",
                "availability_status": "available",
                "status_enum": "online",
            }
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client.count_active_tickets_by_owner.return_value = 2
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert result["status_changes"] == 1
        assert result["agents_synced"] == 1

    def test_sync_skips_status_when_unchanged(self) -> None:
        """Test that sync is skipped when status hasn't changed."""
        self._make_agent("Test Agent", "test@example.com", 123, status="online")

        mock_users = [
            {
                "user_id": "123",
                "email": "test@example.com",
                "availability_status": "available",
                "status_enum": "online",
            }
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client.count_active_tickets_by_owner.return_value = 2
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        assert result["status_changes"] == 0
        assert result["agents_synced"] == 1

    def test_sync_corrects_conversation_count(self) -> None:
        """Test that conversation count is corrected when divergent."""
        agent = self._make_agent("Test Agent", "test@example.com", 123, status="online", current_chats=0)

        mock_users = [
            {
                "user_id": "123",
                "email": "test@example.com",
                "availability_status": "available",
                "status_enum": "online",
            }
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client.count_active_tickets_by_owner.return_value = 3
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        agent.refresh_from_db()
        assert agent.current_simultaneous_chats == 3
        assert result["count_corrections"] == 1

    def test_sync_handles_api_error_gracefully(self) -> None:
        """Test that sync continues even if API calls fail."""
        self._make_agent("Test Agent", "test@example.com", 123, status="online")

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.side_effect = Exception("API Error")
            # Return -1 to indicate error for count
            mock_client.count_active_tickets_by_owner.return_value = -1
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        # Should complete without exception but with 0 changes
        assert result["agents_synced"] == 1
        assert result["status_changes"] == 0
        assert result["count_corrections"] == 0

    def test_sync_skips_inactive_agents(self) -> None:
        """Test that inactive agents are not synced."""
        Agent.objects.create(
            name="Inactive Agent",
            agent_email="inactive@example.com",
            hubspot_owner_id=456,
            status_enum="online",
            current_simultaneous_chats=0,
            max_simultaneous_chats=5,
            auto_assign_enabled=True,
            is_active=False,  # Inactive
        )

        mock_users = []

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        assert result["agents_synced"] == 0

    def test_sync_handles_multiple_agents(self) -> None:
        """Test sync with multiple agents and mixed changes."""
        agent1 = self._make_agent("Agent 1", "agent1@example.com", 111, status="away", current_chats=1)
        agent2 = self._make_agent("Agent 2", "agent2@example.com", 222, status="online", current_chats=2)

        mock_users = [
            {
                "user_id": "111",
                "email": "agent1@example.com",
                "availability_status": "available",
                "status_enum": "online",
            },
            {
                "user_id": "222",
                "email": "agent2@example.com",
                "availability_status": "available",
                "status_enum": "online",
            },
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users

            # Agent 1 count changes, Agent 2 stays same
            def mock_count(owner_id: int) -> int:
                return {111: 2, 222: 2}.get(owner_id, 0)

            mock_client.count_active_tickets_by_owner.side_effect = mock_count
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        agent1.refresh_from_db()
        agent2.refresh_from_db()

        assert agent1.status_enum == "online"  # Changed
        assert agent2.status_enum == "online"  # Unchanged
        assert agent1.current_simultaneous_chats == 2  # Corrected
        assert agent2.current_simultaneous_chats == 2  # Unchanged
        assert result["agents_synced"] == 2
        assert result["status_changes"] == 1
        assert result["count_corrections"] == 1

    def test_sync_creates_status_history(self) -> None:
        """Test that status changes are logged in AgentStatusHistory."""
        agent = self._make_agent("Test Agent", "test@example.com", 123, status="away")

        mock_users = [
            {
                "user_id": "123",
                "email": "test@example.com",
                "availability_status": "available",
                "status_enum": "online",
            }
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client.count_active_tickets_by_owner.return_value = 0
            mock_client_fn.return_value = mock_client

            sync_all_agents_status_and_counts_optimized()

        history = AgentStatusHistory.objects.filter(agent=agent).first()
        assert history is not None
        assert history.old_status == "away"
        assert history.new_status == "online"
        assert history.sync_source == "hubspot_poll_optimized"

    def test_sync_handles_email_not_in_availability_map(self) -> None:
        """Test that agents with email not in HubSpot availability map are still synced for counts."""
        # Create an agent with valid owner_id but email won't be in HubSpot response
        agent = self._make_agent("Unknown Email", "unknown@example.com", 999, status="online")

        mock_users = [
            {
                "user_id": "123",
                "email": "other@example.com",  # Different email
                "availability_status": "available",
                "status_enum": "online",
            }
        ]

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_all_owners_availability.return_value = mock_users
            mock_client.count_active_tickets_by_owner.return_value = 5
            mock_client_fn.return_value = mock_client

            result = sync_all_agents_status_and_counts_optimized()

        agent.refresh_from_db()
        # Email not found, so status not updated
        # But count is still updated
        assert agent.status_enum == "online"  # Unchanged
        assert agent.current_simultaneous_chats == 5  # Updated
        assert result["agents_synced"] == 1

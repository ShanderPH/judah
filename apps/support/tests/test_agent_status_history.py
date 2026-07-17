"""Tests for AgentStatusHistory creation via SAT heartbeat.

Covers:
- SAT heartbeat creates AgentStatusHistory on status change
- updated_at is saved when status changes
- Agents with is_active=None are included (not excluded like is_active=False)
- Agents with is_active=False are excluded
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.support.models import Agent, AgentStatusHistory
from apps.support.tasks import task_sat_heartbeat


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
# Webhook handler — now dispatches async, verify task dispatch
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SAT heartbeat — AgentStatusHistory
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSATHeartbeatStatusHistory:
    def _mock_users(self, email: str, status_enum: str) -> list[dict]:
        return [
            {
                "user_id": "u-test",
                "email": email,
                "availability_status": "available" if status_enum == "online" else "away",
                "status_enum": status_enum,
            }
        ]

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_creates_status_history_on_change(self, mock_bh) -> None:
        agent = _make_agent("Jana", "jana@test.com", 20, status="away")

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("jana@test.com", "online")
            with patch("apps.support.tasks.task_matchmaker_drain_queue"):
                task_sat_heartbeat()

        history = AgentStatusHistory.objects.filter(agent=agent)
        assert history.count() == 1
        record = history.first()
        assert record.old_status == "away"
        assert record.new_status == "online"
        assert record.sync_source == "sat_heartbeat"

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_no_history_when_status_unchanged(self, mock_bh) -> None:
        agent = _make_agent("Karl", "karl@test.com", 21, status="online")

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("karl@test.com", "online")
            task_sat_heartbeat()

        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_includes_agent_with_is_active_null(self, mock_bh) -> None:
        agent = _make_agent("Lena", "lena@test.com", 22, status="away", is_active=None)

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("lena@test.com", "online")
            with patch("apps.support.tasks.task_matchmaker_drain_queue"):
                result = task_sat_heartbeat()

        agent.refresh_from_db()
        assert agent.status_enum == "online"
        assert result["status_changes"] == 1
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 1

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_excludes_agent_with_is_active_false(self, mock_bh) -> None:
        agent = _make_agent("Mario", "mario@test.com", 23, status="away", is_active=False)

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("mario@test.com", "online")
            result = task_sat_heartbeat()

        agent.refresh_from_db()
        assert agent.status_enum == "away"
        assert result["status_changes"] == 0
        assert AgentStatusHistory.objects.filter(agent=agent).count() == 0

    @patch("apps.support.sat_service.is_business_hours", return_value=True)
    def test_saves_updated_at_on_change(self, mock_bh) -> None:
        from django.utils.timezone import make_aware

        agent = _make_agent("Nina", "nina@test.com", 24, status="away")
        before = timezone.now()

        with patch("apps.integrations.hubspot.client.get_hubspot_client") as mock_fn:
            mock_fn.return_value.get_all_owners_availability.return_value = self._mock_users("nina@test.com", "online")
            with patch("apps.support.tasks.task_matchmaker_drain_queue"):
                task_sat_heartbeat()

        agent.refresh_from_db()
        assert agent.updated_at is not None
        updated = agent.updated_at
        if updated.tzinfo is None:
            updated = make_aware(updated)
        assert updated >= before

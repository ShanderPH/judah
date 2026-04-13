"""Regression tests for the assignment_type constraint fix.

Covers:
- AssignmentLog creation with 'automatic' (must not raise)
- AssignmentLog default value is 'automatic'
- get_last_assigned_owner_id filters by 'automatic' (not legacy 'auto')
- _parse_hubspot_timestamp handles invalid inputs (Python 3 except syntax)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.utils import timezone

from apps.support.auto_assign_service import _parse_hubspot_timestamp
from apps.support.models import Agent, AssignmentLog
from apps.support.queue_service import get_last_assigned_owner_id


def _make_agent(name: str, owner_id: int) -> Agent:
    return Agent.objects.create(
        name=name,
        agent_email=f"{name.lower()}@test.com",
        hubspot_owner_id=owner_id,
        status_enum="online",
        current_simultaneous_chats=0,
        max_simultaneous_chats=5,
        auto_assign_enabled=True,
        is_active=True,
    )


@pytest.mark.django_db
class TestAssignmentLogConstraint:
    def test_creates_with_automatic_type(self) -> None:
        agent = _make_agent("Ana", 1)
        log = AssignmentLog.objects.create(
            ticket_id="T-CONSTRAINT-01",
            agent=agent,
            agent_name=agent.name,
            hubspot_owner_id=agent.hubspot_owner_id,
            assignment_type="automatic",
        )
        assert log.pk is not None
        assert log.assignment_type == "automatic"

    def test_creates_with_manual_type(self) -> None:
        agent = _make_agent("Bruno", 2)
        log = AssignmentLog.objects.create(
            ticket_id="T-CONSTRAINT-02",
            agent=agent,
            agent_name=agent.name,
            hubspot_owner_id=agent.hubspot_owner_id,
            assignment_type="manual",
        )
        assert log.assignment_type == "manual"

    def test_default_assignment_type_is_automatic(self) -> None:
        agent = _make_agent("Carla", 3)
        log = AssignmentLog.objects.create(
            ticket_id="T-CONSTRAINT-03",
            agent=agent,
            agent_name=agent.name,
            hubspot_owner_id=agent.hubspot_owner_id,
        )
        assert log.assignment_type == "automatic"

    def test_get_last_assigned_filters_by_automatic(self) -> None:
        AssignmentLog.objects.create(
            ticket_id="T-FILTER-01",
            agent_name="Agent X",
            hubspot_owner_id=999,
            assignment_type="automatic",
            assigned_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        )
        AssignmentLog.objects.create(
            ticket_id="T-FILTER-02",
            agent_name="Agent Y",
            hubspot_owner_id=888,
            assignment_type="manual",
            assigned_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )
        result = get_last_assigned_owner_id()
        assert result == 999

    def test_get_last_assigned_returns_none_with_only_manual(self) -> None:
        AssignmentLog.objects.create(
            ticket_id="T-FILTER-03",
            agent_name="Manual Agent",
            hubspot_owner_id=777,
            assignment_type="manual",
            assigned_at=timezone.now(),
        )
        assert get_last_assigned_owner_id() is None


class TestParseHubspotTimestamp:
    def test_parses_valid_millisecond_epoch(self) -> None:
        ms = 1743530280000
        result = _parse_hubspot_timestamp(ms)
        assert result is not None
        assert result.tzinfo is not None

    def test_parses_string_millisecond_epoch(self) -> None:
        result = _parse_hubspot_timestamp("1743530280000")
        assert result is not None

    def test_returns_none_for_none(self) -> None:
        assert _parse_hubspot_timestamp(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_hubspot_timestamp("") is None

    def test_returns_none_for_non_numeric_string(self) -> None:
        assert _parse_hubspot_timestamp("not-a-timestamp") is None

    def test_returns_none_for_out_of_range_timestamp(self) -> None:
        assert _parse_hubspot_timestamp(999_999_999_999_999_999) is None

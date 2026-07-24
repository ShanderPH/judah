"""Gate A tests for the read-only legacy cycle profiling command (DB-01).

Runs only against the isolated local test database (SQLite lane via
``run_tests_local.py`` or disposable ``judah_test`` PostgreSQL). The command
must never write, repair, or reconcile anything.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.support.legacy_cycle_profile import collect_legacy_cycle_profile
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ClosedConversation,
    NewConversation,
)

pytestmark = pytest.mark.django_db

TICKET_A = "7001"
TICKET_B = "7002"
TICKET_C = "7003"
TICKET_D = "7004"


def _agent(owner_id: int = 7101) -> Agent:
    return Agent.objects.create(
        name=f"Agent {owner_id}",
        agent_email=f"agent-{owner_id}@example.test",
        hubspot_owner_id=owner_id,
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
    )


def _queue_row(ticket_id: str, entered_at=None) -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        entered_queue_at=entered_at or (timezone.now() - timedelta(minutes=5)),
        automatic_assignment_eligible=True,
    )


def _assigned_row(ticket_id: str, agent: Agent, entered_at=None) -> AssignedConversation:
    return AssignedConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        agent=agent,
        hubspot_owner_id=agent.hubspot_owner_id,
        agent_name=agent.name,
        assigned_at=timezone.now() - timedelta(minutes=3),
        entered_queue_at=entered_at,
    )


def _closed_row(ticket_id: str, agent: Agent | None = None, entered_at=None, assigned_at=None) -> ClosedConversation:
    return ClosedConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        agent=agent,
        hubspot_owner_id=agent.hubspot_owner_id if agent else None,
        agent_name=agent.name if agent else None,
        closed_at=timezone.now(),
        entered_queue_at=entered_at,
        assigned_at=assigned_at,
    )


def _attempt(
    ticket_id: str,
    agent: Agent,
    state: str,
    queue_row: NewConversation | None = None,
    reserved_at=None,
) -> AssignmentAttempt:
    return AssignmentAttempt.objects.create(
        idempotency_key=uuid.uuid4(),
        ticket_id=ticket_id,
        queue_row=queue_row,
        selected_agent=agent,
        eligibility_revision=1,
        desired_hubspot_owner_id=agent.hubspot_owner_id,
        decision_reason="eligible",
        state=state,
        reserved_at=reserved_at or (timezone.now() - timedelta(minutes=2)),
    )


def _log(ticket_id: str, agent: Agent, attempt: AssignmentAttempt | None = None) -> AssignmentLog:
    return AssignmentLog.objects.create(
        assignment_attempt=attempt,
        ticket_id=ticket_id,
        agent=agent,
        agent_name=agent.name,
        hubspot_owner_id=agent.hubspot_owner_id,
    )


def _table_sizes() -> dict[str, int]:
    return {
        "queue": NewConversation.objects.count(),
        "assigned": AssignedConversation.objects.count(),
        "closed": ClosedConversation.objects.count(),
        "attempts": AssignmentAttempt.objects.count(),
        "logs": AssignmentLog.objects.count(),
    }


class TestCollectLegacyCycleProfile:
    def test_empty_database_returns_zero_counts(self) -> None:
        profile = collect_legacy_cycle_profile()
        assert profile
        assert all(count == 0 for count in profile.values())

    def test_overlapping_tables_and_incident_signature(self) -> None:
        agent = _agent()
        entered = timezone.now() - timedelta(minutes=10)
        # TICKET_A: everywhere — the incident shape (completed attempt + active rows).
        _queue_row(TICKET_A, entered_at=entered)
        _assigned_row(TICKET_A, agent, entered_at=entered)
        _closed_row(TICKET_A, agent, entered_at=entered, assigned_at=entered)
        _log(TICKET_A, agent, _attempt(TICKET_A, agent, AssignmentAttempt.State.COMPLETED))
        # TICKET_B: multiple attempts, one live (external_applied).
        queue_b = _queue_row(TICKET_B)
        _attempt(TICKET_B, agent, AssignmentAttempt.State.EXTERNAL_APPLIED, queue_row=queue_b)
        _attempt(TICKET_B, agent, AssignmentAttempt.State.COMPENSATED)
        # TICKET_C: closed without provenance timestamps.
        _closed_row(TICKET_C)
        # TICKET_D: repair_required live attempt.
        _attempt(TICKET_D, agent, AssignmentAttempt.State.REPAIR_REQUIRED)

        profile = collect_legacy_cycle_profile()

        assert profile["total_queue_rows"] == 2
        assert profile["total_assigned_rows"] == 1
        assert profile["total_closed_rows"] == 2
        assert profile["total_attempts"] == 4
        assert profile["total_logs"] == 1
        assert profile["tickets_in_queue_and_assigned"] == 1
        assert profile["tickets_in_queue_and_closed"] == 1
        assert profile["tickets_in_assigned_and_closed"] == 1
        assert profile["tickets_in_all_three_tables"] == 1
        assert profile["tickets_with_completed_attempt_and_queue_row"] == 1
        assert profile["tickets_with_completed_attempt_and_assigned_row"] == 1
        assert profile["tickets_with_multiple_attempts"] == 1  # TICKET_B
        assert profile["tickets_with_multiple_logs"] == 0
        assert profile["tickets_with_multiple_live_attempts"] == 0
        assert profile["live_attempts"] == 2  # TICKET_B external_applied + TICKET_D repair
        assert profile["external_applied_attempts"] == 1
        assert profile["repair_required_attempts"] == 1
        assert profile["completed_attempts"] == 1
        assert profile["attempts_reserved_before_queue_entry"] == 0
        assert profile["assigned_rows_without_entered_queue_at"] == 0
        assert profile["closed_rows_without_entered_queue_at"] == 1  # TICKET_C
        assert profile["closed_rows_without_assigned_at"] == 1  # TICKET_C
        assert profile["completed_attempts_without_log"] == 0
        assert profile["logs_without_attempt"] == 0

    def test_timestamp_correlation_and_provenance_gaps(self) -> None:
        agent = _agent()
        entered = timezone.now() - timedelta(minutes=10)
        queue_row = _queue_row(TICKET_A, entered_at=entered)
        _attempt(
            TICKET_A,
            agent,
            AssignmentAttempt.State.RETRYABLE,
            queue_row=queue_row,
            reserved_at=entered - timedelta(minutes=1),  # reserved before queue entry
        )
        _closed_row(
            TICKET_B,
            agent,
            entered_at=entered,
            assigned_at=timezone.now() + timedelta(minutes=1),  # closed before assigned
        )
        _log(TICKET_B, agent)  # orphan log without attempt
        _attempt(TICKET_C, agent, AssignmentAttempt.State.COMPLETED)  # completed without log

        profile = collect_legacy_cycle_profile()

        assert profile["attempts_reserved_before_queue_entry"] == 1
        assert profile["closed_before_assigned"] == 1
        assert profile["logs_without_attempt"] == 1
        assert profile["completed_attempts_without_log"] == 1

    def test_output_is_deterministic(self) -> None:
        agent = _agent()
        _queue_row(TICKET_A)
        _assigned_row(TICKET_A, agent)
        first = collect_legacy_cycle_profile()
        second = collect_legacy_cycle_profile()
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


class TestProfileLegacyCyclesCommand:
    def test_command_outputs_sorted_json(self) -> None:
        agent = _agent()
        _queue_row(TICKET_A)
        _assigned_row(TICKET_B, agent)
        out = StringIO()
        call_command("profile_legacy_cycles", stdout=out)
        profile = json.loads(out.getvalue())
        assert profile["total_queue_rows"] == 1
        assert profile["total_assigned_rows"] == 1
        assert list(profile) == sorted(profile)

    def test_command_is_read_only(self) -> None:
        agent = _agent()
        _queue_row(TICKET_A)
        _assigned_row(TICKET_A, agent)
        before = _table_sizes()
        call_command("profile_legacy_cycles", stdout=StringIO())
        assert _table_sizes() == before
        # Rows themselves are untouched, not merely recreated.
        assert NewConversation.objects.filter(hubspot_ticket_id=TICKET_A).exists()
        assert AssignedConversation.objects.filter(hubspot_ticket_id=TICKET_A).exists()

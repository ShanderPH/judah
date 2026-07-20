"""Gate C/E regression tests for the durable assignment protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.integrations.hubspot.exceptions import (
    HubSpotAPIError,
    HubSpotFailureKind,
    HubSpotResourceNotFoundError,
)
from apps.support.durable_assignment_service import (
    compensate_assignment_attempt,
    execute_assignment_attempt,
    finalize_assignment_attempt,
    reserve_manual_assignment,
    reserve_next_assignment,
)
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    NewConversation,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _agent(*, owner_id: int = 7001, max_chats: int = 5) -> Agent:
    now = timezone.now()
    return Agent.objects.create(
        name=f"Agent {owner_id}",
        agent_email=f"agent-{owner_id}@example.test",
        hubspot_owner_id=owner_id,
        hubspot_user_id=str(owner_id),
        status_enum=Agent.StatusEnum.ONLINE,
        is_active=True,
        auto_assign_enabled=True,
        current_simultaneous_chats=0,
        max_simultaneous_chats=max_chats,
        availability_observed_at=now,
        eligibility_state=Agent.EligibilityState.ELIGIBLE,
        eligibility_reason="eligible",
        availability_revision=4,
    )


def _queue(ticket_id: str = "9001") -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=ticket_id,
        entered_queue_at=timezone.now() - timedelta(minutes=2),
        automatic_assignment_eligible=True,
    )


def _reserve(agent: Agent, ticket_id: str = "9001") -> AssignmentAttempt:
    with patch(
        "apps.support.durable_assignment_service._verify_candidates",
        return_value=[(agent, "eligible")],
    ):
        reservation = reserve_next_assignment(ticket_id)
    assert reservation.attempt is not None
    return reservation.attempt


def test_finalize_and_redelivery_have_one_effect() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.assign_ticket_owner.return_value = {
            "id": "9001",
            "owner_id": agent.hubspot_owner_id,
        }
        assert execute_assignment_attempt(attempt.pk) == "assigned"
        assert execute_assignment_attempt(attempt.pk) == "assigned"

    agent.refresh_from_db()
    assert agent.current_simultaneous_chats == 1
    assert agent.total_assignments == 1
    assert AssignedConversation.objects.filter(hubspot_ticket_id="9001").count() == 1
    assert AssignmentLog.objects.filter(assignment_attempt=attempt).count() == 1
    assert not NewConversation.objects.filter(hubspot_ticket_id="9001").exists()


def test_compensation_is_idempotent_and_never_goes_negative() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    compensate_assignment_attempt(
        attempt.pk,
        retryable=True,
        error_code="timeout",
    )
    compensate_assignment_attempt(
        attempt.pk,
        retryable=True,
        error_code="timeout",
    )

    agent.refresh_from_db()
    attempt.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert attempt.retry_count == 1
    assert attempt.state == AssignmentAttempt.State.RETRYABLE


def test_provider_success_crash_before_finalize_is_repairable() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    with (
        patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory,
        patch(
            "apps.support.durable_assignment_service.finalize_assignment_attempt",
            side_effect=RuntimeError("simulated crash"),
        ),
    ):
        client_factory.return_value.assign_ticket_owner.return_value = {
            "id": "9001",
            "owner_id": agent.hubspot_owner_id,
        }
        with pytest.raises(RuntimeError, match="simulated crash"):
            execute_assignment_attempt(attempt.pk)

    attempt.refresh_from_db()
    assert attempt.state == AssignmentAttempt.State.EXTERNAL_APPLIED
    finalize_assignment_attempt(attempt.pk)
    assert AssignedConversation.objects.filter(hubspot_ticket_id="9001").exists()


def test_not_found_quarantines_and_releases_capacity() -> None:
    agent = _agent()
    queue_row = _queue()
    attempt = _reserve(agent)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.assign_ticket_owner.side_effect = HubSpotResourceNotFoundError("ticket", "9001")
        assert execute_assignment_attempt(attempt.pk) == "stale_ticket"

    agent.refresh_from_db()
    queue_row.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert queue_row.queue_status == NewConversation.QueueStatus.FAILED


def test_revision_change_rejects_reservation_without_capacity_leak() -> None:
    agent = _agent()
    _queue()
    stale_candidate = Agent.objects.get(pk=agent.pk)
    Agent.objects.filter(pk=agent.pk).update(availability_revision=5)

    with patch(
        "apps.support.durable_assignment_service._verify_candidates",
        return_value=[(stale_candidate, "eligible")],
    ):
        reservation = reserve_next_assignment("9001")

    agent.refresh_from_db()
    assert reservation.attempt is None
    assert agent.current_simultaneous_chats == 0
    assert AssignmentAttempt.objects.count() == 0


def test_manual_provider_rejection_has_no_false_local_success() -> None:
    agent = _agent()
    _queue()
    reservation = reserve_manual_assignment(
        ticket_id="9001",
        agent_id=agent.pk,
        requested_by="manager@example.test",
    )
    assert reservation.attempt is not None

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.assign_ticket_owner.side_effect = HubSpotAPIError(
            "forbidden",
            external_status=403,
            retryable=False,
            error_code=HubSpotFailureKind.FORBIDDEN,
        )
        client_factory.return_value.get_ticket_details.return_value = {"owner_id": ""}
        assert execute_assignment_attempt(reservation.attempt.pk) == "repair_required"

    agent.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert not AssignedConversation.objects.filter(hubspot_ticket_id="9001").exists()
    assert not AssignmentLog.objects.filter(ticket_id="9001").exists()


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL row locks are required for the concurrency proof.",
)
def test_two_workers_one_ticket_create_one_reservation() -> None:
    agent = _agent()
    _queue()

    def worker() -> str:
        close_old_connections()
        try:
            with patch(
                "apps.support.durable_assignment_service._verify_candidates",
                return_value=[(Agent.objects.get(pk=agent.pk), "eligible")],
            ):
                return reserve_next_assignment("9001").reason
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reasons = list(pool.map(lambda _: worker(), range(2)))

    agent.refresh_from_db()
    assert AssignmentAttempt.objects.filter(ticket_id="9001").count() == 1
    assert agent.current_simultaneous_chats == 1
    assert "reserved" in reasons


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL row locks are required for the capacity proof.",
)
def test_two_workers_competing_for_last_capacity_reserve_once() -> None:
    agent = _agent(max_chats=1)
    _queue("9001")
    _queue("9002")

    def worker(ticket_id: str) -> str:
        close_old_connections()
        try:
            with patch(
                "apps.support.durable_assignment_service._verify_candidates",
                return_value=[(Agent.objects.get(pk=agent.pk), "eligible")],
            ):
                return reserve_next_assignment(ticket_id).reason
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reasons = list(pool.map(worker, ("9001", "9002")))

    agent.refresh_from_db()
    assert AssignmentAttempt.objects.count() == 1
    assert agent.current_simultaneous_chats == 1
    assert reasons.count("reserved") == 1

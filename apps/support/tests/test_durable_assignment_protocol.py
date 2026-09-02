"""Gate C/E regression tests for the durable assignment protocol."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.integrations.hubspot.client import STAGE_NOVO_ID, SUPPORT_PIPELINE_ID
from apps.integrations.hubspot.exceptions import (
    HubSpotAPIError,
    HubSpotFailureKind,
    HubSpotResourceNotFoundError,
)
from apps.support.durable_assignment_service import (
    compensate_assignment_attempt,
    execute_assignment_attempt,
    finalize_assignment_attempt,
    repair_assignment_attempts,
    reserve_manual_assignment,
    reserve_next_assignment,
)
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    NewConversation,
    SupportConversationCycle,
)
from common.exceptions import ExternalServiceError

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


def _eligible_ticket(*, owner_id: int | str = "") -> dict[str, str | int]:
    return {
        "id": "9001",
        "pipeline": SUPPORT_PIPELINE_ID,
        "stage": STAGE_NOVO_ID,
        "owner_id": owner_id,
    }


def test_finalize_and_redelivery_have_one_effect() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    with (
        patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory,
        patch("apps.webhooks.metrics.emit_metric") as emit_metric,
    ):
        client_factory.return_value.get_ticket_details.side_effect = [
            _eligible_ticket(),
            _eligible_ticket(owner_id=agent.hubspot_owner_id),
        ]
        client_factory.return_value.assign_ticket_owner.return_value = {
            "id": "9001",
            "owner_id": agent.hubspot_owner_id,
        }
        assert execute_assignment_attempt(attempt.pk) == "assigned"
        assert execute_assignment_attempt(attempt.pk) == "assigned"

    provider_metrics = [
        call for call in emit_metric.call_args_list if call.args[0] == "assignment_provider_latency_seconds"
    ]
    assert [call.kwargs["operation"] for call in provider_metrics] == [
        "precondition_read",
        "owner_patch",
        "owner_readback",
    ]
    assert "9001" not in str(provider_metrics)

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
        client_factory.return_value.get_ticket_details.side_effect = [
            _eligible_ticket(),
            _eligible_ticket(owner_id=agent.hubspot_owner_id),
        ]
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


def test_repair_external_applied_reads_back_and_never_repatches() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)
    stale_at = timezone.now() - timedelta(minutes=5)
    AssignmentAttempt.objects.filter(pk=attempt.pk).update(
        state=AssignmentAttempt.State.EXTERNAL_APPLIED,
        external_applied_at=stale_at,
        updated_at=stale_at,
    )

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.return_value = _eligible_ticket(owner_id=agent.hubspot_owner_id)

        first = repair_assignment_attempts(limit=1)
        second = repair_assignment_attempts(limit=1)

    attempt.refresh_from_db()
    assert first["completed"] == 1
    assert second["scanned"] == 0
    assert attempt.state == AssignmentAttempt.State.COMPLETED
    assert client_factory.return_value.get_ticket_details.call_count == 1
    client_factory.return_value.assign_ticket_owner.assert_not_called()


def test_execute_external_applied_reads_back_and_never_repatches() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)
    AssignmentAttempt.objects.filter(pk=attempt.pk).update(
        state=AssignmentAttempt.State.EXTERNAL_APPLIED,
        external_applied_at=timezone.now(),
    )

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.return_value = _eligible_ticket(owner_id=agent.hubspot_owner_id)

        assert execute_assignment_attempt(attempt.pk) == "assigned"

    client_factory.return_value.get_ticket_details.assert_called_once_with("9001")
    client_factory.return_value.assign_ticket_owner.assert_not_called()


def test_repair_is_bounded_deterministic_and_skips_recent_attempts() -> None:
    agent = _agent()
    stale_at = timezone.now() - timedelta(minutes=5)
    recent_at = timezone.now()
    old_attempts = []
    for index, state in enumerate(
        (
            AssignmentAttempt.State.RESERVED,
            AssignmentAttempt.State.EXTERNAL_APPLIED,
            AssignmentAttempt.State.REPAIR_REQUIRED,
        )
    ):
        attempt = AssignmentAttempt.objects.create(
            idempotency_key=f"00000000-0000-0000-0000-0000000001{index:02d}",
            ticket_id=f"repair-old-{index}",
            selected_agent=agent,
            eligibility_revision=1,
            desired_hubspot_owner_id=agent.hubspot_owner_id,
            decision_reason="test",
            state=state,
            reserved_at=stale_at,
        )
        AssignmentAttempt.objects.filter(pk=attempt.pk).update(updated_at=stale_at + timedelta(seconds=index))
        old_attempts.append(attempt)
    recent = AssignmentAttempt.objects.create(
        idempotency_key="00000000-0000-0000-0000-000000000199",
        ticket_id="repair-recent",
        selected_agent=agent,
        eligibility_revision=1,
        desired_hubspot_owner_id=agent.hubspot_owner_id,
        decision_reason="test",
        state=AssignmentAttempt.State.REPAIR_REQUIRED,
        reserved_at=recent_at,
    )

    with patch(
        "apps.support.durable_assignment_service.reconcile_ambiguous_attempt",
        return_value="repair_required",
    ) as reconcile:
        counts = repair_assignment_attempts(limit=2)

    assert counts["scanned"] == 2
    assert [call.args[0] for call in reconcile.call_args_list] == [attempt.pk for attempt in old_attempts[:2]]
    assert recent.pk not in [call.args[0] for call in reconcile.call_args_list]


def test_not_found_quarantines_and_releases_capacity() -> None:
    agent = _agent()
    queue_row = _queue()
    attempt = _reserve(agent)

    with (
        patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory,
        patch("apps.support.durable_assignment_service.logger") as log,
    ):
        client_factory.return_value.get_ticket_details.return_value = _eligible_ticket()
        client_factory.return_value.assign_ticket_owner.side_effect = HubSpotResourceNotFoundError("ticket", "9001")
        assert execute_assignment_attempt(attempt.pk) == "stale_ticket"

    agent.refresh_from_db()
    queue_row.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert queue_row.queue_status == NewConversation.QueueStatus.FAILED
    compensation_log = log.warning.call_args
    assert compensation_log.args == ("assignment_attempt_compensated",)
    assert compensation_log.kwargs["error_catalog_code"] == "SUP-HUBSPOT-001"
    assert compensation_log.kwargs["message_error"].startswith("Erro catalogado [SUP-HUBSPOT-001]:")
    assert compensation_log.kwargs["ticket_id"] == "9001"
    assert compensation_log.kwargs["queue_row_id"] == str(queue_row.pk)
    assert compensation_log.kwargs["quarantine"] is True


def test_revision_only_change_preserves_materially_eligible_candidate() -> None:
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
    assert reservation.attempt is not None
    assert reservation.attempt.eligibility_revision == 5
    assert agent.current_simultaneous_chats == 1
    assert AssignmentAttempt.objects.count() == 1


def test_completed_same_cycle_consumes_residual_queue_without_new_effect() -> None:
    now = timezone.now()
    agent = _agent()
    cycle = SupportConversationCycle.objects.create(
        cycle_key="completed-same-cycle",
        source_account_id="test-account",
        hubspot_ticket_id="9001",
        entered_stage_at=now - timedelta(minutes=2),
        opened_at=now - timedelta(minutes=2),
    )
    queue_row = _queue()
    queue_row.cycle = cycle
    queue_row.save(update_fields=["cycle", "updated_at"])
    queue_row_id = queue_row.pk
    completed = AssignmentAttempt.objects.create(
        idempotency_key="4d07dfd1-3cd5-456a-86d7-f47713ea48bb",
        ticket_id="9001",
        cycle=cycle,
        queue_row=queue_row,
        selected_agent=agent,
        eligibility_revision=agent.availability_revision,
        desired_hubspot_owner_id=agent.hubspot_owner_id,
        decision_reason="eligible",
        reserved_at=now,
        state=AssignmentAttempt.State.COMPLETED,
    )

    with patch("apps.support.durable_assignment_service._verify_candidates", return_value=[(agent, "eligible")]):
        reservation = reserve_next_assignment("9001")

    assert reservation.attempt == completed
    assert reservation.reason == "completed_same_cycle"
    assert not NewConversation.objects.filter(pk=queue_row_id).exists()
    assert agent.current_simultaneous_chats == 0


def test_legacy_completed_attempt_quarantines_ambiguous_row() -> None:
    now = timezone.now()
    agent = _agent()
    queue_row = _queue()
    AssignmentAttempt.objects.create(
        idempotency_key="50daeeef-d135-47a7-8f8c-c5b1df05f736",
        ticket_id="9001",
        selected_agent=agent,
        eligibility_revision=agent.availability_revision,
        desired_hubspot_owner_id=agent.hubspot_owner_id,
        decision_reason="historical",
        reserved_at=now - timedelta(days=1),
        state=AssignmentAttempt.State.COMPLETED,
    )

    with (
        patch("apps.support.durable_assignment_service._verify_candidates", return_value=[(agent, "eligible")]),
        patch("apps.support.durable_assignment_service.logger") as log,
    ):
        reservation = reserve_next_assignment("9001")

    queue_row.refresh_from_db()
    assert reservation.reason == "legacy_cycle_ambiguous"
    assert queue_row.queue_status == NewConversation.QueueStatus.FAILED
    assert queue_row.failure_code == "legacy_cycle_ambiguous"
    assert agent.current_simultaneous_chats == 0
    quarantine_log = log.warning.call_args
    assert quarantine_log.args == ("assignment_queue_row_quarantined",)
    assert quarantine_log.kwargs["error_catalog_code"] == "SUP-QUEUE-001"
    assert quarantine_log.kwargs["message_error"].startswith("Erro catalogado [SUP-QUEUE-001]:")
    assert quarantine_log.kwargs["ticket_id"] == "9001"
    assert quarantine_log.kwargs["queue_row_id"] == str(queue_row.pk)


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
        client_factory.return_value.get_ticket_details.side_effect = [
            _eligible_ticket(),
            {"owner_id": ""},
        ]
        client_factory.return_value.assign_ticket_owner.side_effect = HubSpotAPIError(
            "forbidden",
            external_status=403,
            retryable=False,
            error_code=HubSpotFailureKind.FORBIDDEN,
        )
        assert execute_assignment_attempt(reservation.attempt.pk) == "repair_required"

    agent.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert not AssignedConversation.objects.filter(hubspot_ticket_id="9001").exists()
    assert not AssignmentLog.objects.filter(ticket_id="9001").exists()


@pytest.mark.parametrize(
    ("ticket_overrides", "expected_error"),
    [
        ({"pipeline": "different-pipeline"}, "stale_ticket"),
        ({"stage": "different-stage"}, "stale_ticket"),
        ({"stage": ""}, "stale_ticket"),
    ],
)
def test_pre_effect_ticket_drift_fails_closed_without_owner_patch(
    ticket_overrides: dict[str, str],
    expected_error: str,
) -> None:
    agent = _agent()
    queue_row = _queue()
    attempt = _reserve(agent)
    ticket = _eligible_ticket()
    ticket.update(ticket_overrides)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.return_value = ticket

        assert execute_assignment_attempt(attempt.pk) == "stale_ticket"
        client_factory.return_value.assign_ticket_owner.assert_not_called()

    agent.refresh_from_db()
    attempt.refresh_from_db()
    queue_row.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert attempt.state == AssignmentAttempt.State.COMPENSATED
    assert attempt.last_error_code == expected_error
    assert queue_row.queue_status == NewConversation.QueueStatus.FAILED
    assert queue_row.failure_code == expected_error


def test_pre_effect_manual_owner_converges_without_owner_patch() -> None:
    agent = _agent()
    queue_row = _queue()
    attempt = _reserve(agent)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.return_value = _eligible_ticket(owner_id=9999)

        assert execute_assignment_attempt(attempt.pk) == "converged_external_owner"
        client_factory.return_value.assign_ticket_owner.assert_not_called()

    agent.refresh_from_db()
    attempt.refresh_from_db()
    queue_row.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert attempt.state == AssignmentAttempt.State.COMPENSATED
    assert attempt.last_error_code == "hubspot_manual_owner_observed"
    assert queue_row.queue_status == NewConversation.QueueStatus.FAILED
    assert queue_row.failure_code == "hubspot_manual_owner_observed"


def test_pre_effect_read_failure_releases_capacity_for_bounded_retry() -> None:
    agent = _agent()
    queue_row = _queue()
    attempt = _reserve(agent)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.side_effect = ExternalServiceError("HubSpot", "offline")

        assert execute_assignment_attempt(attempt.pk) == "retryable_external_error"
        client_factory.return_value.assign_ticket_owner.assert_not_called()

    agent.refresh_from_db()
    attempt.refresh_from_db()
    queue_row.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert attempt.state == AssignmentAttempt.State.RETRYABLE
    assert attempt.last_error_code == "hubspot_precondition_unreadable"
    assert queue_row.queue_status == NewConversation.QueueStatus.QUEUED
    assert queue_row.next_assignment_attempt_at is not None


def test_pre_effect_desired_owner_finalizes_once_without_second_patch() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    with patch("apps.support.durable_assignment_service.get_hubspot_client") as client_factory:
        client_factory.return_value.get_ticket_details.return_value = _eligible_ticket(owner_id=agent.hubspot_owner_id)

        assert execute_assignment_attempt(attempt.pk) == "assigned"
        assert execute_assignment_attempt(attempt.pk) == "assigned"
        client_factory.return_value.assign_ticket_owner.assert_not_called()

    agent.refresh_from_db()
    attempt.refresh_from_db()
    assert attempt.state == AssignmentAttempt.State.COMPLETED
    assert attempt.provider_result_classification == "confirmed_before_write"
    assert agent.current_simultaneous_chats == 1
    assert agent.total_assignments == 1
    assert AssignedConversation.objects.filter(hubspot_ticket_id="9001").count() == 1
    assert AssignmentLog.objects.filter(assignment_attempt=attempt).count() == 1


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


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL row locks are required for the compensation proof.",
)
def test_two_workers_compensate_capacity_exactly_once() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)

    def worker() -> str:
        close_old_connections()
        try:
            compensated = compensate_assignment_attempt(
                attempt.pk,
                retryable=True,
                error_code="timeout",
            )
            return compensated.state
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(lambda _index: worker(), range(2)))

    agent.refresh_from_db()
    attempt.refresh_from_db()
    assert states == [AssignmentAttempt.State.RETRYABLE] * 2
    assert agent.current_simultaneous_chats == 0
    assert attempt.retry_count == 1
    assert attempt.compensated_at is not None


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="PostgreSQL row locks are required for the finalization proof.",
)
def test_two_workers_finalize_projection_and_counter_exactly_once() -> None:
    agent = _agent()
    _queue()
    attempt = _reserve(agent)
    AssignmentAttempt.objects.filter(pk=attempt.pk).update(
        state=AssignmentAttempt.State.EXTERNAL_APPLIED,
        external_applied_at=timezone.now(),
    )

    def worker() -> str:
        close_old_connections()
        try:
            finalized = finalize_assignment_attempt(attempt.pk)
            return finalized.state
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        states = list(pool.map(lambda _index: worker(), range(2)))

    agent.refresh_from_db()
    attempt.refresh_from_db()
    assert states == [AssignmentAttempt.State.COMPLETED] * 2
    assert attempt.state == AssignmentAttempt.State.COMPLETED
    assert agent.current_simultaneous_chats == 1
    assert agent.total_assignments == 1
    assert AssignedConversation.objects.filter(hubspot_ticket_id="9001").count() == 1
    assert AssignmentLog.objects.filter(assignment_attempt=attempt).count() == 1

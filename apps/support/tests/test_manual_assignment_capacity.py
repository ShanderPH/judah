"""Capacity regressions using real owner tasks and candidate selection."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.integrations.hubspot.client import STAGE_NOVO_ID, SUPPORT_PIPELINE_ID
from apps.support.durable_assignment_service import (
    compensate_assignment_attempt,
    execute_assignment_attempt,
    reconcile_ambiguous_attempt,
    reserve_next_assignment,
)
from apps.support.models import (
    Agent,
    AgentCapacityReservation,
    AssignedConversation,
    NewConversation,
    SupportConversationCycle,
    SupportTicketOccupancy,
)
from apps.support.tasks import task_handle_owner_change

pytestmark = pytest.mark.django_db


def agent(owner: int) -> Agent:
    return Agent.objects.create(
        name=str(owner),
        agent_email=f"{owner}@example.test",
        hubspot_owner_id=owner,
        status_enum="online",
        is_active=True,
        auto_assign_enabled=True,
        max_simultaneous_chats=5,
    )


def ticket(owner: int | str, ticket_id: str = "cap-1") -> dict:
    return {
        "id": ticket_id,
        "owner_id": str(owner),
        "pipeline": SUPPORT_PIPELINE_ID,
        "stage": STAGE_NOVO_ID,
        "updated_at": timezone.now().isoformat(),
    }


@pytest.fixture(autouse=True)
def capacity_mode(settings):
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED = False


def test_transfer_without_previous_owner():
    source, target = agent(100), agent(200)
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    Agent.objects.filter(pk=source.pk).update(current_simultaneous_chats=1)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = ticket(200)
        task_handle_owner_change("cap-1", "200", {"sourceId": "userId:999"})
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)


def test_manual_without_queue_counts_once():
    target = agent(200)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = ticket(200)
        task_handle_owner_change("cap-1", "200", {})
        task_handle_owner_change("cap-1", "200", {})
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert not AssignedConversation.objects.exists()


def test_specific_failed_queue_converges():
    target = agent(200)
    NewConversation.objects.create(
        hubspot_ticket_id="cap-1",
        entered_queue_at=timezone.now(),
        queue_status="failed",
        failure_code="hubspot_manual_owner_observed",
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = ticket(200)
        task_handle_owner_change("cap-1", "200", {})
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_full_remote_portfolio_vetoes_real_selection():
    target = agent(200)
    Agent.objects.filter(pk=target.pk).update(current_simultaneous_chats=4)
    NewConversation.objects.create(
        hubspot_ticket_id="cap-new",
        entered_queue_at=timezone.now(),
        automatic_assignment_eligible=True,
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.list_active_ticket_ids_by_owner.return_value = (
            ("1", "2", "3", "4", "5"),
            True,
        )
        provider.return_value.get_ticket_details.side_effect = lambda identity: ticket(200, identity)
        result = reserve_next_assignment("cap-new")
    assert result.attempt is None


@pytest.fixture
def provider():
    client = MagicMock()
    client.list_active_ticket_ids_by_owner.return_value = ((), True)
    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client", return_value=client),
        patch("apps.support.durable_assignment_service.get_hubspot_client", return_value=client),
    ):
        yield client


def ready(target: Agent) -> None:
    Agent.objects.filter(pk=target.pk).update(capacity_state="ready", capacity_reconciled_at=timezone.now())


def queue(identity: str = "cap-1") -> NewConversation:
    return NewConversation.objects.create(
        hubspot_ticket_id=identity, entered_queue_at=timezone.now(), automatic_assignment_eligible=True
    )


def test_confirmed_effect_and_webhook_share_one_unit(provider):
    target = agent(200)
    queue()
    provider.get_ticket_details.return_value = ticket("")
    reservation = reserve_next_assignment("cap-1")
    assert reservation.attempt is not None
    provider.assign_ticket_owner.side_effect = lambda *args: setattr(
        provider.get_ticket_details, "return_value", ticket(200)
    )
    assert execute_assignment_attempt(reservation.attempt.pk) == "assigned"
    task_handle_owner_change("cap-1", "200", {})
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert AgentCapacityReservation.objects.get().state == "converted"
    assert AssignedConversation.objects.count() == 1
    assert target.total_assignments == 1
    assert execute_assignment_attempt(reservation.attempt.pk) == "assigned"
    provider.assign_ticket_owner.assert_called_once()


def test_ambiguous_failure_holds_capacity_until_repair(provider):
    target = agent(200)
    queue()
    reservation = reserve_next_assignment("cap-1")
    assert reservation.attempt is not None
    provider.get_ticket_details.side_effect = RuntimeError("provider unavailable")
    assert reconcile_ambiguous_attempt(reservation.attempt.pk) == "repair_required"
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert target.capacity_state == "degraded"
    assert AgentCapacityReservation.objects.get().state == "held"
    provider.get_ticket_details.side_effect = None
    provider.get_ticket_details.return_value = ticket(200)
    assert reconcile_ambiguous_attempt(reservation.attempt.pk) == "assigned"
    assert AgentCapacityReservation.objects.get().state == "converted"
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_compensation_repeated_releases_only_once(provider):
    target = agent(200)
    queue()
    reservation = reserve_next_assignment("cap-1")
    assert reservation.attempt is not None
    for _ in range(2):
        compensate_assignment_attempt(reservation.attempt.pk, retryable=True, error_code="pre_effect_rejected")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 0
    assert AgentCapacityReservation.objects.get().state == "released"


def test_partial_portfolio_preserves_occupancy_and_blocks(provider):
    from apps.support.owner_reconciliation_service import reconcile_ticket, refresh_agent_capacity

    target = agent(200)
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    provider.list_active_ticket_ids_by_owner.return_value = ((), False)
    assert not refresh_agent_capacity(target, force=True)
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert target.capacity_state == "degraded"


def test_search_absence_is_confirmed_by_identity(provider):
    from apps.support.owner_reconciliation_service import reconcile_ticket, refresh_agent_capacity

    target = agent(200)
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    provider.get_ticket_details.reset_mock()
    assert refresh_agent_capacity(target, force=True)
    provider.get_ticket_details.assert_called_once_with("cap-1")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


@pytest.mark.parametrize("owners", [(100, 200, 100, 200), (200, 200, 200)])
def test_repeated_transfers_use_current_identity(provider, owners):
    source, target = agent(100), agent(200)
    for owner in owners:
        provider.get_ticket_details.return_value = ticket(owner)
        task_handle_owner_change("cap-1", str(owner), {"previousValue": "999", "sourceId": "100"})
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)
    assert SupportTicketOccupancy.objects.count() == 1


def test_owner_removal_does_not_requeue_assigned_cycle(provider):
    from apps.support.conversation_cycle_service import open_or_get_cycle
    from apps.support.owner_reconciliation_service import reconcile_ticket

    target = agent(200)
    cycle = open_or_get_cycle(
        hubspot_ticket_id="cap-1", entered_stage_value=str(int(timezone.now().timestamp() * 1000))
    ).cycle
    assert cycle is not None
    cycle.state = "assigned"
    cycle.save()
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        cycle=cycle,
        agent=target,
        hubspot_owner_id=200,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    provider.get_ticket_details.return_value = ticket("")
    task_handle_owner_change("cap-1", None, {})
    target.refresh_from_db()
    cycle.refresh_from_db()
    assert target.current_simultaneous_chats == 0
    assert cycle.state == "assigned"
    assert not AssignedConversation.objects.exists()
    assert not NewConversation.objects.exists()


def test_manual_proven_entry_creates_cycle_without_auto_effect(provider):
    target = agent(200)
    provider.get_ticket_details.return_value = {
        **ticket(200),
        "entered_novo_at": str(int(timezone.now().timestamp() * 1000)),
    }
    task_handle_owner_change("cap-1", "200", {})
    assert SupportConversationCycle.objects.get().state == "assigned"
    assert AssignedConversation.objects.get().agent == target
    provider.assign_ticket_owner.assert_not_called()


def test_old_provider_snapshot_cannot_restore_owner(provider):
    from apps.support.owner_reconciliation_service import CapacityObservationConflictError, reconcile_ticket

    target = agent(200)
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    provider.get_ticket_details.return_value = {
        **ticket(100),
        "updated_at": (timezone.now() - timedelta(days=1)).isoformat(),
    }
    with pytest.raises(CapacityObservationConflictError):
        reconcile_ticket("cap-1")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert target.capacity_state == "degraded"


def test_unknown_owner_is_bound_when_registered(provider):
    from apps.support.owner_reconciliation_service import reconcile_ticket, refresh_agent_capacity

    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    assert SupportTicketOccupancy.objects.get().agent is None
    target = agent(200)
    provider.list_active_ticket_ids_by_owner.return_value = (("cap-1",), True)
    assert refresh_agent_capacity(target)
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_full_first_candidate_falls_back_to_second(provider):
    first, second = agent(100), agent(200)
    queue()
    Agent.objects.filter(pk=second.pk).update(last_assignment_at=timezone.now())
    provider.list_active_ticket_ids_by_owner.side_effect = lambda owner: (
        (("1", "2", "3", "4", "5"), True) if owner == 100 else ((), True)
    )
    provider.get_ticket_details.side_effect = lambda identity: ticket(100, identity)
    reservation = reserve_next_assignment("cap-1")
    assert reservation.attempt is not None
    assert reservation.attempt.selected_agent == second
    first.refresh_from_db()
    assert first.current_simultaneous_chats == 5


def test_close_without_cycle_releases_only_current_ticket(provider):
    from apps.integrations.hubspot.client import STAGE_FECHADO_ID
    from apps.support.auto_assign_service import handle_ticket_closed
    from apps.support.owner_reconciliation_service import reconcile_ticket

    target = agent(200)
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    provider.get_ticket_details.return_value = {**ticket(200), "stage": STAGE_FECHADO_ID}
    handle_ticket_closed("cap-1")
    handle_ticket_closed("cap-1")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 0


def test_shadow_preserves_legacy_counter(provider, settings):
    from apps.support.owner_reconciliation_service import reconcile_ticket

    settings.SUPPORT_CAPACITY_MODE = "shadow"
    target = agent(200)
    Agent.objects.filter(pk=target.pk).update(current_simultaneous_chats=3)
    provider.get_ticket_details.return_value = ticket(200)
    reconcile_ticket("cap-1")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 3
    assert SupportTicketOccupancy.objects.get().state == "active"
    assert not AgentCapacityReservation.objects.exists()


def test_admin_transfer_and_own_webhook_do_not_double_count(provider):
    from apps.support.admin_api import _force_reassign_internal

    source, target = agent(100), agent(200)
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    provider.get_ticket_details.return_value = ticket(100)

    def apply_and_deliver(*args):
        source.refresh_from_db()
        target.refresh_from_db()
        assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (1, 1)
        provider.get_ticket_details.return_value = ticket(200)
        task_handle_owner_change("cap-1", "200", {})

    provider.assign_ticket_owner.side_effect = apply_and_deliver
    assert _force_reassign_internal("cap-1", target)["success"]
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)
    assert AgentCapacityReservation.objects.get().state == "converted"


def test_timeout_and_unassigned_readback_remain_ambiguous(provider):
    from apps.integrations.hubspot.exceptions import HubSpotAPIError

    target = agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    provider.get_ticket_details.return_value = ticket("")
    error = HubSpotAPIError("timeout", retryable=True)
    assert reconcile_ambiguous_attempt(attempt.pk, error) == "repair_required"
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert AgentCapacityReservation.objects.get().state == "held"


def test_bootstrap_distinguishes_released_retry_from_ambiguous_operation(provider, settings):
    from apps.support.management.commands.bootstrap_support_capacity import bootstrap_agent

    target = agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    compensate_assignment_attempt(attempt.pk, retryable=True, error_code="pre_effect_rejected")
    AgentCapacityReservation.objects.all().delete()
    settings.SUPPORT_CAPACITY_MODE = "shadow"
    provider.get_ticket_details.return_value = ticket("")
    bootstrap_agent(target)
    bootstrap_agent(target)
    assert AgentCapacityReservation.objects.get().state == "released"
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 0


def test_precondition_cannot_overwrite_newer_known_owner(provider):
    from apps.support.owner_reconciliation_service import reconcile_ticket

    agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    provider.get_ticket_details.return_value = ticket(100)
    reconcile_ticket("cap-1")
    provider.get_ticket_details.return_value = {
        **ticket(""),
        "updated_at": (timezone.now() - timedelta(hours=1)).isoformat(),
    }
    assert execute_assignment_attempt(attempt.pk) == "retryable_external_error"
    provider.assign_ticket_owner.assert_not_called()
    assert SupportTicketOccupancy.objects.get().hubspot_owner_id == 100


def test_shadow_provider_failure_preserves_legacy_owner_path(provider, settings):
    settings.SUPPORT_CAPACITY_MODE = "shadow"
    source, target = agent(100), agent(200)
    Agent.objects.filter(pk=source.pk).update(current_simultaneous_chats=1)
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    provider.get_ticket_details.side_effect = TimeoutError
    task_handle_owner_change("cap-1", "200", {"previousValue": "100"})
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)


def test_retry_reuses_released_reservation_and_verifies_real_eligibility(provider, settings):
    from datetime import UTC, datetime

    from apps.support.durable_assignment_service import retry_assignment_attempt

    captured = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
    with (
        patch("django.utils.timezone.now", return_value=captured),
        patch(
            "apps.support.durable_assignment_service._database_now",
            return_value=captured,
        ),
    ):
        target = agent(200)
        Agent.objects.filter(pk=target.pk).update(
            hubspot_user_id="user-200",
            availability_observed_at=captured,
            eligibility_state="eligible",
            eligibility_reason="eligible",
        )
        queue()
        provider.get_ticket_details.return_value = ticket("")
        attempt = reserve_next_assignment("cap-1").attempt
        assert attempt is not None
        compensate_assignment_attempt(attempt.pk, retryable=True, error_code="pre_effect_rejected")
    settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED = True
    next_time = captured + timedelta(seconds=61)
    Agent.objects.filter(pk=target.pk).update(availability_observed_at=next_time)
    provider.get_user_by_id.return_value = {
        "id": "user-200",
        "email": "200@example.test",
        "hs_availability_status": "available",
        "hs_out_of_office_hours": "[]",
    }
    provider.get_ticket_details.return_value = {**ticket(""), "updated_at": captured.isoformat()}
    provider.assign_ticket_owner.side_effect = lambda *args: setattr(
        provider.get_ticket_details, "return_value", ticket(200)
    )
    with (
        patch("django.utils.timezone.now", return_value=next_time),
        patch(
            "apps.support.durable_assignment_service._database_now",
            return_value=next_time,
        ),
    ):
        assert retry_assignment_attempt(attempt.pk) == "assigned"
        assert retry_assignment_attempt(attempt.pk) == "completed"
    assert AgentCapacityReservation.objects.count() == 1
    assert AgentCapacityReservation.objects.get().state == "converted"
    provider.get_user_by_id.assert_called_once_with("user-200")
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_repair_after_confirmed_effect_uses_readback_without_repatch(provider):
    from apps.support.durable_assignment_service import repair_assignment_attempts
    from apps.support.models import AssignmentAttempt

    target = agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    AssignmentAttempt.objects.filter(pk=attempt.pk).update(
        state="external_applied", external_applied_at=timezone.now(), updated_at=timezone.now() - timedelta(minutes=3)
    )
    provider.get_ticket_details.return_value = ticket(200)
    result = repair_assignment_attempts()
    assert result["completed"] == 1
    provider.assign_ticket_owner.assert_not_called()
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_bootstrap_command_requires_shadow_and_reports_ready_portfolio(provider, settings):
    import json
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("bootstrap_support_capacity")
    settings.SUPPORT_CAPACITY_MODE = "shadow"
    target = agent(200)
    output = StringIO()
    call_command("bootstrap_support_capacity", stdout=output)
    report = json.loads(output.getvalue())
    assert report["agents"][0]["agent_id"] == str(target.pk)
    assert report["agents"][0]["ready"]


def test_admin_ambiguous_transfer_preserves_destination_reservation(provider):
    from apps.support.admin_api import _force_reassign_internal
    from common.exceptions import ValidationError

    source, target = agent(100), agent(200)
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    provider.get_ticket_details.return_value = ticket(100)
    provider.assign_ticket_owner.side_effect = TimeoutError
    with pytest.raises(ValidationError, match="unconfirmed"):
        _force_reassign_internal("cap-1", target)
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (1, 1)
    assert target.capacity_state == "degraded"
    assert AgentCapacityReservation.objects.get().state == "held"


def test_retry_state_alone_cannot_reuse_a_held_reservation(provider):
    from apps.support.durable_assignment_service import retry_assignment_attempt
    from apps.support.models import AssignmentAttempt

    target = agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    AssignmentAttempt.objects.filter(pk=attempt.pk).update(state="retryable")
    assert retry_assignment_attempt(attempt.pk) == "capacity_reservation_not_released"
    provider.assign_ticket_owner.assert_not_called()
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert AgentCapacityReservation.objects.get().state == "held"


def test_duplicate_readback_before_cycle_finalize_preserves_attempt_identity(provider):
    from apps.support.conversation_cycle_service import open_or_get_cycle
    from apps.support.durable_assignment_service import _mark_external_applied, finalize_assignment_attempt
    from apps.support.models import AssignmentLog
    from apps.support.owner_reconciliation_service import reconcile_ticket

    target = agent(200)
    cycle = open_or_get_cycle(
        hubspot_ticket_id="cap-1", entered_stage_value=str(int(timezone.now().timestamp() * 1000))
    ).cycle
    assert cycle is not None
    queue_row = queue()
    queue_row.cycle = cycle
    queue_row.save()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    provider.get_ticket_details.return_value = ticket(200)
    # Provider confirmation commits, then the worker stops before finalization.
    reconcile_ticket("cap-1", source="effect_readback")
    _mark_external_applied(attempt.pk, classification="confirmed_by_read")
    # Redelivery/repair reads again while the reservation is already converted.
    reconcile_ticket("cap-1", source="effect_readback")
    cycle.refresh_from_db()
    assert cycle.state == "queued"
    assert not AssignedConversation.objects.exists()
    finalize_assignment_attempt(attempt.pk)
    finalize_assignment_attempt(attempt.pk)
    cycle.refresh_from_db()
    target.refresh_from_db()
    assert cycle.state == "assigned"
    assert target.current_simultaneous_chats == 1
    assert AssignedConversation.objects.get().cycle == cycle
    assert AssignmentLog.objects.get().assignment_attempt == attempt


def test_reopened_identity_does_not_rewrite_an_unresolved_previous_cycle(provider):
    from apps.support.conversation_cycle_service import open_or_get_cycle
    from apps.support.owner_reconciliation_service import reconcile_ticket

    source, target = agent(100), agent(200)
    old_entry = str(int((timezone.now() - timedelta(days=2)).timestamp() * 1000))
    cycle = open_or_get_cycle(hubspot_ticket_id="cap-1", entered_stage_value=old_entry).cycle
    assert cycle is not None
    cycle.state = "assigned"
    cycle.save()
    assigned = AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        cycle=cycle,
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now() - timedelta(days=2),
        entered_queue_at=cycle.entered_stage_at,
    )
    provider.get_ticket_details.return_value = {**ticket(100), "entered_novo_at": old_entry}
    reconcile_ticket("cap-1")
    provider.get_ticket_details.return_value = {
        **ticket(200),
        "entered_novo_at": str(int(timezone.now().timestamp() * 1000)),
    }
    reconcile_ticket("cap-1")
    assigned.refresh_from_db()
    source.refresh_from_db()
    target.refresh_from_db()
    assert assigned.hubspot_owner_id == 100
    assert SupportConversationCycle.objects.count() == 1
    assert SupportTicketOccupancy.objects.get().cycle is None
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)


def test_confirmed_archive_releases_held_capacity_without_finalizing(provider):
    target = agent(200)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    provider.get_ticket_details.return_value = {**ticket(200), "archived": True}
    assert reconcile_ambiguous_attempt(attempt.pk) == "stale_ticket"
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 0
    assert AgentCapacityReservation.objects.get().state == "released"
    assert not AssignedConversation.objects.exists()


def test_public_eligibility_still_excludes_full_agents():
    from apps.support.queue_service import get_eligible_agents

    target = agent(200)
    Agent.objects.filter(pk=target.pk).update(current_simultaneous_chats=5)
    assert get_eligible_agents() == []


def test_remote_full_alternative_does_not_exclude_last_automatic_owner(provider):
    from apps.support.models import AssignmentLog

    agent(100)
    last = agent(200)
    AssignmentLog.objects.create(
        ticket_id="previous", agent=last, agent_name=last.name, hubspot_owner_id=200, assignment_type="automatic"
    )
    queue()
    provider.list_active_ticket_ids_by_owner.side_effect = lambda owner: (
        (("1", "2", "3", "4", "5"), True) if owner == 100 else ((), True)
    )
    provider.get_ticket_details.side_effect = lambda identity: ticket(100, identity)
    result = reserve_next_assignment("cap-1")
    assert result.attempt is not None
    assert result.attempt.selected_agent == last

"""Occurrence-time closure regressions and provider-boundary checks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection

from apps.support.auto_assign_service import handle_ticket_closed
from apps.support.models import (
    Agent,
    AssignedConversation,
    ClosedConversation,
    NewConversation,
    SupportConversationCycle,
)
from apps.support.ticket_close_service import CloseClassification, TicketCloseOccurrence, reconcile_close_occurrence

T0 = datetime(2026, 9, 1, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


@pytest.fixture(autouse=True)
def close_settings(settings):
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    settings.SUPPORT_CAPACITY_MODE = "off"


def cycle(*, entered_at=T0, state="assigned"):
    return SupportConversationCycle.objects.create(
        cycle_key=f"close:{entered_at.isoformat()}",
        source_account_id="test-portal",
        hubspot_ticket_id="close-ticket",
        entered_stage_at=entered_at,
        opened_at=entered_at,
        state=state,
    )


def assignment(target):
    agent = Agent.objects.create(
        hubspot_owner_id=700,
        name="Test",
        agent_email="test@example.test",
        current_simultaneous_chats=1,
    )
    AssignedConversation.objects.create(
        hubspot_ticket_id=target.hubspot_ticket_id,
        cycle=target,
        agent=agent,
        hubspot_owner_id=700,
        assigned_at=T0,
    )
    return agent


def snapshot(settings):
    return {
        "id": "close-ticket",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID,
        "owner_id": None,
        "entered_closed_at": str(int(T1.timestamp() * 1000)),
        "updated_at": (T1 + timedelta(seconds=5)).isoformat(),
    }


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_current_close_and_retries_have_one_effect(settings, mode):
    """Current closure applies once across all capacity modes."""
    settings.SUPPORT_CAPACITY_MODE = mode
    target = cycle()
    agent = assignment(target)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        results = [handle_ticket_closed("close-ticket", str(int(T1.timestamp() * 1000))) for _ in range(3)]
    assert results[0].classification == CloseClassification.APPLIED_CURRENT
    assert all(result.classification == CloseClassification.DUPLICATE for result in results[1:])
    target.refresh_from_db()
    agent.refresh_from_db()
    assert target.state == "closed"
    assert target.closed_at == T1
    assert ClosedConversation.objects.get(cycle=target).closed_at == T1
    assert not AssignedConversation.objects.filter(cycle=target).exists()
    assert agent.current_simultaneous_chats == 0


@pytest.mark.parametrize("value", [None, "", "bad", "123", "999999999999999999"])
def test_invalid_timestamp_never_mutates(value):
    target = cycle()
    assignment(target)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        result = handle_ticket_closed("close-ticket", value)
    assert result.classification == CloseClassification.IDENTITY_UNAVAILABLE
    provider.assert_not_called()
    assert AssignedConversation.objects.filter(cycle=target).exists()
    assert not ClosedConversation.objects.exists()


def test_provider_failure_leaves_cycle_untouched():
    """Provider failure leaves active projections unchanged."""
    target = cycle()
    assignment(target)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = RuntimeError("unavailable")
        with pytest.raises(RuntimeError, match="unavailable"):
            reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    target.refresh_from_db()
    assert target.state == "assigned"
    assert not ClosedConversation.objects.exists()
    assert AssignedConversation.objects.filter(cycle=target).exists()


def test_unmaterialized_reopen_is_rejected(settings):
    """A later provider reopening blocks old close materialization."""
    target = cycle()
    assignment(target)
    current = snapshot(settings)
    current["entered_novo_at"] = str(int((T1 + timedelta(hours=1)).timestamp() * 1000))
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = current
        result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    assert result.classification == CloseClassification.REOPEN_NOT_MATERIALIZED
    assert AssignedConversation.objects.filter(cycle=target).exists()
    assert not ClosedConversation.objects.exists()


def test_dry_run_does_not_mutate(settings):
    """Dry-run reports eligibility without changing projections."""
    target = cycle()
    agent = assignment(target)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1), dry_run=True)
    assert result.classification == CloseClassification.APPLIED_CURRENT
    target.refresh_from_db()
    agent.refresh_from_db()
    assert target.state == "assigned"
    assert agent.current_simultaneous_chats == 1
    assert AssignedConversation.objects.filter(cycle=target).exists()
    assert not ClosedConversation.objects.exists()


def test_revision_change_after_reconciliation_is_retryable(settings):
    """Revision races raise retryable conflicts before close writes."""
    from apps.support.owner_reconciliation_service import CapacityObservationConflictError

    settings.SUPPORT_CAPACITY_MODE = "shadow"
    target = cycle()
    assignment(target)
    with (
        patch(
            "apps.support.owner_reconciliation_service.reconcile_ticket",
            return_value=SimpleNamespace(revision=-1),
        ),
        pytest.raises(CapacityObservationConflictError, match="revision changed"),
    ):
        reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    assert AssignedConversation.objects.filter(cycle=target).exists()
    assert not ClosedConversation.objects.exists()


@pytest.mark.parametrize("projection", ["assigned", "pending"])
def test_legacy_close_with_prior_closed_row_materializes_active_projection(settings, projection):
    """An active legacy projection permits another close record."""
    settings.CONVERSATION_CYCLES_ENFORCED = False
    ClosedConversation.objects.create(hubspot_ticket_id="close-ticket", closed_at=T0)
    if projection == "assigned":
        agent = Agent.objects.create(
            hubspot_owner_id=700,
            name="Test",
            agent_email="test@example.test",
            current_simultaneous_chats=1,
        )
        AssignedConversation.objects.create(
            hubspot_ticket_id="close-ticket",
            agent=agent,
            hubspot_owner_id=700,
            assigned_at=T0,
        )
    else:
        NewConversation.objects.create(hubspot_ticket_id="close-ticket", entered_queue_at=T0)
    result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1), allow_legacy=True)
    assert result.classification == CloseClassification.APPLIED_CURRENT
    assert ClosedConversation.objects.filter(hubspot_ticket_id="close-ticket", cycle__isnull=True).count() == 2
    assert not AssignedConversation.objects.filter(hubspot_ticket_id="close-ticket", cycle__isnull=True).exists()
    assert not NewConversation.objects.filter(hubspot_ticket_id="close-ticket", cycle__isnull=True).exists()


def test_legacy_close_with_only_prior_closed_row_is_duplicate(settings):
    """A legacy close without active projection remains duplicate."""
    settings.CONVERSATION_CYCLES_ENFORCED = False
    ClosedConversation.objects.create(hubspot_ticket_id="close-ticket", closed_at=T0)
    result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1), allow_legacy=True)
    assert result.classification == CloseClassification.DUPLICATE
    assert ClosedConversation.objects.filter(hubspot_ticket_id="close-ticket", cycle__isnull=True).count() == 1


def test_cycle_close_with_existing_closed_row_remains_conflict(settings):
    """Cycle-bound close rows retain conflict classification."""
    target = cycle()
    assignment(target)
    ClosedConversation.objects.create(cycle=target, hubspot_ticket_id="close-ticket", closed_at=T0)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    assert result.classification == CloseClassification.CONFLICT
    assert AssignedConversation.objects.filter(cycle=target).exists()
    assert ClosedConversation.objects.filter(cycle=target).count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_postgres_concurrent_close_converges(settings, mode):
    """Concurrent closes produce one durable effect under row locks."""
    from apps.support.owner_reconciliation_service import CapacityObservationConflictError

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")
    settings.SUPPORT_CAPACITY_MODE = mode
    target = cycle()
    agent = assignment(target)
    barrier = Barrier(2)

    def read(_ticket_id):
        assert not connection.in_atomic_block
        barrier.wait(timeout=10)
        return snapshot(settings)

    def close(_index):
        close_old_connections()
        try:
            try:
                return reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
            except CapacityObservationConflictError:
                from apps.support.ticket_close_service import TicketCloseResult

                return TicketCloseResult(CloseClassification.CONFLICT)
        finally:
            close_old_connections()

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = read
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(close, range(2)))
    assert sum(result.classification == CloseClassification.APPLIED_CURRENT for result in results) == 1
    assert all(
        result.classification
        in {
            CloseClassification.APPLIED_CURRENT,
            CloseClassification.DUPLICATE,
            CloseClassification.CONFLICT,
        }
        for result in results
    )
    assert (
        reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1)).classification
        == CloseClassification.DUPLICATE
    )
    assert ClosedConversation.objects.filter(cycle=target).count() == 1
    assert not AssignedConversation.objects.filter(cycle=target).exists()
    agent.refresh_from_db()
    target.refresh_from_db()
    assert agent.current_simultaneous_chats == 0
    assert target.closed_at == T1


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_late_duplicate_does_not_close_reopened_cycle(settings, mode):
    """Late duplicate close preserves the reopened active cycle."""
    from apps.ai_agents.models import ConversationInstance
    from apps.support.models import SupportTicketOccupancy

    settings.SUPPORT_CAPACITY_MODE = mode
    first = cycle(state="closed")
    first.closed_at = T1
    first.save(update_fields=["closed_at"])
    ClosedConversation.objects.create(cycle=first, hubspot_ticket_id="close-ticket", closed_at=T1)
    second = cycle(entered_at=T1 + timedelta(hours=1))
    agent = assignment(second)
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")
    occupancy = SupportTicketOccupancy.objects.create(
        hubspot_ticket_id="close-ticket",
        source_account_id="test-portal",
        cycle=second,
        agent=agent,
        hubspot_owner_id=700,
        state="active",
    )
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    assert result.classification == CloseClassification.DUPLICATE
    provider.assert_not_called()
    second.refresh_from_db()
    agent.refresh_from_db()
    instance.refresh_from_db()
    occupancy.refresh_from_db()
    assert second.state == "assigned"
    assert AssignedConversation.objects.filter(cycle=second).exists()
    assert agent.current_simultaneous_chats == 1
    assert occupancy.state == "active"
    assert occupancy.cycle_id == second.pk
    assert instance.state == "HUMAN_ASSIGNED"


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_reopen_during_provider_read_cannot_release_new_occupancy(settings, mode):
    """Provider read races cannot release reopened occupancy."""
    from apps.ai_agents.models import ConversationInstance
    from apps.support.models import SupportTicketOccupancy

    settings.SUPPORT_CAPACITY_MODE = mode
    first = cycle()
    agent = assignment(first)
    occupancy = SupportTicketOccupancy.objects.create(
        hubspot_ticket_id="close-ticket",
        source_account_id="test-portal",
        cycle=first,
        agent=agent,
        hubspot_owner_id=700,
        state="active",
    )
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")

    def read(_ticket_id):
        first.state = "closed"
        first.closed_at = T1
        first.save(update_fields=["state", "closed_at"])
        ClosedConversation.objects.create(cycle=first, hubspot_ticket_id="close-ticket", closed_at=T1)
        AssignedConversation.objects.filter(cycle=first).delete()
        second = cycle(entered_at=T1 + timedelta(hours=1))
        AssignedConversation.objects.create(
            cycle=second,
            hubspot_ticket_id="close-ticket",
            agent=agent,
            hubspot_owner_id=700,
            assigned_at=second.entered_stage_at,
        )
        occupancy.cycle = second
        occupancy.save(update_fields=["cycle"])
        return snapshot(settings)

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = read
        result = reconcile_close_occurrence(TicketCloseOccurrence("close-ticket", T1))
    assert result.classification == CloseClassification.DUPLICATE
    occupancy.refresh_from_db()
    agent.refresh_from_db()
    instance.refresh_from_db()
    assert occupancy.state == "active"
    assert occupancy.cycle.state == "assigned"
    assert AssignedConversation.objects.filter(cycle=occupancy.cycle).exists()
    assert agent.current_simultaneous_chats == 1
    assert instance.state == "HUMAN_ASSIGNED"

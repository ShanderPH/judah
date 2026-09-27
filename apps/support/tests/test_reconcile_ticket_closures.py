"""Repair command shares live rules and performs no writes without --apply."""

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ai_agents.models import ConversationEvent, ConversationInstance
from apps.support.models import ClosedConversation, SupportConversationCycle
from apps.support.owner_reconciliation_service import CapacityObservationConflictError
from apps.support.tests.test_ticket_close_service import T0, T1, assignment, cycle, snapshot
from apps.support.ticket_close_service import CloseClassification, TicketCloseResult
from common.exceptions import ExternalServiceError, ForbiddenError


def occurrence(settings, suffix="", *, ticket_id="close-ticket"):
    """Persist a calculated close event for command replay."""
    instance = ConversationInstance.objects.create(
        hubspot_ticket_id=ticket_id, state="HUMAN_ASSIGNED", idempotency_key=f"repair-instance{suffix}"
    )
    return ConversationEvent.objects.create(
        instance=instance,
        source="hubspot",
        event_type="ticket_closed",
        idempotency_key=f"repair-close{suffix}",
        source_event_id=f"repair-event{suffix}",
        payload={
            "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
            "propertyValue": str(int(T1.timestamp() * 1000)),
        },
    )


def cycle_at_cutoff():
    """Persist a cycle-era boundary before the test close occurrence."""
    target = cycle()
    SupportConversationCycle.objects.filter(pk=target.pk).update(created_at=T0)
    return target


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_command_defaults_to_read_only_classification(settings, mode):
    """Dry-run classifies every capacity mode without database writes."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = mode
    target = cycle_at_cutoff()
    assignment(target)
    occurrence(settings)
    output = StringIO()
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        with CaptureQueriesContext(connection) as queries:
            call_command("reconcile_ticket_closures", limit=1, stdout=output)
    assert not any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries)
    counts = json.loads(output.getvalue())
    assert counts["scanned"] == counts["applicable_current"] == 1
    assert counts["applied"] == 0
    assert not ClosedConversation.objects.exists()


def test_apply_requires_writer_authority_before_provider_io(settings):
    """Unauthorized apply stops before provider access."""
    occurrence(settings)
    with (
        patch("apps.support.availability_runtime.may_write_routing_state", return_value=False),
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
        pytest.raises(ForbiddenError),
    ):
        call_command("reconcile_ticket_closures", apply=True)
    provider.assert_not_called()


def test_apply_and_repeated_batch_converge(settings):
    """Repeated apply does not create another closed projection."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = "off"
    target = cycle_at_cutoff()
    assignment(target)
    occurrence(settings)
    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = snapshot(settings)
        for expected in (1, 0):
            output = StringIO()
            call_command("reconcile_ticket_closures", apply=True, stdout=output)
            assert json.loads(output.getvalue())["applied"] == expected
    assert ClosedConversation.objects.filter(cycle=target).count() == 1


def test_provider_failure_reports_batch_then_exits_nonzero(settings):
    """Provider failure reports full batch before signaling incomplete work."""
    cycle_at_cutoff()
    event = occurrence(settings)
    event.pk = None
    event.idempotency_key = "repair-close-second"
    event.source_event_id = "repair-event-second"
    event.save(force_insert=True)
    output = StringIO()
    with (
        patch(
            "apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence",
            side_effect=[ExternalServiceError("hubspot"), TicketCloseResult(CloseClassification.DUPLICATE)],
        ) as reconcile,
        pytest.raises(CommandError, match="batch incomplete"),
    ):
        call_command("reconcile_ticket_closures", limit=2, stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["scanned"] == 2
    assert counts["provider_unavailable"] == 1
    assert counts["duplicate"] == 1
    assert reconcile.call_count == 2


def test_legacy_receipts_are_excluded_before_offset_and_preserved(settings):
    """The first page starts after every pre-cycle event, without deleting audit rows."""
    cycle_at_cutoff()
    legacy = occurrence(settings)
    ConversationEvent.objects.filter(pk=legacy.pk).update(created_at=T0 - timedelta(microseconds=1))
    current = occurrence(settings, "-current")
    ConversationEvent.objects.filter(pk=current.pk).update(created_at=T0)
    output = StringIO()
    with patch(
        "apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence",
        return_value=TicketCloseResult(CloseClassification.DUPLICATE),
    ) as reconcile:
        call_command("reconcile_ticket_closures", limit=1, offset=0, stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["legacy_skipped"] == 1
    assert counts["scanned"] == counts["duplicate"] == 1
    assert reconcile.call_args.args[0].source_event_id == "repair-event-current"
    assert ConversationEvent.objects.filter(pk=legacy.pk).exists()


def test_late_legacy_occurrence_cannot_apply(settings):
    """A post-cutoff receipt cannot repair a pre-cutoff effective close."""
    cycle_at_cutoff()
    event = occurrence(settings)
    event.payload["propertyValue"] = str(int((T0 - timedelta(seconds=1)).timestamp() * 1000))
    event.save(update_fields=["payload"])
    output = StringIO()
    with (
        patch("apps.support.management.commands.reconcile_ticket_closures.require_routing_writer_authority"),
        patch("apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence") as reconcile,
    ):
        call_command("reconcile_ticket_closures", apply=True, stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["legacy_skipped"] == 1
    assert counts["scanned"] == 0
    assert counts["applied"] == 0
    reconcile.assert_not_called()
    assert ConversationEvent.objects.filter(pk=event.pk).exists()
    assert not ClosedConversation.objects.exists()


def test_pre_cutoff_receipt_cannot_apply(settings):
    """Even explicit apply never passes a pre-cycle receipt to the repair service."""
    cycle_at_cutoff()
    event = occurrence(settings)
    ConversationEvent.objects.filter(pk=event.pk).update(created_at=T0 - timedelta(microseconds=1))
    output = StringIO()
    with (
        patch("apps.support.management.commands.reconcile_ticket_closures.require_routing_writer_authority"),
        patch("apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence") as reconcile,
    ):
        call_command("reconcile_ticket_closures", apply=True, stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["legacy_skipped"] == 1
    assert counts["scanned"] == counts["applied"] == 0
    reconcile.assert_not_called()
    assert ConversationEvent.objects.filter(pk=event.pk).exists()


def test_apply_pages_only_temporally_resolvable_cycles(settings):
    """Unrelated, future and unresolved cycles cannot consume the page or reach apply."""
    cycle_at_cutoff()
    skipped = [
        occurrence(settings, "-orphan", ticket_id="orphan"),
        occurrence(settings, "-future", ticket_id="future"),
        occurrence(settings, "-unresolved", ticket_id="unresolved"),
    ]
    for ticket_id, entered_at in (("future", T1 + timedelta(hours=1)), ("unresolved", None)):
        SupportConversationCycle.objects.create(
            cycle_key=f"close:{ticket_id}",
            source_account_id="test-portal",
            hubspot_ticket_id=ticket_id,
            entered_stage_at=entered_at,
            opened_at=T0,
            state="assigned",
        )
    first = occurrence(settings, "-first")
    second = occurrence(settings, "-second")
    for position, event in enumerate([*skipped, first, second], start=1):
        ConversationEvent.objects.filter(pk=event.pk).update(created_at=T0 + timedelta(seconds=position))
    output = StringIO()
    with (
        patch("apps.support.management.commands.reconcile_ticket_closures.require_routing_writer_authority"),
        patch(
            "apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence",
            return_value=TicketCloseResult(CloseClassification.DUPLICATE),
        ) as reconcile,
    ):
        call_command("reconcile_ticket_closures", apply=True, limit=1, offset=1, stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["no_cycle"] == 2
    assert counts["identity_unavailable"] == 1
    assert counts["scanned"] == counts["duplicate"] == 1
    assert counts["applied"] == 0
    assert reconcile.call_count == 1
    assert reconcile.call_args.args[0].source_event_id == "repair-event-second"
    assert ConversationEvent.objects.filter(pk__in=[event.pk for event in skipped]).count() == 3


@pytest.mark.parametrize(
    "classification",
    [
        CloseClassification.NO_CYCLE,
        CloseClassification.IDENTITY_UNAVAILABLE,
        CloseClassification.CONFLICT,
        CloseClassification.REOPEN_NOT_MATERIALIZED,
    ],
)
def test_known_rejections_have_separate_counters(settings, classification):
    """Expected rejection causes never collapse into ambiguous."""
    cycle_at_cutoff()
    occurrence(settings)
    output = StringIO()
    with patch(
        "apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence",
        return_value=TicketCloseResult(classification),
    ):
        call_command("reconcile_ticket_closures", stdout=output)
    counts = json.loads(output.getvalue())
    assert counts[classification.value] == 1
    assert counts["ambiguous"] == counts["applied"] == 0


def test_invalid_timestamp_counts_identity_unavailable(settings):
    """Malformed source time is counted as unavailable identity."""
    cycle_at_cutoff()
    event = occurrence(settings)
    event.payload["propertyValue"] = "invalid"
    event.save(update_fields=["payload"])
    output = StringIO()
    call_command("reconcile_ticket_closures", stdout=output)
    assert json.loads(output.getvalue())["identity_unavailable"] == 1


def test_missing_ticket_counts_identity_unavailable(settings):
    """A missing ticket identifier is counted before reaching the repair service."""
    cycle_at_cutoff()
    event = occurrence(settings)
    ConversationInstance.objects.filter(pk=event.instance_id).update(hubspot_ticket_id=None)
    output = StringIO()
    with patch("apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence") as reconcile:
        call_command("reconcile_ticket_closures", stdout=output)
    assert json.loads(output.getvalue())["identity_unavailable"] == 1
    reconcile.assert_not_called()


def test_capacity_conflict_has_separate_counter(settings):
    """A concurrent capacity conflict remains visible in the summary."""
    cycle_at_cutoff()
    occurrence(settings)
    output = StringIO()
    with patch(
        "apps.support.management.commands.reconcile_ticket_closures.reconcile_close_occurrence",
        side_effect=CapacityObservationConflictError("changed"),
    ):
        call_command("reconcile_ticket_closures", stdout=output)
    counts = json.loads(output.getvalue())
    assert counts["conflict"] == 1
    assert counts["ambiguous"] == 0


def test_no_cycle_boundary_fails_closed(settings):
    """No cycle means no provable start date and no repair universe."""
    occurrence(settings)
    with pytest.raises(CommandError, match="cutoff is unavailable"):
        call_command("reconcile_ticket_closures")

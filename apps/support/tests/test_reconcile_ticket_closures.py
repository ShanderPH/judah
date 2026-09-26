"""Repair command shares live rules and performs no writes without --apply."""

import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ai_agents.models import ConversationEvent, ConversationInstance
from apps.support.models import ClosedConversation
from apps.support.tests.test_ticket_close_service import T1, assignment, cycle, snapshot
from apps.support.ticket_close_service import CloseClassification, TicketCloseResult
from common.exceptions import ExternalServiceError, ForbiddenError


def occurrence(settings):
    """Persist a calculated close event for command replay."""
    instance = ConversationInstance.objects.create(hubspot_ticket_id="close-ticket", state="HUMAN_ASSIGNED")
    return ConversationEvent.objects.create(
        instance=instance,
        source="hubspot",
        event_type="ticket_closed",
        idempotency_key="repair-close",
        source_event_id="repair-event",
        payload={
            "propertyName": f"hs_v2_date_entered_{settings.HUBSPOT_SUPPORT_CLOSED_STAGE_ID}",
            "propertyValue": str(int(T1.timestamp() * 1000)),
        },
    )


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_command_defaults_to_read_only_classification(settings, mode):
    """Dry-run classifies every capacity mode without database writes."""
    settings.CONVERSATION_CYCLES_ENFORCED = True
    settings.SUPPORT_CAPACITY_MODE = mode
    target = cycle()
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
    target = cycle()
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

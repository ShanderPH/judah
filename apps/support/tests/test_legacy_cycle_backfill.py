"""Gate E tests for deterministic, restartable legacy cycle backfill."""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.support.legacy_cycle_backfill import backfill_legacy_cycles
from apps.support.models import AssignedConversation, ClosedConversation, SupportConversationCycle

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def portal_id(settings) -> None:
    """Provide the explicit non-secret account identity required by Gate A."""
    settings.HUBSPOT_PORTAL_ID = "test-portal"


def test_backfill_is_idempotent_and_preserves_sequential_closed_cycles() -> None:
    now = timezone.now()
    first = ClosedConversation.objects.create(
        hubspot_ticket_id="ticket-1", entered_queue_at=now - timedelta(days=2), closed_at=now - timedelta(days=1)
    )
    second = ClosedConversation.objects.create(
        hubspot_ticket_id="ticket-1", entered_queue_at=now - timedelta(hours=2), closed_at=now - timedelta(hours=1)
    )

    initial = backfill_legacy_cycles(ticket_id="ticket-1")
    repeated = backfill_legacy_cycles(ticket_id="ticket-1")

    assert initial.created_cycles == 2
    assert initial.linked_rows == 2
    assert repeated.created_cycles == repeated.linked_rows == 0
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="ticket-1").count() == 2
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.cycle_id != second.cycle_id
    assert first.cycle.identity_source == second.cycle.identity_source == "legacy_backfill"


def test_missing_active_timestamp_is_quarantined_without_inventing_identity() -> None:
    AssignedConversation.objects.create(
        hubspot_ticket_id="ticket-2",
        hubspot_owner_id=2,
        agent_name="Legacy Agent",
        assigned_at=timezone.now(),
        entered_queue_at=None,
    )

    report = backfill_legacy_cycles(ticket_id="ticket-2")

    assert report.ambiguous_rows == 1
    assert report.quarantined[0]["reason"] == "missing_queue_entry_timestamp"
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="ticket-2").exists()


def test_command_dry_run_rolls_back_and_emits_checkpoint() -> None:
    ClosedConversation.objects.create(hubspot_ticket_id="ticket-3", closed_at=timezone.now())
    output = StringIO()

    call_command("backfill_conversation_cycles", "--dry-run", "--limit=1", stdout=output)

    payload = json.loads(output.getvalue())
    assert payload["created_cycles"] == 1
    assert payload["next_cursor"] == "ticket-3"
    assert SupportConversationCycle.objects.count() == 0


def test_cursor_and_ticket_filter_bound_the_batch() -> None:
    now = timezone.now()
    ClosedConversation.objects.create(hubspot_ticket_id="a", closed_at=now)
    ClosedConversation.objects.create(hubspot_ticket_id="b", closed_at=now)

    report = backfill_legacy_cycles(after="a", limit=1)

    assert report.scanned_tickets == 1
    assert report.next_cursor == "b"
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="a").exists()


def test_contract_allows_multiple_closed_projections_for_same_ticket() -> None:
    now = timezone.now()
    first = SupportConversationCycle.objects.create(
        cycle_key="legacy:v1:first",
        source_account_id="test-portal",
        hubspot_ticket_id="repeat",
        entered_stage_at=now - timedelta(days=2),
        opened_at=now - timedelta(days=2),
        closed_at=now - timedelta(days=1),
        state="closed",
    )
    second = SupportConversationCycle.objects.create(
        cycle_key="legacy:v1:second",
        source_account_id="test-portal",
        hubspot_ticket_id="repeat",
        entered_stage_at=now - timedelta(hours=2),
        opened_at=now - timedelta(hours=2),
        closed_at=now - timedelta(hours=1),
        state="closed",
    )

    ClosedConversation.objects.create(hubspot_ticket_id="repeat", cycle=first, closed_at=first.closed_at)
    ClosedConversation.objects.create(hubspot_ticket_id="repeat", cycle=second, closed_at=second.closed_at)

    assert ClosedConversation.objects.filter(hubspot_ticket_id="repeat").count() == 2

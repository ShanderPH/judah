"""PostgreSQL regression for observed owner changes without origin evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from unittest.mock import patch

import pytest
from django.db import IntegrityError, connection, transaction
from pytest_django.fixtures import Settings

from apps.support.assignment_provenance import AssignmentProvenance
from apps.support.models import (
    Agent,
    AssignedConversation,
    AssignmentAttempt,
    AssignmentLog,
    ConversationInstanceAttendant,
    ConversationReassignment,
    SupportConversationCycle,
    SupportLifecycleOccurrence,
    SupportTicketOccupancy,
)
from apps.support.owner_reconciliation_service import reconcile_ticket
from apps.support.tasks import task_handle_owner_change

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL required"),
]


def test_migration_replaces_legacy_check_and_reverses_when_safe() -> None:
    """A legacy physical check is widened before canonical values are stored."""
    migration = import_module("apps.support.migrations.0036_assignment_log_provenance_check")
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE assignment_logs DROP CONSTRAINT assignment_logs_assignment_type_check")
        cursor.execute(
            "ALTER TABLE assignment_logs ADD CONSTRAINT assignment_logs_assignment_type_check "
            "CHECK (assignment_type IN ('manual', 'automatic', 'auto'))"
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        AssignmentLog.objects.create(
            ticket_id="before-migration", agent_name="Agent", assignment_type="unknown_external"
        )

    with connection.schema_editor(atomic=False) as schema_editor:
        migration.replace_check(None, schema_editor)
    with connection.schema_editor(atomic=False) as schema_editor:
        migration.restore_legacy_check(None, schema_editor)
    with pytest.raises(IntegrityError), transaction.atomic():
        AssignmentLog.objects.create(ticket_id="after-reverse", agent_name="Agent", assignment_type="unknown_external")
    with connection.schema_editor(atomic=False) as schema_editor:
        migration.replace_check(None, schema_editor)
    AssignmentLog.objects.create(ticket_id="after-migration", agent_name="Agent", assignment_type="unknown_external")
    AssignmentLog.objects.create(ticket_id="historic", agent_name="Agent", assignment_type="auto")


def test_assignment_log_check_accepts_canonical_and_legacy_values() -> None:
    """The physical check must accept every canonical value and historical types."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'assignment_logs'::regclass AND conname = %s",
            ["assignment_logs_assignment_type_check"],
        )
        definition = cursor.fetchone()[0]
    for value in (*AssignmentProvenance, "auto", "automatic", "manual"):
        log = AssignmentLog.objects.create(ticket_id=f"check-{value}", agent_name="Agent", assignment_type=value)
        assert log.assignment_type == value
        assert str(value) in definition
    with pytest.raises(IntegrityError), transaction.atomic():
        AssignmentLog.objects.create(ticket_id="check-invalid", agent_name="Agent", assignment_type="invented")


def test_unknown_owner_effect_converges_without_duplicate_projection(settings: Settings) -> None:
    """Readback, retry and transfer keep one cycle and correct capacity."""
    settings.HUBSPOT_PROVIDER_CONTRACT_MODE = "enforce"
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    first = Agent.objects.create(hubspot_owner_id=801, name="First", agent_email="first@example.test")
    second = Agent.objects.create(hubspot_owner_id=802, name="Second", agent_email="second@example.test")
    snapshot = {
        "id": "unproven-owner-effect",
        "pipeline": settings.HUBSPOT_SUPPORT_PIPELINE_ID,
        "stage": settings.HUBSPOT_SUPPORT_NEW_STAGE_ID,
        "owner_id": "801",
        "entered_novo_at": None,
        "updated_at": "2026-09-01T01:00:00Z",
    }

    pending = reconcile_ticket("unproven-owner-effect", provider_data=snapshot)
    assert pending.state == "active"
    assert pending.cycle_id is None
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id=snapshot["id"]).exists()
    assert not AssignmentLog.objects.filter(ticket_id=snapshot["id"]).exists()

    snapshot["entered_novo_at"] = datetime(2026, 9, 1, tzinfo=UTC)
    snapshot["updated_at"] = "2026-09-01T01:01:00Z"
    occupancy = reconcile_ticket("unproven-owner-effect", provider_data=snapshot)
    cycle = SupportConversationCycle.objects.get(hubspot_ticket_id=snapshot["id"])
    occurrence = SupportLifecycleOccurrence.objects.get(
        hubspot_ticket_id=snapshot["id"],
        occurrence_type=SupportLifecycleOccurrence.Type.ENTERED_SUPPORT_QUEUE,
    )
    log = AssignmentLog.objects.get(ticket_id=snapshot["id"])
    assert occurrence.source_account_id == cycle.source_account_id
    assert occurrence.occurred_at == cycle.entered_stage_at
    assert occurrence.evidence_status == SupportLifecycleOccurrence.EvidenceStatus.PROVEN
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED
    assert cycle.state == SupportConversationCycle.State.ASSIGNED
    assert occupancy.cycle_id == cycle.pk
    assert log.cycle_id == cycle.pk
    assert log.assignment_attempt_id is None
    assert log.assignment_type == AssignmentProvenance.UNKNOWN_EXTERNAL
    assert not AssignmentAttempt.objects.filter(ticket_id=snapshot["id"]).exists()
    assert log.assignment_type == ConversationInstanceAttendant.Source.UNKNOWN_EXTERNAL
    first.refresh_from_db()
    assert first.current_simultaneous_chats == 1

    reconcile_ticket("unproven-owner-effect", provider_data=snapshot)
    snapshot["owner_id"] = "802"
    snapshot["updated_at"] = "2026-09-01T01:02:00Z"
    payload = {
        "eventId": "unproven-owner-event",
        "previousValue": "801",
        "occurredAt": int(datetime(2026, 9, 1, 1, 2, tzinfo=UTC).timestamp() * 1000),
    }
    with (
        patch("apps.support.availability_runtime.may_write_routing_state", return_value=True),
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
    ):
        provider.return_value.get_ticket_details.return_value = snapshot
        task_handle_owner_change("unproven-owner-effect", "802", payload)
        task_handle_owner_change("unproven-owner-effect", "802", payload)
    reconcile_ticket("unproven-owner-effect", provider_data=snapshot)
    transferred = SupportTicketOccupancy.objects.get(hubspot_ticket_id=snapshot["id"])

    assert transferred.cycle_id == cycle.pk
    assert transferred.agent_id == second.pk
    assert SupportTicketOccupancy.objects.filter(hubspot_ticket_id=snapshot["id"]).count() == 1
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id=snapshot["id"]).count() == 1
    assert SupportLifecycleOccurrence.objects.filter(hubspot_ticket_id=snapshot["id"]).count() == 2
    owner_occurrence = SupportLifecycleOccurrence.objects.get(
        hubspot_ticket_id=snapshot["id"], occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED
    )
    assert owner_occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED
    assert AssignedConversation.objects.filter(hubspot_ticket_id=snapshot["id"]).count() == 1
    assert AssignmentLog.objects.filter(ticket_id=snapshot["id"]).count() == 1
    reassignment = ConversationReassignment.objects.get(hubspot_ticket_id=snapshot["id"])
    assert reassignment.cycle_id == cycle.pk
    assert reassignment.reassignment_source == AssignmentProvenance.UNKNOWN_EXTERNAL
    assert reassignment.reassigned_at is None
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.current_simultaneous_chats == 0
    assert second.current_simultaneous_chats == 1

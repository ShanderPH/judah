"""Regressions for bounded recovery of proven queue-entry occurrences."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone
from pytest_django.fixtures import Settings

from apps.support.conversation_cycle_service import open_or_get_cycle
from apps.support.lifecycle_occurrence_service import (
    mark_processed,
    open_from_proven_occurrence,
    record_proven_occurrence,
)
from apps.support.models import SupportConversationCycle, SupportLifecycleOccurrence
from apps.support.tasks import task_reconcile_lifecycle_occurrence, task_scan_lifecycle_occurrences


def record_entry(ticket_id: str = "entry-recovery") -> SupportLifecycleOccurrence:
    """Persist provider-proven entry evidence without projecting its cycle."""
    return record_proven_occurrence(
        account_id="test-portal",
        ticket_id=ticket_id,
        occurrence_type=SupportLifecycleOccurrence.Type.ENTERED_SUPPORT_QUEUE,
        occurred_at=datetime(2026, 9, 30, 14, 30, tzinfo=UTC),
        evidence_source="webhook_property",
        source_event_id="entry-event",
    )


def test_terminal_entry_is_not_projected_by_an_earlier_execution(settings: Settings) -> None:
    """Preserve a terminal decision committed between claim and projection."""
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_ATTEMPTS = 1
    occurrence = record_entry("entry-overlap")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
    select_for_update = SupportLifecycleOccurrence.objects.select_for_update
    lock_count = 0

    def exhaust_before_lock():
        """Interleave the competing due task before the next lock acquisition."""
        nonlocal lock_count
        lock_count += 1
        if lock_count == 2:
            SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
            assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "repair_required"
        return select_for_update()

    with patch.object(SupportLifecycleOccurrence.objects, "select_for_update", side_effect=exhaust_before_lock):
        result = task_reconcile_lifecycle_occurrence.run(str(occurrence.pk))

    occurrence.refresh_from_db()
    assert result == "repair_required"
    assert occurrence.processing_status == "repair_required"
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-overlap").exists()


def test_mark_processed_never_overwrites_a_terminal_repair_decision() -> None:
    """A delayed acknowledgement cannot reset a terminal occurrence."""
    occurrence = record_entry("entry-terminal")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(
        processing_status="repair_required", next_reconcile_at=None
    )
    mark_processed(occurrence.pk)
    occurrence.refresh_from_db()
    assert occurrence.processing_status == "repair_required"


@pytest.mark.django_db(transaction=True)
def test_overlapping_postgres_entry_tasks_serialize_projection(settings: Settings) -> None:
    """A competing due task waits for projection and observes its committed result."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_ATTEMPTS = 1
    occurrence = record_entry("entry-postgres-overlap")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
    projection_started, release_projection, second_connected = Event(), Event(), Event()
    second_pids: list[int] = []

    def pause_projection(**kwargs):
        """Pause at the guarded writer boundary while a second connection arrives."""
        projection_started.set()
        assert release_projection.wait(timeout=10)
        return open_from_proven_occurrence(**kwargs)

    def reconcile(second: bool) -> str:
        close_old_connections()
        try:
            if second:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    second_pids.append(cursor.fetchone()[0])
                second_connected.set()
            return task_reconcile_lifecycle_occurrence.run(str(occurrence.pk))
        finally:
            close_old_connections()

    blocked = False
    with (
        patch("apps.support.lifecycle_occurrence_service.open_from_proven_occurrence", side_effect=pause_projection),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(reconcile, False)
        try:
            assert projection_started.wait(timeout=10)
            with patch("apps.support.tasks.timezone.now", return_value=timezone.now() + timedelta(minutes=1)):
                second = pool.submit(reconcile, True)
                assert second_connected.wait(timeout=10)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not second.done():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [second_pids[0]])
                        blocked = cursor.fetchone()[0] > 0
                    if blocked:
                        break
                    time.sleep(0.01)
                release_projection.set()
                results = (first.result(timeout=10), second.result(timeout=10))
        finally:
            release_projection.set()

    assert blocked, "The occurrence lock must cover eligibility and projection"
    assert results == ("processed", "processed")
    occurrence.refresh_from_db()
    assert occurrence.processing_status == "processed"
    assert occurrence.retry_count == 1
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-postgres-overlap").count() == 1


def test_proven_entry_is_scheduled_without_resetting_duplicate_budget() -> None:
    """A repeated delivery must preserve the original schedule and retry count."""
    occurrence = record_entry()
    assert occurrence.next_reconcile_at is not None
    assert occurrence.next_reconcile_at > timezone.now()
    scheduled_at = occurrence.next_reconcile_at
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(retry_count=2)

    duplicate = record_entry()

    assert duplicate.pk == occurrence.pk
    assert duplicate.next_reconcile_at == scheduled_at
    assert duplicate.retry_count == 2


def test_entry_retry_opens_its_proven_cycle_once_without_close_projection() -> None:
    """Entry retries must materialize one cycle using the persisted identity."""
    occurrence = record_entry()
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
        patch("apps.support.ticket_close_service.reconcile_close_occurrence") as close,
    ):
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "processed"
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "processed"

    provider.assert_not_called()
    close.assert_not_called()
    occurrence.refresh_from_db()
    cycle = SupportConversationCycle.objects.get(hubspot_ticket_id=occurrence.hubspot_ticket_id)
    assert cycle.source_account_id == occurrence.source_account_id
    assert cycle.entered_stage_at == occurrence.occurred_at
    assert cycle.source_event_id == occurrence.source_event_id
    assert cycle.state == SupportConversationCycle.State.QUEUED
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED
    assert occurrence.next_reconcile_at is None
    assert occurrence.retry_count == 1


def test_conflicting_entry_retries_after_prior_cycle_closes() -> None:
    """A blocked reopen must wait for closure without closing the prior cycle."""
    prior_time = datetime(2026, 9, 30, 13, tzinfo=UTC)
    prior = open_or_get_cycle(
        hubspot_ticket_id="entry-conflict", entered_stage_value=prior_time, source_account_id="test-portal"
    ).cycle
    assert prior is not None
    entered_at = datetime(2026, 9, 30, 14, 30, tzinfo=UTC)
    result = open_from_proven_occurrence(
        ticket_id="entry-conflict",
        entered_at=entered_at,
        account_id="test-portal",
        evidence_source="webhook_property",
        source_event_id="entry-event",
    )
    assert result.admission.classification == "active_conflict"
    occurrence = SupportLifecycleOccurrence.objects.get(hubspot_ticket_id="entry-conflict")
    assert occurrence.next_reconcile_at is not None
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=timezone.now())
    with patch("apps.support.ticket_close_service.reconcile_close_occurrence") as close:
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "pending"
    close.assert_not_called()
    occurrence.refresh_from_db()
    prior.refresh_from_db()
    assert occurrence.last_error_code == "active_conflict"
    assert occurrence.next_reconcile_at > timezone.now()
    assert prior.state == SupportConversationCycle.State.QUEUED
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-conflict").count() == 1

    SupportConversationCycle.objects.filter(pk=prior.pk).update(
        state=SupportConversationCycle.State.CLOSED, closed_at=entered_at - timedelta(minutes=1)
    )
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=timezone.now())
    assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "processed"
    occurrence.refresh_from_db()
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-conflict").count() == 2


def test_retry_acknowledges_an_already_materialized_entry_without_duplicate() -> None:
    """Recovery must acknowledge a cycle whose occurrence was not marked processed."""
    occurrence = record_entry("entry-duplicate")
    cycle = open_or_get_cycle(
        hubspot_ticket_id=occurrence.hubspot_ticket_id,
        entered_stage_value=occurrence.occurred_at,
        source_account_id=occurrence.source_account_id,
    ).cycle
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)

    assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "processed"

    assert SupportConversationCycle.objects.get(hubspot_ticket_id="entry-duplicate") == cycle
    occurrence.refresh_from_db()
    assert occurrence.processing_status == SupportLifecycleOccurrence.ProcessingStatus.PROCESSED


def test_stale_entry_exhausts_budget_without_changing_newer_cycle(settings) -> None:
    """Older entry evidence must require repair rather than mutate a newer cycle."""
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_ATTEMPTS = 1
    occurrence = record_entry("entry-stale")
    newer = open_or_get_cycle(
        hubspot_ticket_id="entry-stale",
        entered_stage_value=occurrence.occurred_at + timedelta(hours=1),
        source_account_id="test-portal",
    ).cycle
    assert newer is not None
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=None)
    with patch("apps.support.ticket_close_service.reconcile_close_occurrence") as close:
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "repair_required"
    close.assert_not_called()
    occurrence.refresh_from_db()
    newer.refresh_from_db()
    assert occurrence.last_error_code == "stale"
    assert occurrence.evidence_status == SupportLifecycleOccurrence.EvidenceStatus.PROVEN
    assert occurrence.next_reconcile_at is None
    assert newer.state == SupportConversationCycle.State.QUEUED
    assert SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-stale").count() == 1


def test_entry_without_proven_time_never_uses_close_readback() -> None:
    """Unproven entry evidence must not be interpreted as a pending close."""
    occurrence = record_entry("entry-unproven")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(
        occurred_at=None,
        evidence_status=SupportLifecycleOccurrence.EvidenceStatus.AMBIGUOUS,
        next_reconcile_at=None,
    )
    with (
        patch("apps.integrations.hubspot.client.get_hubspot_client") as provider,
        patch("apps.support.ticket_close_service.reconcile_close_occurrence") as close,
    ):
        assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "pending"
    provider.assert_not_called()
    close.assert_not_called()
    occurrence.refresh_from_db()
    assert occurrence.last_error_code == "entry_evidence_unproven"
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-unproven").exists()


def test_expired_unscheduled_entry_requires_repair_without_projecting(settings) -> None:
    """The scanner fallback must not replay entries past the live age budget."""
    settings.SUPPORT_LIFECYCLE_RECONCILE_MAX_AGE_SECONDS = 60
    occurrence = record_entry("entry-expired")
    SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(
        created_at=timezone.now() - timedelta(minutes=2), next_reconcile_at=None
    )
    assert task_reconcile_lifecycle_occurrence.run(str(occurrence.pk)) == "repair_required"
    occurrence.refresh_from_db()
    assert occurrence.last_error_code == "reconcile_budget_exhausted"
    assert occurrence.evidence_status == SupportLifecycleOccurrence.EvidenceStatus.PROVEN
    assert occurrence.retry_count == 0
    assert not SupportConversationCycle.objects.filter(hubspot_ticket_id="entry-expired").exists()


@pytest.mark.parametrize("status", ["processed", "repair_required", "future"])
def test_scan_recovers_unscheduled_entry_and_excludes_terminal_or_future(status: str) -> None:
    """Only due pending entries may join the fallback recovery batch."""
    pending = record_entry("entry-scan")
    excluded = record_entry("entry-excluded")
    SupportLifecycleOccurrence.objects.filter(pk=pending.pk).update(next_reconcile_at=None)
    if status == "future":
        SupportLifecycleOccurrence.objects.filter(pk=excluded.pk).update(
            next_reconcile_at=timezone.now() + timedelta(minutes=5)
        )
    else:
        SupportLifecycleOccurrence.objects.filter(pk=excluded.pk).update(
            processing_status=status, next_reconcile_at=None
        )
    with patch("apps.support.tasks.task_reconcile_lifecycle_occurrence.delay") as dispatch:
        assert task_scan_lifecycle_occurrences.run() == 1
    dispatch.assert_called_once_with(str(pending.pk))


def test_scan_keeps_the_hundred_occurrence_batch_limit() -> None:
    """Entry recovery must preserve the scanner's bounded batch size."""
    now = timezone.now()
    for index in range(101):
        occurrence = record_entry(f"entry-batch-{index}")
        SupportLifecycleOccurrence.objects.filter(pk=occurrence.pk).update(next_reconcile_at=now)
    with patch("apps.support.tasks.task_reconcile_lifecycle_occurrence.delay") as dispatch:
        assert task_scan_lifecycle_occurrences.run() == 100
    assert dispatch.call_count == 100


def test_scan_keeps_unscheduled_owner_evidence_out_of_entry_recovery() -> None:
    """The new fallback must leave unscheduled owner observations unchanged."""
    occurrence = record_proven_occurrence(
        account_id="test-portal",
        ticket_id="owner-unscheduled",
        occurrence_type=SupportLifecycleOccurrence.Type.OWNER_CHANGED,
        occurred_at=datetime(2026, 9, 30, 14, 30, tzinfo=UTC),
        evidence_source="webhook_property",
    )
    assert occurrence.next_reconcile_at is None
    with patch("apps.support.tasks.task_reconcile_lifecycle_occurrence.delay") as dispatch:
        assert task_scan_lifecycle_occurrences.run() == 0
    dispatch.assert_not_called()

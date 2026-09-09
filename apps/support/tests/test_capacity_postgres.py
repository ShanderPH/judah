"""Real PostgreSQL contention and reversible schema gates for capacity."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.support.capacity_service import capacity_count
from apps.support.durable_assignment_service import compensate_assignment_attempt, reserve_next_assignment
from apps.support.models import Agent, AgentCapacityReservation, SupportTicketOccupancy
from apps.support.owner_reconciliation_service import CapacityObservationConflictError, reconcile_ticket
from apps.support.tests.test_manual_assignment_capacity import agent, queue, ready, ticket

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def postgres_mode(settings):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")
    settings.SUPPORT_CAPACITY_MODE = "enforce"
    settings.HUBSPOT_PORTAL_ID = "test-portal"
    settings.ABSENCE_SAFE_ELIGIBILITY_ENFORCED = False


def test_last_slot_has_one_held_reservation():
    target = agent(200)
    target.max_simultaneous_chats = 1
    target.save()
    ready(target)
    queue("one")
    queue("two")
    barrier = Barrier(2)

    def reserve(identity: str):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return reserve_next_assignment(identity).attempt
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["one", "two"]))
    assert sum(result is not None for result in results) == 1
    assert AgentCapacityReservation.objects.filter(state="held").count() == 1
    target.refresh_from_db()
    assert target.current_simultaneous_chats == capacity_count(target.pk) == 1


def test_first_observation_race_rejects_losing_snapshot():
    target = agent(200)
    barrier = Barrier(2)

    def read(identity: str):
        assert not connection.in_atomic_block
        barrier.wait(timeout=10)
        return ticket(200, identity)

    def observe(_index: int):
        close_old_connections()
        try:
            try:
                reconcile_ticket("first")
                return "applied"
            except CapacityObservationConflictError:
                return "conflict"
        finally:
            close_old_connections()

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = read
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(observe, range(2)))
    assert sorted(outcomes) == ["applied", "conflict"]
    assert SupportTicketOccupancy.objects.count() == 1
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1


def test_compensation_contention_does_not_double_release():
    target = agent(200)
    ready(target)
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None
    barrier = Barrier(2)

    def release(_index: int):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            compensate_assignment_attempt(attempt.pk, retryable=False, error_code="pre_effect_rejected")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(release, range(2)))
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 0
    assert AgentCapacityReservation.objects.get().state == "released"


def test_reverse_forward_schema_and_runtime_guards():
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    executor.migrate([("support", "0030_opening_assignment_cohort")])
    assert "support_ticket_occupancies" not in connection.introspection.table_names()
    try:
        MigrationExecutor(connection).migrate([("support", "0031_ticket_capacity")])
        with connection.cursor() as cursor:
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'support_ticket_occupancies'")
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                "('trg_guard_support_ticket_occupancies_runtime', 'trg_guard_agent_capacity_reservations_runtime')"
            )
            assert cursor.fetchone() == (2,)
    finally:
        MigrationExecutor(connection).migrate([("support", "0031_ticket_capacity")])


def test_scan_generation_cannot_overwrite_concurrent_reservation():
    from apps.support.owner_reconciliation_service import refresh_agent_capacity

    target = agent(200)
    ready(target)
    queue()
    Agent.objects.filter(pk=target.pk).update(capacity_reconciled_at=timezone.now())

    def discovery(_owner):
        assert not connection.in_atomic_block
        # Provider callback represents a second decision during the scan.
        assert reserve_next_assignment("cap-1").attempt is not None
        return (), True

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.list_active_ticket_ids_by_owner.side_effect = discovery
        assert not refresh_agent_capacity(target, force=True)
    target.refresh_from_db()
    assert target.current_simultaneous_chats == 1
    assert target.capacity_state == "degraded"


def test_capacity_query_plan_on_representative_local_rows():
    """Exercise the actual indexed projection with 2,000 local ticket rows."""
    import json
    import time

    target = agent(200)
    SupportTicketOccupancy.objects.bulk_create(
        [
            SupportTicketOccupancy(
                source_account_id="test-portal",
                hubspot_ticket_id=f"perf-{index}",
                agent=target if index < 5 else None,
                hubspot_owner_id=200 if index < 5 else 999,
                state="active",
            )
            for index in range(2000)
        ]
    )
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE support_ticket_occupancies")
    started = time.perf_counter()
    assert capacity_count(target.pk) == 5
    elapsed = time.perf_counter() - started
    plan = json.loads(SupportTicketOccupancy.objects.filter(agent=target, state="active").explain(format="json"))
    assert elapsed < 2
    assert "Index" in json.dumps(plan) or "Bitmap" in json.dumps(plan)


def test_manual_webhook_wins_during_auto_precondition_read():
    from threading import Event, current_thread

    from apps.support.durable_assignment_service import execute_assignment_attempt
    from apps.support.tasks import task_handle_owner_change

    automatic, manual = agent(100), agent(200)
    ready(automatic)
    ready(manual)
    Agent.objects.filter(pk=manual.pk).update(last_assignment_at=timezone.now())
    queue()
    attempt = reserve_next_assignment("cap-1").attempt
    assert attempt is not None and attempt.selected_agent == automatic
    reading, delivered = Event(), Event()
    old = ticket("")

    def read(identity: str):
        assert not connection.in_atomic_block
        if current_thread().name != "MainThread":
            reading.set()
            assert delivered.wait(timeout=10)
            return old
        return ticket(200, identity)

    def execute():
        close_old_connections()
        try:
            return execute_assignment_attempt(attempt.pk)
        finally:
            close_old_connections()

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.side_effect = read
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            try:
                assert reading.wait(timeout=10)
                task_handle_owner_change("cap-1", "200", {})
            finally:
                delivered.set()
            assert future.result(timeout=10) == "retryable_external_error"
        provider.return_value.assign_ticket_owner.assert_not_called()
    automatic.refresh_from_db()
    manual.refresh_from_db()
    assert (automatic.current_simultaneous_chats, manual.current_simultaneous_chats) == (0, 1)


def test_admin_and_webhook_threads_converge_one_transfer():
    from threading import Event

    from apps.support.admin_api import _force_reassign_internal
    from apps.support.models import AssignedConversation, ConversationReassignment
    from apps.support.tasks import task_handle_owner_change

    source, target = agent(100), agent(200)
    ready(target)
    AssignedConversation.objects.create(
        hubspot_ticket_id="cap-1",
        agent=source,
        hubspot_owner_id=100,
        assigned_at=timezone.now(),
        entered_queue_at=timezone.now(),
    )
    applied, delivered = Event(), Event()

    with patch("apps.integrations.hubspot.client.get_hubspot_client") as provider:
        provider.return_value.get_ticket_details.return_value = ticket(100)

        def apply(*args):
            assert not connection.in_atomic_block
            provider.return_value.get_ticket_details.return_value = ticket(200)
            applied.set()
            assert delivered.wait(timeout=10)

        provider.return_value.assign_ticket_owner.side_effect = apply

        def transfer():
            close_old_connections()
            try:
                return _force_reassign_internal("cap-1", target)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(transfer)
            try:
                assert applied.wait(timeout=10)
                task_handle_owner_change("cap-1", "200", {})
            finally:
                delivered.set()
            assert future.result(timeout=10)["success"]
    source.refresh_from_db()
    target.refresh_from_db()
    assert (source.current_simultaneous_chats, target.current_simultaneous_chats) == (0, 1)
    assert ConversationReassignment.objects.count() == 1

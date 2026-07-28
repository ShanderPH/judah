"""PostgreSQL contract tests for the queue-status CHECK constraint."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION_BEFORE = ("support", "0023_cycle_backfill_contract")
MIGRATION_AFTER = ("support", "0024_repair_queue_status_constraint")
CONSTRAINT = "new_conversations_queue_status_check"


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete migration graph after historical assertions."""
    if connection.vendor != "postgresql":
        pytest.skip("Queue-status schema contract requires PostgreSQL.")
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _constraint_definition() -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'new_conversations'::regclass AND conname = %s",
            [CONSTRAINT],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_forward_reverse_reapply_and_fail_closed_rollback(restore_migrations: None) -> None:
    executor = _migrate(MIGRATION_BEFORE)
    before_apps = executor.loader.project_state([MIGRATION_BEFORE]).apps
    queue_model = before_apps.get_model("support", "NewConversation")
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE new_conversations DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
        cursor.execute(
            f"ALTER TABLE new_conversations ADD CONSTRAINT {CONSTRAINT} CHECK (queue_status IN ('pending', 'queued'))"
        )

    executor = _migrate(MIGRATION_AFTER)
    definition = _constraint_definition()
    assert all(f"'{value}'" in definition for value in ("pending", "queued", "failed"))

    queue_model = executor.loader.project_state([MIGRATION_AFTER]).apps.get_model("support", "NewConversation")
    entered_queue_at = timezone.now()
    failed = queue_model.objects.create(
        hubspot_ticket_id="failed-contract",
        queue_status="failed",
        entered_queue_at=entered_queue_at,
    )
    with pytest.raises(IntegrityError):
        queue_model.objects.create(
            hubspot_ticket_id="invalid-contract",
            queue_status="invalid",
            entered_queue_at=entered_queue_at,
        )

    with pytest.raises(RuntimeError, match="quarantined rows exist"):
        _migrate(MIGRATION_BEFORE)

    failed.delete()
    _migrate(MIGRATION_BEFORE)
    definition = _constraint_definition()
    assert "'failed'" not in definition

    _migrate(MIGRATION_AFTER)
    definition = _constraint_definition()
    assert all(f"'{value}'" in definition for value in ("pending", "queued", "failed"))

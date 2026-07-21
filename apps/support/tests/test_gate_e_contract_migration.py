"""PostgreSQL verification for the Gate E contract migration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION_BEFORE = ("support", "0022_closed_conversation_multi_cycle")
MIGRATION_AFTER = ("support", "0023_cycle_backfill_contract")


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete graph after historical migration assertions."""
    if connection.vendor != "postgresql":
        pytest.skip("Gate E contract migration tests require PostgreSQL.")
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


def _constraints(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = %s
            UNION
            SELECT indexname FROM pg_indexes WHERE tablename = %s
            """,
            [table, table],
        )
        return {row[0] for row in cursor.fetchall()}


def test_contract_apply_reverse_reapply_and_unsafe_rollback_guard(restore_migrations: None) -> None:
    executor = _migrate(MIGRATION_BEFORE)
    before_apps = executor.loader.project_state([MIGRATION_BEFORE]).apps
    cycle_model = before_apps.get_model("support", "SupportConversationCycle")
    assert not hasattr(cycle_model, "identity_source")
    assert "uniq_completed_assignment_ticket" in _constraints("assignment_attempts")

    executor = _migrate(MIGRATION_AFTER)
    after_apps = executor.loader.project_state([MIGRATION_AFTER]).apps
    cycle_model = after_apps.get_model("support", "SupportConversationCycle")
    assert hasattr(cycle_model, "identity_source")
    assert "uniq_completed_assignment_ticket" not in _constraints("assignment_attempts")

    # A clean rollback remains possible before multi-cycle rows exist.
    executor = _migrate(MIGRATION_BEFORE)
    assert "uniq_completed_assignment_ticket" in _constraints("assignment_attempts")

    executor = _migrate(MIGRATION_AFTER)
    after_apps = executor.loader.project_state([MIGRATION_AFTER]).apps
    cycle_model = after_apps.get_model("support", "SupportConversationCycle")
    queue_model = after_apps.get_model("support", "NewConversation")
    entered = datetime(2026, 7, 1, 12, tzinfo=UTC)
    first = cycle_model.objects.create(
        cycle_key="legacy:v1:migration-first",
        source_account_id="test-portal",
        hubspot_ticket_id="repeat-ticket",
        entered_stage_at=entered,
        opened_at=entered,
        state="closed",
    )
    second = cycle_model.objects.create(
        cycle_key="legacy:v1:migration-second",
        source_account_id="test-portal",
        hubspot_ticket_id="repeat-ticket",
        entered_stage_at=entered + timedelta(days=1),
        opened_at=entered + timedelta(days=1),
        state="closed",
    )
    queue_model.objects.create(hubspot_ticket_id="repeat-ticket", entered_queue_at=entered, cycle=first)
    queue_model.objects.create(
        hubspot_ticket_id="repeat-ticket", entered_queue_at=entered + timedelta(days=1), cycle=second
    )

    with pytest.raises(IrreversibleError, match="ticket-wide uniqueness"):
        _migrate(MIGRATION_BEFORE)

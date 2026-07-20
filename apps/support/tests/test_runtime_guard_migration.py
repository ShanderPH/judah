"""PostgreSQL integration tests for the routing writer guard migration."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION_BEFORE_GUARDS = ("support", "0014_newconversation_failure_tracking")
MIGRATION_WITH_GUARDS = ("support", "0016_block_non_authoritative_runtime_writes")
EXPECTED_TRIGGERS = {
    "trg_guard_agent_routing_state",
    "trg_guard_new_conversations_runtime",
    "trg_guard_assigned_conversations_runtime",
    "trg_guard_assignment_logs_runtime",
    "trg_guard_agent_availability_decisions_runtime",
    "trg_guard_availability_reconciliation_leases_runtime",
}


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete migration graph after exercising historical states."""
    if connection.vendor != "postgresql":
        pytest.skip("Runtime guard migration requires PostgreSQL.")

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


def _set_application_name(value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('application_name', %s, false)", [value])


def _installed_guard_triggers() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trigger_name
            FROM information_schema.triggers
            WHERE trigger_name LIKE 'trg_guard_%'
            """
        )
        return {row[0] for row in cursor.fetchall()}


def _guard_function_exists() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_proc
                WHERE proname = 'judah_reject_non_authoritative_runtime'
            )
            """
        )
        return bool(cursor.fetchone()[0])


def test_runtime_guards_apply_reverse_reapply_and_enforce(
    restore_migrations: None,
) -> None:
    _migrate(MIGRATION_BEFORE_GUARDS)
    assert not _guard_function_exists()
    assert EXPECTED_TRIGGERS.isdisjoint(_installed_guard_triggers())

    migration_executor = _migrate(MIGRATION_WITH_GUARDS)
    migrated_apps = migration_executor.loader.project_state([MIGRATION_WITH_GUARDS]).apps
    Agent = migrated_apps.get_model("support", "Agent")

    assert _guard_function_exists()
    assert _installed_guard_triggers() >= EXPECTED_TRIGGERS

    _set_application_name("judah:production:pytest")
    agent = Agent.objects.create(
        name="Migration Guard Agent",
        agent_email="migration-guard@example.test",
        hubspot_owner_id=991001,
        status_enum="away",
    )
    assert Agent.objects.filter(pk=agent.pk).update(status_enum="online") == 1

    _set_application_name("judah:staging:pytest")
    with pytest.raises(DatabaseError, match="non-authoritative JUDAH runtime"), transaction.atomic():
        Agent.objects.filter(pk=agent.pk).update(status_enum="away")
    assert Agent.objects.get(pk=agent.pk).status_enum == "online"

    _set_application_name("judah:production:pytest")
    _migrate(MIGRATION_BEFORE_GUARDS)
    assert not _guard_function_exists()
    assert EXPECTED_TRIGGERS.isdisjoint(_installed_guard_triggers())

    _migrate(MIGRATION_WITH_GUARDS)
    assert _guard_function_exists()
    assert _installed_guard_triggers() >= EXPECTED_TRIGGERS

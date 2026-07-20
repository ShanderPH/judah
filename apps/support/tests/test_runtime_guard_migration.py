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
    "trg_guard_agent_status_history_runtime",
    "trg_guard_agent_availability_decisions_runtime",
    "trg_guard_availability_reconciliation_leases_runtime",
    "trg_guard_conversation_reassignments_runtime",
}
TEST_ROLES = (
    "judah_production_runtime",
    "judah_schema_migration",
    "judah_break_glass",
    "judah_untrusted_client",
)


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


def _ensure_test_roles() -> None:
    with connection.cursor() as cursor:
        for role in TEST_ROLES:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", [role])
            if not cursor.fetchone()[0]:
                cursor.execute(f"CREATE ROLE {connection.ops.quote_name(role)} NOLOGIN")
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f"TO {connection.ops.quote_name(role)}"
            )
            cursor.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {connection.ops.quote_name(role)}"
            )


def _set_role(role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {connection.ops.quote_name(role)}")


def _reset_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


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

    _ensure_test_roles()
    _set_application_name("judah:production:pytest")
    try:
        _set_role("judah_production_runtime")
        agent = Agent.objects.create(
            name="Migration Guard Agent",
            agent_email="migration-guard@example.test",
            hubspot_owner_id=991001,
            status_enum="away",
        )
        assert Agent.objects.filter(pk=agent.pk).update(status_enum="online") == 1
        _reset_role()

        _set_role("judah_untrusted_client")
        _set_application_name("judah:production:forged-client")
        with pytest.raises(DatabaseError, match="untrusted JUDAH database role"), transaction.atomic():
            Agent.objects.filter(pk=agent.pk).update(status_enum="away")
        _reset_role()
        assert Agent.objects.get(pk=agent.pk).status_enum == "online"

        _set_role("judah_schema_migration")
        _set_application_name("judah:production:schema-migration")
        assert Agent.objects.filter(pk=agent.pk).update(status_enum="away") == 1
        _reset_role()

        _set_role("judah_break_glass")
        _set_application_name("judah:production:break-glass")
        assert Agent.objects.filter(pk=agent.pk).delete()[0] == 1
        _reset_role()
    finally:
        _reset_role()

    _set_application_name("judah:local-test:pytest")
    _migrate(MIGRATION_BEFORE_GUARDS)
    assert not _guard_function_exists()
    assert EXPECTED_TRIGGERS.isdisjoint(_installed_guard_triggers())

    _migrate(MIGRATION_WITH_GUARDS)
    assert _guard_function_exists()
    assert _installed_guard_triggers() >= EXPECTED_TRIGGERS
    _set_application_name("judah:local-test:pytest")

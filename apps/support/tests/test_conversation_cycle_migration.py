"""PostgreSQL integration tests for the conversation-cycle expand migration.

Proves apply/reverse/reapply of ``support.0020`` from ``support.0019`` on a
disposable PostgreSQL 16 database: schema objects, writer-guard trigger,
preservation of legacy data, and removal of only Gate B objects on reverse.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION_BEFORE = ("support", "0019_fix_agent_assignment_timestamp_timezone")
MIGRATION_AFTER = ("support", "0020_conversation_cycles_expand")
CYCLE_TABLE = "support_conversation_cycles"
CYCLE_TRIGGER = "trg_guard_support_conversation_cycles_runtime"
CYCLE_INDEXES = {
    "idx_cycle_ticket_opened",
    "idx_cycle_state_opened",
    "uniq_conv_cycle_natural_key",
    "uniq_active_conv_cycle_ticket",
}
LEGACY_GUARD_TRIGGERS = {
    "trg_guard_agent_routing_state",
    "trg_guard_new_conversations_runtime",
    "trg_guard_assigned_conversations_runtime",
    "trg_guard_assignment_logs_runtime",
}
LEGACY_CONSTRAINTS = {
    "uniq_live_assignment_attempt_ticket",
    "uniq_completed_assignment_ticket",
}
TEST_ROLES = (
    "judah_production_runtime",
    "judah_untrusted_client",
)


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete migration graph after exercising historical states."""
    if connection.vendor != "postgresql":
        pytest.skip("Conversation-cycle migration tests require PostgreSQL.")

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


def _set_role(role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {connection.ops.quote_name(role)}")


def _reset_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


def _table_exists(table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
            [table],
        )
        return bool(cursor.fetchone()[0])


def _table_columns(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


def _installed_indexes(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", [table])
        return {row[0] for row in cursor.fetchall()}


def _installed_constraints(table: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = %s
            """,
            [table],
        )
        return {row[0] for row in cursor.fetchall()}


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


def _create_legacy_rows(apps) -> dict[str, object]:
    """Persist one row in each operational table using the 0019 schema."""
    Agent = apps.get_model("support", "Agent")
    NewConversation = apps.get_model("support", "NewConversation")
    AssignedConversation = apps.get_model("support", "AssignedConversation")
    AssignmentAttempt = apps.get_model("support", "AssignmentAttempt")
    AssignmentLog = apps.get_model("support", "AssignmentLog")
    ClosedConversation = apps.get_model("support", "ClosedConversation")
    ConversationReassignment = apps.get_model("support", "ConversationReassignment")

    now = timezone.now()
    agent = Agent.objects.create(
        name="Cycle Migration Agent",
        agent_email="cycle-migration@example.test",
        hubspot_owner_id=991002,
        status_enum="online",
        is_active=True,
    )
    queue_row = NewConversation.objects.create(hubspot_ticket_id="8801", entered_queue_at=now)
    assigned = AssignedConversation.objects.create(
        hubspot_ticket_id="8802",
        hubspot_owner_id=agent.hubspot_owner_id,
        agent_name=agent.name,
        assigned_at=now,
    )
    attempt = AssignmentAttempt.objects.create(
        idempotency_key=uuid.uuid4(),
        ticket_id="8802",
        selected_agent=agent,
        eligibility_revision=1,
        desired_hubspot_owner_id=agent.hubspot_owner_id,
        decision_reason="eligible",
        state="completed",
        reserved_at=now,
    )
    log = AssignmentLog.objects.create(ticket_id="8802", agent_name=agent.name, assignment_attempt=attempt)
    closed = ClosedConversation.objects.create(hubspot_ticket_id="8803", closed_at=now)
    reassignment = ConversationReassignment.objects.create(hubspot_ticket_id="8802", reassigned_at=now)
    return {
        "agent": agent.pk,
        "queue_row": queue_row.pk,
        "assigned": assigned.pk,
        "attempt": attempt.pk,
        "log": log.pk,
        "closed": closed.pk,
        "reassignment": reassignment.pk,
    }


def _assert_legacy_rows_intact(apps, ids: dict[str, object], *, expect_cycle_column: bool) -> None:
    for model_name, key in (
        ("NewConversation", "queue_row"),
        ("AssignedConversation", "assigned"),
        ("AssignmentAttempt", "attempt"),
        ("AssignmentLog", "log"),
        ("ClosedConversation", "closed"),
        ("ConversationReassignment", "reassignment"),
    ):
        row = apps.get_model("support", model_name).objects.get(pk=ids[key])
        if expect_cycle_column:
            assert row.cycle_id is None
    assert apps.get_model("support", "Agent").objects.filter(pk=ids["agent"]).exists()


def test_conversation_cycle_expand_apply_reverse_reapply(restore_migrations: None) -> None:
    # --- Starting point: 0019, no cycle objects.
    executor = _migrate(MIGRATION_BEFORE)
    legacy_apps = executor.loader.project_state([MIGRATION_BEFORE]).apps
    assert not _table_exists(CYCLE_TABLE)
    assert "cycle_id" not in _table_columns("new_conversations")
    ids = _create_legacy_rows(legacy_apps)

    # --- Apply 0020.
    executor = _migrate(MIGRATION_AFTER)
    migrated_apps = executor.loader.project_state([MIGRATION_AFTER]).apps
    assert _table_exists(CYCLE_TABLE)
    assert _installed_indexes(CYCLE_TABLE) >= CYCLE_INDEXES
    # Plain unique constraints surface in pg_constraint; the partial active
    # unique is a backing index only (asserted above and behaviorally in the
    # model tests).
    assert "uniq_conv_cycle_natural_key" in _installed_constraints(CYCLE_TABLE)
    assert CYCLE_TRIGGER in _installed_guard_triggers()
    assert _installed_constraints("assignment_attempts") >= LEGACY_CONSTRAINTS or (
        _installed_indexes("assignment_attempts") >= LEGACY_CONSTRAINTS
    )
    for table in (
        "new_conversations",
        "assigned_conversations",
        "closed_conversations",
        "assignment_attempts",
        "assignment_logs",
        "conversation_reassignments",
    ):
        assert "cycle_id" in _table_columns(table)

    # --- Legacy data survives, no cycle invented.
    _assert_legacy_rows_intact(migrated_apps, ids, expect_cycle_column=True)
    cycle_model = migrated_apps.get_model("support", "SupportConversationCycle")
    assert cycle_model.objects.count() == 0

    # --- Writer guard covers the new table.
    _ensure_test_roles()
    entered_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    try:
        _set_application_name("judah:production:forged-client")
        _set_role("judah_untrusted_client")
        with pytest.raises(DatabaseError, match="untrusted JUDAH database role"), transaction.atomic():
            cycle_model.objects.create(
                cycle_key="hubspot:v1:untrusted",
                source_account_id="1",
                hubspot_ticket_id="1",
                entered_stage_at=entered_at,
                opened_at=entered_at,
            )
        _reset_role()

        _set_application_name("judah:production:pytest")
        _set_role("judah_production_runtime")
        cycle = cycle_model.objects.create(
            cycle_key="hubspot:v1:trusted",
            source_account_id="1",
            hubspot_ticket_id="1",
            entered_stage_at=entered_at,
            opened_at=entered_at,
        )
        assert cycle_model.objects.filter(pk=cycle.pk).delete()[0] == 1
        _reset_role()
    finally:
        _reset_role()
        _set_application_name("judah:local-test:pytest")

    # --- Reverse removes only Gate B objects.
    executor = _migrate(MIGRATION_BEFORE)
    reversed_apps = executor.loader.project_state([MIGRATION_BEFORE]).apps
    assert not _table_exists(CYCLE_TABLE)
    assert CYCLE_TRIGGER not in _installed_guard_triggers()
    assert _installed_guard_triggers() >= LEGACY_GUARD_TRIGGERS
    assert "cycle_id" not in _table_columns("new_conversations")
    _assert_legacy_rows_intact(reversed_apps, ids, expect_cycle_column=False)

    # --- Reapply restores the expansion; legacy rows still intact.
    executor = _migrate(MIGRATION_AFTER)
    reapplied_apps = executor.loader.project_state([MIGRATION_AFTER]).apps
    assert _table_exists(CYCLE_TABLE)
    assert CYCLE_TRIGGER in _installed_guard_triggers()
    _assert_legacy_rows_intact(reapplied_apps, ids, expect_cycle_column=True)
    cycle_model = reapplied_apps.get_model("support", "SupportConversationCycle")
    assert cycle_model.objects.count() == 0

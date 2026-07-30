"""PostgreSQL verification for operational-table least privilege."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION_BEFORE = ("support", "0025_administrative_action_audit")
MIGRATION_AFTER = ("support", "0026_protect_operational_tables_rls")
SAMPLE_TABLES = (
    "conversation_instances",
    "assignment_attempts",
    "token_blacklist_outstandingtoken",
)
rls_migration = import_module("apps.support.migrations.0026_protect_operational_tables_rls")


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete graph after forward/reverse assertions."""
    if connection.vendor != "postgresql":
        pytest.skip("Operational RLS migration tests require PostgreSQL.")
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


def _ensure_client_roles() -> None:
    with connection.cursor() as cursor:
        for role in ("anon", "authenticated"):
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", [role])
            if not cursor.fetchone()[0]:
                cursor.execute(f"CREATE ROLE {connection.ops.quote_name(role)} NOLOGIN")


def _assert_protected(expected: bool) -> None:
    with connection.cursor() as cursor:
        for table in SAMPLE_TABLES:
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", [f"public.{table}"])
            assert cursor.fetchone()[0] is expected
            for role in ("anon", "authenticated"):
                cursor.execute(
                    "SELECT has_table_privilege(%s, %s, 'SELECT'), has_table_privilege(%s, %s, 'TRUNCATE')",
                    [role, f"public.{table}", role, f"public.{table}"],
                )
                select_allowed, truncate_allowed = cursor.fetchone()
                assert select_allowed is (not expected)
                assert truncate_allowed is (not expected)


def test_operational_rls_forward_reverse_forward(restore_migrations: None) -> None:
    _ensure_client_roles()
    _migrate(MIGRATION_BEFORE)
    _assert_protected(False)
    _migrate(MIGRATION_AFTER)
    _assert_protected(True)
    _migrate(MIGRATION_BEFORE)
    _assert_protected(False)
    _migrate(MIGRATION_AFTER)
    _assert_protected(True)


def test_operational_rls_skips_tables_not_owned_by_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_editor = MagicMock()
    schema_editor.connection.vendor = "postgresql"
    schema_editor.connection.ops.quote_name.side_effect = lambda value: f'"{value}"'
    monkeypatch.setattr(
        rls_migration,
        "_existing_tables",
        MagicMock(return_value={"conversation_instances"}),
    )
    monkeypatch.setattr(
        rls_migration,
        "_manageable_tables",
        MagicMock(return_value=set()),
    )
    monkeypatch.setattr(
        rls_migration,
        "_existing_client_roles",
        MagicMock(return_value={"anon", "authenticated"}),
    )

    with pytest.warns(RuntimeWarning, match="table-owner connection"):
        rls_migration.protect_operational_tables(None, schema_editor)

    cursor = schema_editor.connection.cursor.return_value.__enter__.return_value
    cursor.execute.assert_not_called()

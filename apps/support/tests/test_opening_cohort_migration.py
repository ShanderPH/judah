"""PostgreSQL migration and security checks for opening cohorts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]
MIGRATION_BEFORE = ("support", "0029_grant_helpdesk_calendar_runtime_access")
MIGRATION_AFTER = ("support", "0030_opening_assignment_cohort")
TABLE = "opening_assignment_cohorts"


@pytest.fixture
def restore_migrations() -> Iterator[None]:
    """Restore the complete migration graph after destructive migration checks."""
    if connection.vendor != "postgresql":
        pytest.skip("Opening cohort migration checks require disposable PostgreSQL.")
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


def _table_exists() -> bool:
    return TABLE in connection.introspection.table_names()


def _ensure_roles() -> None:
    with connection.cursor() as cursor:
        for role in ("anon", "authenticated", "judah_production_runtime", "judah_staging_runtime"):
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", [role])
            if not cursor.fetchone()[0]:
                cursor.execute(f"CREATE ROLE {connection.ops.quote_name(role)} NOLOGIN")


def test_forward_reverse_forward_and_rls(restore_migrations: None) -> None:
    """The table is reversible and protected every time it is applied."""
    _migrate(MIGRATION_BEFORE)
    assert _table_exists() is False
    _ensure_roles()
    _migrate(MIGRATION_AFTER)
    assert _table_exists() is True
    with connection.cursor() as cursor:
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", [f"public.{TABLE}"])
        assert cursor.fetchone()[0] is True
        for role in ("anon", "authenticated"):
            cursor.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", [role, f"public.{TABLE}"])
            assert cursor.fetchone()[0] is False
        for role in ("judah_production_runtime", "judah_staging_runtime"):
            cursor.execute("SELECT has_table_privilege(%s, %s, 'SELECT,INSERT,UPDATE,DELETE')", [role, TABLE])
            assert cursor.fetchone()[0] is True
    _migrate(MIGRATION_BEFORE)
    assert _table_exists() is False
    _migrate(MIGRATION_AFTER)
    assert _table_exists() is True

"""Regression tests for helpdesk calendar runtime grants."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Self


class RecordingCursor:
    def __init__(self, existing_roles: tuple[str, ...]) -> None:
        self.existing_roles = existing_roles
        self.statements: list[tuple[str, object | None]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: object | None = None) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[str]]:
        return [(role,) for role in self.existing_roles]


class FakeOperations:
    @staticmethod
    def quote_name(value: str) -> str:
        return f'"{value}"'


class FakeConnection:
    vendor = "postgresql"
    ops = FakeOperations()

    def __init__(self, cursor: RecordingCursor) -> None:
        self.recording_cursor = cursor

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


class FakeSchemaEditor:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.connection = FakeConnection(cursor)


def _migration_module() -> ModuleType:
    return importlib.import_module("apps.support.migrations.0029_grant_helpdesk_calendar_runtime_access")


def test_grants_crud_on_every_calendar_table_to_existing_runtime_role() -> None:
    migration = _migration_module()
    cursor = RecordingCursor(("judah_production_runtime",))

    migration.grant_calendar_runtime_access(None, FakeSchemaEditor(cursor))

    grants = [sql for sql, _params in cursor.statements if sql.startswith("GRANT")]
    assert len(grants) == len(migration.CALENDAR_TABLES)
    for table in migration.CALENDAR_TABLES:
        assert f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" TO "judah_production_runtime"' in grants


def test_missing_runtime_roles_are_skipped() -> None:
    migration = _migration_module()
    cursor = RecordingCursor(())

    migration.grant_calendar_runtime_access(None, FakeSchemaEditor(cursor))

    assert not [sql for sql, _params in cursor.statements if sql.startswith("GRANT")]

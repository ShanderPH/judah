"""Regression tests for conversation attendant runtime grants."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Self


class RecordingCursor:
    """Record migration SQL without requiring privileged database roles."""

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
    return importlib.import_module("apps.support.migrations.0032_grant_conversation_attendant_runtime_access")


def test_grants_only_required_privileges_to_existing_runtime_roles() -> None:
    migration = _migration_module()
    cursor = RecordingCursor(("judah_production_runtime", "judah_staging_runtime"))

    migration.grant_attendant_runtime_access(None, FakeSchemaEditor(cursor))

    grants = [sql for sql, _params in cursor.statements if sql.startswith("GRANT")]
    assert grants == [
        'GRANT SELECT, INSERT, UPDATE ON TABLE public."conversation_instance_attendants" TO "judah_production_runtime"',
        'GRANT SELECT, INSERT, UPDATE ON TABLE public."conversation_instance_attendants" TO "judah_staging_runtime"',
    ]
    assert all("DELETE" not in statement for statement in grants)
    assert all("anon" not in statement and "authenticated" not in statement for statement in grants)


def test_reverse_revokes_exactly_the_granted_privileges() -> None:
    migration = _migration_module()
    cursor = RecordingCursor(("judah_production_runtime",))

    migration.revoke_attendant_runtime_access(None, FakeSchemaEditor(cursor))

    revokes = [sql for sql, _params in cursor.statements if sql.startswith("REVOKE")]
    assert revokes == [
        'REVOKE SELECT, INSERT, UPDATE ON TABLE public."conversation_instance_attendants" '
        'FROM "judah_production_runtime"'
    ]


def test_missing_runtime_roles_are_skipped() -> None:
    migration = _migration_module()
    cursor = RecordingCursor(())

    migration.grant_attendant_runtime_access(None, FakeSchemaEditor(cursor))

    assert not [sql for sql, _params in cursor.statements if sql.startswith("GRANT")]

"""Tests for destructive-test database target validation."""

from __future__ import annotations

import pytest

from common.database_safety import UnsafeTestDatabaseError, assert_safe_test_database


def test_accepts_local_sqlite_database() -> None:
    identity = assert_safe_test_database("sqlite:///./.test.sqlite3")

    assert identity.backend == "sqlite"
    assert identity.host == "local-file"


def test_accepts_named_local_postgresql_test_database() -> None:
    identity = assert_safe_test_database("postgresql://postgres:secret@127.0.0.1:5432/judah_test")

    assert identity.backend == "postgresql"
    assert identity.host == "127.0.0.1"
    assert identity.name == "judah_test"


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://postgres:secret@db.example.com:5432/judah_test",
        "postgresql://postgres:secret@localhost:5432/judah",
        "postgresql://postgres:secret@localhost:5432/production",
        "",
    ],
)
def test_rejects_remote_or_non_disposable_database(database_url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_database(database_url)


def test_requires_unique_database_name_in_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "1234")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    identity = assert_safe_test_database("postgresql://postgres:secret@localhost:5432/judah_ci_1234_2")

    assert identity.name == "judah_ci_1234_2"


def test_rejects_database_from_another_github_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", "1234")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")

    with pytest.raises(UnsafeTestDatabaseError, match="uniquely bound"):
        assert_safe_test_database("postgresql://postgres:secret@localhost:5432/judah_ci_9999_1")

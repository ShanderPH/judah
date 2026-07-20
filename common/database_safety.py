"""Safety checks for database targets used by tests and CI."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LOCAL_TEST_DATABASE_NAMES = frozenset({"judah_test"})
CI_DATABASE_PREFIX = "judah_ci_"


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when a test command targets a non-disposable database."""


@dataclass(frozen=True)
class TestDatabaseIdentity:
    """Redacted identity of a database approved for destructive tests."""

    backend: str
    host: str
    name: str


def assert_safe_test_database(database_url: str) -> TestDatabaseIdentity:
    """Validate that a database URL points to a local disposable test database.

    Args:
        database_url: Database URL that a test or migration command will use.

    Returns:
        A redacted database identity suitable for logs.

    Raises:
        UnsafeTestDatabaseError: If the URL can resolve to a shared database.
    """
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme == "sqlite":
        name = unquote(parsed.path or parsed.netloc)
        if not name:
            raise UnsafeTestDatabaseError("SQLite test database path is empty.")
        return TestDatabaseIdentity(backend="sqlite", host="local-file", name=name)

    if scheme not in {"postgres", "postgresql"}:
        raise UnsafeTestDatabaseError(f"Unsupported test database backend: {scheme or 'missing'}.")

    host = (parsed.hostname or "").lower()
    name = unquote(parsed.path.lstrip("/"))
    if host not in LOCAL_DATABASE_HOSTS:
        raise UnsafeTestDatabaseError(f"PostgreSQL test database host is not local: {host or 'missing'}.")
    if name not in LOCAL_TEST_DATABASE_NAMES and not name.startswith(CI_DATABASE_PREFIX):
        raise UnsafeTestDatabaseError(
            "PostgreSQL test database name is not disposable: "
            f"{name or 'missing'}; expected judah_test or {CI_DATABASE_PREFIX}<unique-id>."
        )

    if os.environ.get("GITHUB_ACTIONS") == "true":
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
        expected_name = f"{CI_DATABASE_PREFIX}{run_id}_{run_attempt}"
        if not run_id or not run_attempt or name != expected_name:
            raise UnsafeTestDatabaseError(
                f"CI database must be uniquely bound to this run: expected {expected_name}, got {name or 'missing'}."
            )

    return TestDatabaseIdentity(backend="postgresql", host=host, name=name)


def main() -> None:
    """Validate ``DATABASE_URL`` and print only its redacted identity."""
    identity = assert_safe_test_database(os.environ.get("DATABASE_URL", ""))
    sys.stdout.write(f"Safe test database: backend={identity.backend} host={identity.host} name={identity.name}\n")


if __name__ == "__main__":
    main()

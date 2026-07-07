"""Run local validation checks with CI-like failure semantics."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence

TEST_ENV = {
    "DJANGO_ENV": "test",
    "DJANGO_SECRET_KEY": "ci-secret-key-not-for-production",
    "DJANGO_DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DATABASE_URL": "sqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/0",
    "SENTRY_DSN": "",
    "OPENAI_API_KEY": "sk-test-placeholder",
    "PINECONE_API_KEY": "test-placeholder",
    "PINECONE_INDEX_NAME": "test-index",
    "HUBSPOT_ACCESS_TOKEN": "test-placeholder",
    "HUBSPOT_APP_SECRET": "test-placeholder",
    "JIRA_SERVER_URL": "https://test.atlassian.net",
    "JIRA_API_TOKEN": "test-placeholder",
    "JIRA_USER_EMAIL": "test@test.com",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY": "test-placeholder",
    "SUPABASE_ANON_KEY": "test-placeholder",
    "AGNO_TELEMETRY": "false",
}

MANDATORY_COMMANDS = (
    ("Running migrations...", (sys.executable, "manage.py", "migrate", "--run-syncdb")),
    (
        "Checking for missing migrations...",
        (sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"),
    ),
    ("Running django checks...", (sys.executable, "manage.py", "check", "--fail-level", "WARNING")),
)


def configure_test_environment() -> None:
    """Set local safe defaults before importing Django settings."""
    os.environ.update(TEST_ENV)


def run_command(label: str, command: Sequence[str]) -> int:
    """Run a mandatory validation command and return its exit code."""
    print(label)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    """Run all mandatory checks, failing on the first validation failure."""
    configure_test_environment()
    for label, command in MANDATORY_COMMANDS:
        return_code = run_command(label, command)
        if return_code != 0:
            return return_code
    return 0


if __name__ == "__main__":
    sys.exit(main())

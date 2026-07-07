"""Safe local test runner.

This script is the default way to run the test suite locally. It forces a
private SQLite file database so tests never accidentally touch a remote or
production PostgreSQL instance. The database file is created next to this
script and ignored by git.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

import pytest

os.environ["DJANGO_ENV"] = "test"
os.environ["DJANGO_SECRET_KEY"] = "ci-secret-key-not-for-production"
os.environ["DJANGO_DEBUG"] = "False"
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["SENTRY_DSN"] = ""
os.environ["OPENAI_API_KEY"] = "sk-test-placeholder"
os.environ["PINECONE_API_KEY"] = "test-placeholder"
os.environ["PINECONE_INDEX_NAME"] = "test-index"
os.environ["HUBSPOT_ACCESS_TOKEN"] = "test-placeholder"
os.environ["HUBSPOT_APP_SECRET"] = "test-placeholder"
os.environ["JIRA_SERVER_URL"] = "https://test.atlassian.net"
os.environ["JIRA_API_TOKEN"] = "test-placeholder"
os.environ["JIRA_USER_EMAIL"] = "test@test.com"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "test-placeholder"
os.environ["SUPABASE_ANON_KEY"] = "test-placeholder"
os.environ["AGNO_TELEMETRY"] = "false"

# Default behavior: use a private, persistent SQLite file so local tests never
# touch a remote or production database. pytest-django will create the test
# database, run migrations, and clean it up after the run.
# To use a local Postgres instead, set JUDAH_TEST_DATABASE_URL to a local URL.
test_database_url = os.environ.get("JUDAH_TEST_DATABASE_URL", "")
if test_database_url:
    parsed = urlparse(test_database_url)
    is_postgres = parsed.scheme in ("postgres", "postgresql")
    is_local = parsed.hostname in (None, "localhost", "127.0.0.1", "::1")
    if is_postgres and not is_local:
        print(
            "ERROR: refusing to run local tests against a remote database. "
            f"JUDAH_TEST_DATABASE_URL points to {parsed.hostname}. "
            "Use a local SQLite/Postgres database for local tests.",
            file=sys.stderr,
        )
        sys.exit(1)
    os.environ["DATABASE_URL"] = test_database_url
else:
    os.environ["DATABASE_URL"] = "sqlite:///./.test.sqlite3"

sys.exit(pytest.main(["--cov=apps", "--cov=common", "-v"]))

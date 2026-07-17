"""Regression tests for explicit and production-safe settings profiles."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _inspect_settings(environment: str) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    child_env.update(
        {
            "DJANGO_ENV": environment,
            "DJANGO_SECRET_KEY": "settings-profile-test-only",
            "DATABASE_URL": "sqlite:///./.settings-profile-test.sqlite3",
            "SENTRY_DSN": "",
        }
    )
    script = (
        "import core.settings as settings; "
        "print(settings.DEBUG); "
        "print(settings.LOGGING['handlers']['console']['formatter']); "
        "print(settings.LOGGING['root']['level']); "
        "print('debug_toolbar' in settings.INSTALLED_APPS)"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_staging_is_production_safe_with_diagnostic_logging() -> None:
    result = _inspect_settings("staging")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["False", "json", "INFO", "False"]


def test_production_keeps_stricter_root_logging() -> None:
    result = _inspect_settings("production")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["False", "json", "ERROR", "False"]


def test_unknown_environment_fails_closed() -> None:
    result = _inspect_settings("stagin")

    assert result.returncode != 0
    assert "Unsupported DJANGO_ENV='stagin'" in result.stderr

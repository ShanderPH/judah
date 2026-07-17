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
        "print('debug_toolbar' in settings.INSTALLED_APPS); "
        "print(settings.AGENT_STATUS_SYNC_ENABLED); "
        "print(settings.CELERY_RESULT_BACKEND); "
        "print(settings.CELERY_TASK_IGNORE_RESULT); "
        "print(settings.CACHES['default']['OPTIONS']['pool_class'])"
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
    assert result.stdout.splitlines() == [
        "False",
        "json",
        "INFO",
        "False",
        "False",
        "None",
        "True",
        "redis.BlockingConnectionPool",
    ]


def test_production_keeps_stricter_root_logging() -> None:
    result = _inspect_settings("production")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "False",
        "json",
        "ERROR",
        "False",
        "True",
        "None",
        "True",
        "redis.BlockingConnectionPool",
    ]


def test_celery_images_use_environment_settings_loader() -> None:
    for dockerfile_name in ("Dockerfile.worker", "Dockerfile.beat"):
        contents = (REPOSITORY_ROOT / dockerfile_name).read_text(encoding="utf-8")
        assert "DJANGO_SETTINGS_MODULE=core.settings.production" not in contents
        assert "DJANGO_SETTINGS_MODULE=core.settings" in contents


def test_unknown_environment_fails_closed() -> None:
    result = _inspect_settings("stagin")

    assert result.returncode != 0
    assert "Unsupported DJANGO_ENV='stagin'" in result.stderr

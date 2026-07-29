"""Tests for structured logging helpers and filters."""

import logging
from unittest.mock import Mock, patch

import pytest
import structlog

from celery import signals
from common.logging import (
    HealthCheckFilter,
    SlowQueryFilter,
    add_service_context,
    bind_request_context,
    bind_task_context,
    clear_context,
    connect_celery_signals,
    get_logger,
    log_external_call,
    maybe_log,
    scrub_pii,
)


def test_context_helpers_and_logger_factory() -> None:
    with (
        patch.object(structlog.contextvars, "bind_contextvars") as bind,
        patch.object(structlog.contextvars, "clear_contextvars") as clear,
        patch("common.logging.structlog.get_logger", return_value=Mock()) as factory,
    ):
        assert get_logger("test") is factory.return_value
        bind_request_context("req", user_id=1, church_id=2, method="GET", path="/")
        bind_task_context("task", "name")
        clear_context()

    assert bind.call_count == 2
    clear.assert_called_once()


def test_external_call_logs_success_and_failure() -> None:
    with patch("common.logging._ext_logger") as logger:
        with log_external_call("hubspot", "GET", "https://example", extra={"operation": "read"}):
            pass
        logger.info.assert_called_once()

        with pytest.raises(RuntimeError), log_external_call("hubspot", "GET", "https://example"):
            raise RuntimeError("offline")
        logger.warning.assert_called_once()


def test_processors_scrub_nested_pii_and_add_context(monkeypatch) -> None:
    event = {
        "token": "secret",
        "nested": {"Authorization": "Bearer x", "items": [{"cpf": "123"}, ("safe",)]},
    }
    scrubbed = scrub_pii(None, "info", event)
    assert scrubbed["token"] == "[REDACTED]"
    assert scrubbed["nested"]["Authorization"] == "[REDACTED]"
    assert scrubbed["nested"]["items"][0]["cpf"] == "[REDACTED]"

    embedded = scrub_pii(
        None,
        "error",
        {
            "error": (
                "ConnectionError redis://default:redis-secret@redis.internal:6379/0 "
                "password=another-secret "
                "https://example.test/callback?access_token=token-secret"
            )
        },
    )
    assert "redis-secret" not in embedded["error"]
    assert "another-secret" not in embedded["error"]
    assert "token-secret" not in embedded["error"]
    assert "redis://default:[REDACTED]@redis.internal:6379/0" in embedded["error"]

    monkeypatch.setenv("DJANGO_ENV", "test")
    assert add_service_context(None, "info", {}) == {"service": "judah", "env": "test"}
    custom = add_service_context(None, "info", {"service": "custom", "env": "prod"})
    assert custom == {"service": "custom", "env": "prod"}


def test_logging_filters() -> None:
    health = HealthCheckFilter()
    assert health.filter(logging.LogRecord("x", logging.INFO, "", 1, "GET /health/", (), None)) is False
    assert health.filter(logging.LogRecord("x", logging.INFO, "", 1, "GET /tickets", (), None)) is True

    slow = SlowQueryFilter(threshold_ms=100)
    fast_record = logging.LogRecord("x", logging.DEBUG, "", 1, "query", (), None)
    fast_record.duration = 0.05
    slow_record = logging.LogRecord("x", logging.DEBUG, "", 1, "query", (), None)
    slow_record.duration = 0.2
    plain_record = logging.LogRecord("x", logging.DEBUG, "", 1, "plain", (), None)
    assert slow.filter(fast_record) is False
    assert slow.filter(slow_record) is True
    assert slow.filter(plain_record) is True


def test_maybe_log_honors_sampling() -> None:
    logger = Mock()
    maybe_log(logger, "info", "always", sample_rate=1.0, value=1)
    with patch("random.random", return_value=0.9):
        maybe_log(logger, "debug", "skipped", sample_rate=0.1)
    with patch("random.random", return_value=0.01):
        maybe_log(logger, "debug", "sampled", sample_rate=0.1)

    logger.info.assert_called_once_with("always", sample_rate=1.0, value=1)
    logger.debug.assert_called_once_with("sampled", sample_rate=0.1)


def test_celery_failure_and_retry_logs_are_cataloged() -> None:
    passthrough = lambda receiver: receiver  # noqa: E731
    with (
        patch.object(signals.task_prerun, "connect", side_effect=passthrough),
        patch.object(signals.task_postrun, "connect", side_effect=passthrough),
        patch.object(signals.task_failure, "connect", side_effect=passthrough) as failure_connect,
        patch.object(signals.task_retry, "connect", side_effect=passthrough) as retry_connect,
    ):
        connect_celery_signals()

    failure_receiver = failure_connect.call_args.args[0]
    retry_receiver = retry_connect.call_args.args[0]
    logger = Mock()
    with patch("common.logging.get_logger", return_value=logger):
        failure_receiver(task_id="task-failed", exception=RuntimeError("database unavailable"))
        retry_receiver(task_id="task-retry", reason=TimeoutError("provider timeout"))

    failure = logger.error.call_args
    assert failure.args == ("celery_task_failure",)
    assert failure.kwargs["error_catalog_code"] == "CELERY-TASK-001"
    assert failure.kwargs["message_error"].startswith("Erro catalogado [CELERY-TASK-001]:")
    assert failure.kwargs["error_type"] == "RuntimeError"

    retry = logger.warning.call_args
    assert retry.args == ("celery_task_retry",)
    assert retry.kwargs["error_catalog_code"] == "CELERY-TASK-002"
    assert retry.kwargs["message_error"].startswith("Erro catalogado [CELERY-TASK-002]:")
    assert retry.kwargs["retryable"] is True

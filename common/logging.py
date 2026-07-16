"""Centralized structured logging utilities for JUDAH.

Implements 2026 observability best practices for a Django + structlog +
Celery + Sentry stack:

  • Consistent structured schema (service, env, request_id, user_id, …)
  • Request correlation IDs via contextvars (zero-copy across async/sync)
  • Celery task context auto-binding via signals
  • External API call timing + error capture with context manager
  • Health-check log suppression (avoids /health/ flooding prod logs)
  • PII field scrubbing processor
  • Slow-query detection helper (Django DB backend integration)
  • Log-level sampling for high-frequency events (e.g. rate-limit hits)

Usage
-----
    from common.logging import get_logger, log_external_call

    logger = get_logger(__name__)
    logger.info("ticket_assigned", ticket_id="123", agent="Ana")

    with log_external_call("hubspot", "POST", url):
        response = httpx.post(url, json=payload)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

__all__ = [
    "HealthCheckFilter",
    "SlowQueryFilter",
    "add_service_context",
    "bind_request_context",
    "bind_task_context",
    "clear_context",
    "connect_celery_signals",
    "get_logger",
    "log_external_call",
    "maybe_log",
    "scrub_pii",
]

# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog BoundLogger bound to *name*.

    Prefer this over ``structlog.get_logger()`` directly so all application
    loggers go through the same factory and can be swapped centrally.

    Example::

        logger = get_logger(__name__)
        logger.info("user_login", user_id=42, method="jwt")
    """
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Context helpers (thin wrappers around structlog.contextvars)
# ---------------------------------------------------------------------------


def bind_request_context(
    request_id: str,
    *,
    user_id: int | str | None = None,
    church_id: int | str | None = None,
    method: str | None = None,
    path: str | None = None,
) -> None:
    """Bind request-scoped context variables for the current thread/task.

    Call this at the very beginning of a request (in RequestLoggingMiddleware)
    so every subsequent log record within that request automatically carries
    these fields — no need to pass them explicitly to each logger call.
    """
    ctx: dict[str, Any] = {"request_id": request_id}
    if user_id is not None:
        ctx["user_id"] = str(user_id)
    if church_id is not None:
        ctx["church_id"] = str(church_id)
    if method is not None:
        ctx["http_method"] = method
    if path is not None:
        ctx["http_path"] = path
    structlog.contextvars.bind_contextvars(**ctx)


def bind_task_context(task_id: str, task_name: str) -> None:
    """Bind Celery task context variables for the current worker thread.

    Automatically called by the Celery signal handlers set up in
    ``connect_celery_signals()``.  You rarely need to call this directly.
    """
    structlog.contextvars.bind_contextvars(
        task_id=task_id,
        task_name=task_name,
    )


def clear_context() -> None:
    """Clear all structlog context variables.

    Called automatically by RequestLoggingMiddleware at the end of every
    request and by Celery signal handlers at task completion/failure.
    """
    structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# External API call context manager
# ---------------------------------------------------------------------------

_ext_logger = get_logger("common.external")


@contextmanager
def log_external_call(
    service: str,
    method: str,
    url: str,
    *,
    extra: dict[str, Any] | None = None,
) -> Generator[None]:
    """Context manager that logs external HTTP calls with timing and outcome.

    Emits ``external_call_start`` at entry (DEBUG), ``external_call_ok``
    on success (INFO with duration_ms), and ``external_call_error`` on any
    exception (WARNING with error type and re-raised exception).

    The URL is included as-is; callers should strip auth tokens from it
    before passing in sensitive paths.

    Example::

        with log_external_call("hubspot", "GET", f"{base}/crm/v3/objects/tickets"):
            resp = httpx.get(url, headers=headers)
    """
    _extra = extra or {}
    start = time.perf_counter()

    _ext_logger.debug(
        "external_call_start",
        service=service,
        method=method,
        url=url,
        **_extra,
    )
    try:
        yield
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        _ext_logger.warning(
            "external_call_error",
            service=service,
            method=method,
            url=url,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
            **_extra,
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        _ext_logger.info(
            "external_call_ok",
            service=service,
            method=method,
            url=url,
            duration_ms=duration_ms,
            **_extra,
        )


# ---------------------------------------------------------------------------
# structlog processors
# ---------------------------------------------------------------------------

#: Fields that contain PII and must be redacted before logging.
_PII_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "token",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "id_token",
        "credit_card",
        "card_number",
        "cpf",
        "cnpj",
        "ssn",
    }
)


def scrub_pii(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Structlog processor: redact known PII fields before emitting the log.

    Performs case-insensitive key matching.  Any key whose lowercase form
    appears in ``_PII_FIELDS`` is replaced with ``"[REDACTED]"``.

    Register in ``structlog.configure(processors=[..., scrub_pii, ...])``.
    """

    def _scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if str(key).lower() in _PII_FIELDS else _scrub(item) for key, item in value.items()
            }
        if isinstance(value, list):
            return [_scrub(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_scrub(item) for item in value)
        return value

    for key in list(event_dict.keys()):
        event_dict[key] = "[REDACTED]" if key.lower() in _PII_FIELDS else _scrub(event_dict[key])
    return event_dict


def add_service_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor: stamp every log record with service metadata.

    Adds ``service`` and ``env`` keys if not already present so records are
    immediately identifiable in a multi-service log aggregator (e.g. Datadog,
    Loki, CloudWatch).
    """
    event_dict.setdefault("service", "judah")
    event_dict.setdefault("env", os.environ.get("DJANGO_ENV", "development"))
    return event_dict


# ---------------------------------------------------------------------------
# stdlib logging filters
# ---------------------------------------------------------------------------


class HealthCheckFilter(logging.Filter):
    """Suppress request log records for infrastructure health-check endpoints.

    Prevents Railway / ELB / k8s liveness probes from flooding production
    logs with hundreds of entries per minute that carry zero diagnostic value.

    Suppressed paths: /api/v1/health/, /health/, /ping/, /readyz/, /livez/
    """

    _SUPPRESSED: frozenset[str] = frozenset({"/api/v1/health/", "/health/", "/ping/", "/readyz/", "/livez/"})

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in self._SUPPRESSED)


class SlowQueryFilter(logging.Filter):
    """Pass only Django DB log records that exceed a latency threshold.

    Configure ``django.db.backends`` at DEBUG level and attach this filter
    to the handler to capture only slow queries without drowning in noise.

    Example (development.py)::

        LOGGING["loggers"]["django.db.backends"]["level"] = "DEBUG"
        LOGGING["handlers"]["console"]["filters"].append("slow_queries")
        LOGGING["filters"]["slow_queries"] = {
            "()": "common.logging.SlowQueryFilter",
            "threshold_ms": 100.0,
        }

    Args:
        threshold_ms: Minimum query duration in milliseconds to emit.
                      Defaults to 100 ms.
    """

    def __init__(self, name: str = "", threshold_ms: float = 100.0) -> None:
        super().__init__(name)
        self.threshold_ms = threshold_ms

    def filter(self, record: logging.LogRecord) -> bool:
        # Django sets record.duration in seconds for DB backend queries.
        duration_s: float | None = getattr(record, "duration", None)
        if duration_s is None:
            return True  # Non-query record — let it through
        return (duration_s * 1000) >= self.threshold_ms


# ---------------------------------------------------------------------------
# Celery signal integration
# ---------------------------------------------------------------------------


def connect_celery_signals() -> None:
    """Wire Celery task signals to structlog contextvars for automatic binding.

    Call once from your Celery app's ``on_after_configure`` hook, or from
    ``AppConfig.ready()`` in a Celery-enabled app:

    Example (in apps/support/apps.py)::

        from django.apps import AppConfig

        class SupportConfig(AppConfig):
            name = "apps.support"

            def ready(self):
                from common.logging import connect_celery_signals
                connect_celery_signals()

    After this, every task will automatically have ``task_id`` and
    ``task_name`` injected into all structlog records it emits.
    """
    try:
        from celery import signals  # type: ignore[import-untyped]
    except ImportError:
        return

    @signals.task_prerun.connect  # type: ignore[misc]
    def _task_prerun(task_id: str, task: Any, **_kwargs: Any) -> None:
        structlog.contextvars.clear_contextvars()
        bind_task_context(task_id=task_id, task_name=task.name)

    @signals.task_postrun.connect  # type: ignore[misc]
    def _task_postrun(**_kwargs: Any) -> None:
        structlog.contextvars.clear_contextvars()

    @signals.task_failure.connect  # type: ignore[misc]
    def _task_failure(task_id: str, exception: Exception, **_kwargs: Any) -> None:
        _logger = get_logger("celery.task")
        _logger.error(
            "celery_task_failure",
            task_id=task_id,
            error_type=type(exception).__name__,
            error=str(exception),
        )
        structlog.contextvars.clear_contextvars()

    @signals.task_retry.connect  # type: ignore[misc]
    def _task_retry(task_id: str, reason: Exception, **_kwargs: Any) -> None:
        _logger = get_logger("celery.task")
        _logger.warning(
            "celery_task_retry",
            task_id=task_id,
            reason=str(reason),
        )


# ---------------------------------------------------------------------------
# Sampling helper
# ---------------------------------------------------------------------------


def maybe_log(
    logger_instance: structlog.stdlib.BoundLogger,
    level: str,
    event: str,
    *,
    sample_rate: float = 1.0,
    **kwargs: Any,
) -> None:
    """Emit a log record at *sample_rate* probability (0.0 - 1.0).

    Use for very high-frequency events (e.g. rate-limit counter increments,
    cache hits on hot paths) where logging every occurrence would be too noisy
    but you still want periodic visibility.

    Example::

        maybe_log(logger, "debug", "cache_hit", sample_rate=0.01, key=cache_key)
        # Logs ~1 % of cache hits
    """
    import random

    if sample_rate >= 1.0 or random.random() < sample_rate:
        getattr(logger_instance, level)(event, sample_rate=sample_rate, **kwargs)

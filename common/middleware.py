"""Custom middlewares for JUDAH."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from common.logging import bind_request_context, clear_context

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)

# Paths whose request logs are suppressed (health checks / probes).
_SILENT_PATHS: frozenset[str] = frozenset({"/api/v1/health/", "/health/", "/ping/", "/readyz/", "/livez/"})


class RequestLoggingMiddleware:
    """Structured request/response logging with per-request correlation ID.

    For every API request this middleware:
      1. Generates a UUID4 ``request_id`` and binds it to structlog's
         contextvars so all log records within the request carry it.
      2. Binds ``user_id`` and ``church_id`` once the auth middleware has
         resolved the JWT (available after ``process_response``).
      3. Emits a single ``http_request`` log record with method, path,
         status code, and wall-clock duration in milliseconds.
      4. Sets the ``X-Request-ID`` response header for client-side correlation.
      5. Suppresses log records for health-check endpoints to avoid log noise.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = str(uuid.uuid4())
        request.META["X_REQUEST_ID"] = request_id

        # Clear any leftovers from a previous request on this thread/greenlet.
        clear_context()
        bind_request_context(request_id, method=request.method, path=request.path)

        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response["X-Request-ID"] = request_id

        # Bind user identity after auth middleware has run.
        user_id = getattr(getattr(request, "auth", None), "pk", None)
        if user_id is not None:
            structlog.contextvars.bind_contextvars(user_id=str(user_id))

        # Suppress noisy health/probe endpoints.
        if request.path not in _SILENT_PATHS:
            logger.info(
                "http_request",
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
                user_id=user_id,
                content_length=response.get("Content-Length"),
            )

        # Clear context after the request so it doesn't leak into the next one.
        clear_context()

        return response

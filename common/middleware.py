"""Custom middlewares for JUDAH."""

import time
import uuid
from typing import Any

import structlog
from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware:
    """Structured request/response logging middleware.

    Logs method, path, status code, duration, and a unique request ID
    for every API call. Sets X-Request-ID header on the response.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = str(uuid.uuid4())
        request.META["X_REQUEST_ID"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()

        response = self.get_response(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response["X-Request-ID"] = request_id

        logger.info(
            "http_request",
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=duration_ms,
            user_id=getattr(getattr(request, "auth", None), "pk", None),
        )

        return response

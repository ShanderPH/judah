"""Rate limiting middleware for JUDAH."""

from typing import Any

import structlog
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse

logger = structlog.get_logger(__name__)

DEFAULT_RATE = 100
DEFAULT_WINDOW = 60


def _get_client_identifier(request: HttpRequest) -> str:
    """Extract a unique identifier for the request originator."""
    if hasattr(request, "auth") and request.auth is not None:
        return f"user:{request.auth.pk}"
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{ip}"


class RateLimitMiddleware:
    """Sliding-window rate limit middleware backed by Redis.

    Reads per-path overrides from settings.RATE_LIMIT_OVERRIDES:
        {"/api/v1/ai/": (20, 60), "/api/v1/auth/": (10, 60)}

    Falls back to DEFAULT_RATE / DEFAULT_WINDOW for all other paths.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        from django.conf import settings

        self.overrides: dict[str, tuple[int, int]] = getattr(settings, "RATE_LIMIT_OVERRIDES", {})

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        rate, window = self._get_limits(request.path)
        identifier = _get_client_identifier(request)
        cache_key = f"ratelimit:{identifier}:{request.path}"

        current_count = cache.get(cache_key, 0)
        if current_count >= rate:
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                path=request.path,
                count=current_count,
                limit=rate,
            )
            return JsonResponse(
                {"detail": "Too many requests. Please slow down."},
                status=429,
                headers={"Retry-After": str(window)},
            )

        pipe_key = f"{cache_key}:ttl"
        if cache.get(pipe_key) is None:
            cache.set(cache_key, 1, window)
            cache.set(pipe_key, 1, window)
        else:
            cache.incr(cache_key)

        response = self.get_response(request)
        response["X-RateLimit-Limit"] = str(rate)
        response["X-RateLimit-Remaining"] = str(max(0, rate - current_count - 1))
        return response

    def _get_limits(self, path: str) -> tuple[int, int]:
        for prefix, limits in self.overrides.items():
            if path.startswith(prefix):
                return limits
        return DEFAULT_RATE, DEFAULT_WINDOW

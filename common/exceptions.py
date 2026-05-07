"""Custom application exceptions for JUDAH."""

import structlog

logger = structlog.get_logger(__name__)


class JudahError(Exception):
    """Base exception for all JUDAH errors."""

    status_code: int = 500
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(JudahError):
    """Raised when a requested resource is not found."""

    status_code = 404
    default_message = "Resource not found."


class ForbiddenError(JudahError):
    """Raised when the caller lacks permission to perform the operation."""

    status_code = 403
    default_message = "You do not have permission to perform this action."


class UnauthorizedError(JudahError):
    """Raised when the caller is not authenticated."""

    status_code = 401
    default_message = "Authentication required."


class ValidationError(JudahError):
    """Raised when input validation fails."""

    status_code = 422
    default_message = "Validation error."

    def __init__(self, message: str | None = None, errors: dict | None = None) -> None:
        self.errors = errors or {}
        super().__init__(message)


class ConflictError(JudahError):
    """Raised when a conflict prevents the operation (e.g. duplicate resource)."""

    status_code = 409
    default_message = "Resource already exists."


class ExternalServiceError(JudahError):
    """Raised when an external API call fails."""

    status_code = 502
    default_message = "External service unavailable."

    def __init__(self, service: str, message: str | None = None) -> None:
        self.service = service
        super().__init__(message or f"Error communicating with {service}.")


class RateLimitExceededError(JudahError):
    """Raised when the rate limit is exceeded for a given caller."""

    status_code = 429
    default_message = "Too many requests. Please slow down."


class CircuitOpenError(JudahError):
    """Raised when the circuit breaker is open for an external dependency."""

    status_code = 503
    default_message = "Service temporarily unavailable. Please try again later."


def register_exception_handlers(api: object) -> None:
    """Register custom exception handlers on the Ninja API instance."""
    from ninja import NinjaAPI

    if not isinstance(api, NinjaAPI):
        return

    @api.exception_handler(NotFoundError)
    def handle_not_found(request, exc: NotFoundError):
        return api.create_response(request, {"detail": exc.message}, status=404)

    @api.exception_handler(ForbiddenError)
    def handle_forbidden(request, exc: ForbiddenError):
        return api.create_response(request, {"detail": exc.message}, status=403)

    @api.exception_handler(UnauthorizedError)
    def handle_unauthorized(request, exc: UnauthorizedError):
        return api.create_response(request, {"detail": exc.message}, status=401)

    @api.exception_handler(ValidationError)
    def handle_validation(request, exc: ValidationError):
        return api.create_response(
            request,
            {"detail": exc.message, "errors": exc.errors},
            status=422,
        )

    @api.exception_handler(ConflictError)
    def handle_conflict(request, exc: ConflictError):
        return api.create_response(request, {"detail": exc.message}, status=409)

    @api.exception_handler(ExternalServiceError)
    def handle_external_service(request, exc: ExternalServiceError):
        return api.create_response(
            request,
            {"detail": exc.message, "service": exc.service},
            status=502,
        )

    @api.exception_handler(RateLimitExceededError)
    def handle_rate_limit(request, exc: RateLimitExceededError):
        return api.create_response(request, {"detail": exc.message}, status=429)

    @api.exception_handler(CircuitOpenError)
    def handle_circuit_open(request, exc: CircuitOpenError):
        return api.create_response(request, {"detail": exc.message}, status=503)

    @api.exception_handler(Exception)
    def handle_unhandled(request, exc: Exception):
        # Surface traceback in production logs (Ninja's default 500 handler
        # re-raises, but Django's request logger may be silenced; this guarantees
        # the trace lands in stdout/Sentry with the request_id correlation.
        logger.exception(
            "unhandled_api_exception",
            error_type=type(exc).__name__,
            error=str(exc),
            path=getattr(request, "path", None),
            method=getattr(request, "method", None),
            request_id=getattr(request, "META", {}).get("X_REQUEST_ID"),
        )
        return api.create_response(
            request,
            {"detail": "Internal server error.", "error_code": "INTERNAL_ERROR"},
            status=500,
        )

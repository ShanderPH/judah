"""Tests for the custom exception hierarchy and Ninja handler registration."""

from __future__ import annotations

from ninja import NinjaAPI

from common.exceptions import (
    CircuitOpenError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    JudahError,
    NotFoundError,
    RateLimitExceededError,
    UnauthorizedError,
    ValidationError,
    register_exception_handlers,
)


class TestExceptionHierarchy:
    def test_all_descend_from_judah_error(self) -> None:
        for exc_cls in (
            NotFoundError,
            ForbiddenError,
            UnauthorizedError,
            ValidationError,
            ConflictError,
            ExternalServiceError,
            RateLimitExceededError,
            CircuitOpenError,
        ):
            assert issubclass(exc_cls, JudahError)

    def test_default_messages(self) -> None:
        assert NotFoundError().status_code == 404
        assert ForbiddenError().status_code == 403
        assert UnauthorizedError().status_code == 401
        assert ConflictError().status_code == 409
        assert RateLimitExceededError().status_code == 429
        assert CircuitOpenError().status_code == 503

    def test_validation_error_carries_errors(self) -> None:
        err = ValidationError("bad", errors={"field": ["required"]})
        assert err.errors == {"field": ["required"]}
        assert err.status_code == 422
        assert err.message == "bad"

    def test_validation_error_defaults(self) -> None:
        err = ValidationError()
        assert err.errors == {}
        assert err.message == ValidationError.default_message

    def test_external_service_error_carries_service(self) -> None:
        err = ExternalServiceError("hubspot")
        assert err.service == "hubspot"
        assert "hubspot" in err.message
        assert err.status_code == 502

    def test_external_service_error_custom_message(self) -> None:
        err = ExternalServiceError("jira", "connection reset")
        assert err.service == "jira"
        assert err.message == "connection reset"

    def test_judah_error_custom_message(self) -> None:
        err = JudahError("custom message")
        assert err.message == "custom message"


class TestRegisterExceptionHandlers:
    def test_registers_handlers_on_ninja_api(self) -> None:
        api = NinjaAPI()
        register_exception_handlers(api)
        # After registration, the exception handler registry must contain
        # entries for each custom exception (Ninja stores them internally
        # as a dict keyed by exception class).
        registered = api._exception_handlers
        assert NotFoundError in registered
        assert ForbiddenError in registered
        assert UnauthorizedError in registered
        assert ValidationError in registered
        assert ConflictError in registered
        assert ExternalServiceError in registered
        assert RateLimitExceededError in registered
        assert CircuitOpenError in registered

    def test_no_op_on_non_ninja_object(self) -> None:
        # Passing a non-NinjaAPI object should not raise.
        register_exception_handlers(object())

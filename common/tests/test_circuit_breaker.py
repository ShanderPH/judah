"""Tests for circuit-breaker failure classification."""

import pytest

from common.circuit_breaker import CircuitBreaker, CircuitState


class ExpectedClientError(Exception):
    """Non-service failure that should not affect circuit health."""


def test_excluded_exception_does_not_increment_failure_count() -> None:
    breaker = CircuitBreaker(
        "test",
        failure_threshold=1,
        excluded_exceptions=(ExpectedClientError,),
    )

    def fail() -> None:
        raise ExpectedClientError

    with pytest.raises(ExpectedClientError):
        breaker.call(fail)

    assert breaker.state == CircuitState.CLOSED

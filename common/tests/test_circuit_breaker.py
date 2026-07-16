"""Tests for circuit-breaker failure classification."""

from unittest.mock import patch

import pytest

from common.circuit_breaker import CircuitBreaker, CircuitState
from common.exceptions import CircuitOpenError


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


def test_sync_breaker_opens_half_opens_and_recovers() -> None:
    breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=10)

    def fail() -> None:
        raise RuntimeError("offline")

    with pytest.raises(RuntimeError):
        breaker.call(fail)
    with pytest.raises(RuntimeError):
        breaker.call(fail)
    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "blocked")

    with patch("common.circuit_breaker.time.monotonic", return_value=(breaker._last_failure_time or 0) + 11):
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitState.CLOSED
    assert breaker._failure_count == 0


def test_half_open_call_limit_and_decorator() -> None:
    breaker = CircuitBreaker("test", half_open_max_calls=1)
    breaker._state = CircuitState.HALF_OPEN
    breaker._half_open_calls = 1
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: None)

    decorated_breaker = CircuitBreaker("decorator")

    @decorated_breaker
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


@pytest.mark.asyncio
async def test_async_breaker_success_failure_exclusion_and_open() -> None:
    breaker = CircuitBreaker("async", failure_threshold=1)

    async def success() -> str:
        return "ok"

    async def fail() -> None:
        raise RuntimeError("offline")

    assert await breaker.async_call(success) == "ok"
    with pytest.raises(RuntimeError):
        await breaker.async_call(fail)
    with pytest.raises(CircuitOpenError):
        await breaker.async_call(success)

    excluded = CircuitBreaker("excluded", failure_threshold=1, excluded_exceptions=(ExpectedClientError,))

    async def expected() -> None:
        raise ExpectedClientError

    with pytest.raises(ExpectedClientError):
        await excluded.async_call(expected)
    assert excluded.state == CircuitState.CLOSED

"""Circuit breaker implementation for external API calls."""

import time
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

from common.exceptions import CircuitOpenError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class CircuitState(Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker for protecting external service calls.

    Args:
        name: Identifier for this circuit (used in logs and cache keys).
        failure_threshold: Number of failures before opening the circuit.
        recovery_timeout: Seconds to wait before attempting recovery.
        half_open_max_calls: Max calls allowed in HALF_OPEN state.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state, transitioning OPEN -> HALF_OPEN if timeout elapsed."""
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit_half_open", circuit=self.name)
        return self._state

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker.

        Raises:
            CircuitOpenError: If the circuit is open.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit '{self.name}' is open.")

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                raise CircuitOpenError(f"Circuit '{self.name}' is in half-open state, max probe calls reached.")
            self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        logger.info("circuit_closed", circuit=self.name)

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "circuit_opened",
                circuit=self.name,
                failures=self._failure_count,
            )

    def __call__(self, func: Callable) -> Callable:
        """Use as a decorator."""
        import functools

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)

        return wrapper

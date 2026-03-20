"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Circuit breaker pattern for resilient API calls
Project : CW1 - Value + News Sentiment Strategy

Implements the circuit breaker pattern (Nygard, 2007) to prevent
cascading failures when external APIs (GDELT, Yahoo Finance) are
unavailable or degraded.

States:
  CLOSED    -> Normal operation; failures increment a counter
  OPEN      -> After threshold consecutive failures, all calls
               are short-circuited for a recovery period
  HALF_OPEN -> After recovery timeout, one probe call is allowed.
               If it succeeds the circuit closes; otherwise it re-opens.

Thread-safe: all state mutations are protected by ``threading.Lock``
to support concurrent workers in ``ThreadPoolExecutor``.

References:
  - Nygard, M. (2007). Release It! Pragmatic Bookshelf.
  - AWS Architecture Blog: "Exponential Backoff And Jitter" (2015)
"""

import threading
import time
from enum import Enum

from modules.utils.logger import pipeline_logger


class CircuitState(Enum):
    """Possible states of a circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Circuit breaker for wrapping unreliable external API calls.

    :param name: Identifier for this circuit (e.g. 'gdelt', 'yf_news')
    :type name: str
    :param failure_threshold: Consecutive failures before opening circuit
    :type failure_threshold: int
    :param recovery_timeout: Seconds to wait before allowing a probe
    :type recovery_timeout: float
    :param success_threshold: Successful probes needed to fully close
    :type success_threshold: int

    Example::

        >>> cb = CircuitBreaker('gdelt', failure_threshold=10, recovery_timeout=30)
        >>> if cb.allow_request():
        ...     try:
        ...         result = fetch_from_api()
        ...         cb.record_success()
        ...     except Exception:
        ...         cb.record_failure()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._total_trips = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state, accounting for recovery timeout.

        :return: Current state of the circuit breaker
        :rtype: CircuitState
        """
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    pipeline_logger.info(
                        "[CircuitBreaker:%s] OPEN -> HALF_OPEN after %.0fs recovery",
                        self.name,
                        elapsed,
                    )
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through.

        :return: True if the circuit is closed or half-open (probe allowed)
        :rtype: bool
        """
        current = self.state
        return current in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        """Record a successful API call.

        In HALF_OPEN state, increments the success counter.
        After ``success_threshold`` consecutive successes, the circuit
        fully closes and resets all counters.
        """
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    pipeline_logger.info(
                        "[CircuitBreaker:%s] HALF_OPEN -> CLOSED (recovered)",
                        self.name,
                    )
            else:
                self._failure_count = 0

    def record_failure(self):
        """Record a failed API call.

        Increments the failure counter. If the threshold is reached,
        the circuit transitions to OPEN and logs the event.
        In HALF_OPEN state, a single failure re-opens the circuit.
        """
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._total_trips += 1
                pipeline_logger.warning(
                    "[CircuitBreaker:%s] HALF_OPEN -> OPEN (probe failed, trip #%d)",
                    self.name,
                    self._total_trips,
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._total_trips += 1
                pipeline_logger.warning(
                    "[CircuitBreaker:%s] CLOSED -> OPEN after %d consecutive failures (trip #%d)",
                    self.name,
                    self._failure_count,
                    self._total_trips,
                )

    def reset(self):
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            pipeline_logger.info("[CircuitBreaker:%s] Manually reset to CLOSED", self.name)

    def to_dict(self) -> dict:
        """Export circuit breaker state for metrics reporting.

        :return: Dictionary with current state and counters
        :rtype: dict
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_trips": self._total_trips,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }

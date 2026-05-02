"""Unit tests for modules.utils.resilience.

Tests cover:
- CircuitBreaker state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- TokenBucket acquire/refill logic (in-memory fallback, no Redis required)
- retry_with_backoff decorator behaviour
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from modules.utils.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    TokenBucket,
    get_circuit_breaker,
    get_token_bucket,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cb(**kwargs) -> CircuitBreaker:
    """Return a CircuitBreaker that always uses in-memory state (no Redis)."""
    cb = CircuitBreaker("test_service", **kwargs)
    return cb


def _force_no_redis(monkeypatch):
    """Patch _get_redis to always return None (simulate Redis unavailable)."""
    monkeypatch.setattr("modules.utils.resilience._get_redis", lambda: None)
    monkeypatch.setattr("modules.utils.resilience._redis_client", None)


# ---------------------------------------------------------------------------
# CircuitBreaker: state transitions
# ---------------------------------------------------------------------------

class TestCircuitBreakerTransitions:
    def test_initial_state_is_closed(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=3, recovery_timeout=1)
        assert cb._get_state() == CircuitState.CLOSED

    def test_closed_to_open_after_threshold(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb._get_state() == CircuitState.OPEN

    def test_open_raises_circuit_open_error(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=1, recovery_timeout=999)
        cb.record_failure()
        assert cb._get_state() == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.allow_request()

    def test_open_transitions_to_half_open_after_timeout(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        # recovery_timeout=0 means immediate transition
        state = cb._maybe_transition_to_half_open()
        assert state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        cb._mem_state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb._get_state() == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        cb._mem_state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb._get_state() == CircuitState.OPEN

    def test_half_open_probe_limit_is_enforced(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=1, recovery_timeout=0, half_open_max_calls=2)
        cb._mem_state = CircuitState.HALF_OPEN
        assert cb.allow_request() is True
        assert cb.allow_request() is True
        with pytest.raises(CircuitOpenError):
            cb.allow_request()

    def test_success_resets_failure_counter(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=5, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb._get_failures() == 2
        cb.record_success()
        assert cb._get_failures() == 0

    def test_protect_decorator_records_failure(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=3, recovery_timeout=60)

        @cb.protect
        def failing_func():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            failing_func()

        assert cb._get_failures() == 1

    def test_protect_decorator_records_success(self, monkeypatch):
        _force_no_redis(monkeypatch)
        cb = _make_cb(failure_threshold=3, recovery_timeout=60)

        @cb.protect
        def ok_func():
            return 42

        result = ok_func()
        assert result == 42
        assert cb._get_failures() == 0


# ---------------------------------------------------------------------------
# TokenBucket: acquire / refill
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_first_acquire_succeeds_immediately(self, monkeypatch):
        monkeypatch.setattr("modules.utils.resilience._get_redis", lambda: None)
        tb = TokenBucket("test", rate=10, period=1)
        # Should not raise
        tb.acquire(timeout=5.0)

    def test_tokens_deplete_and_refill(self, monkeypatch):
        monkeypatch.setattr("modules.utils.resilience._get_redis", lambda: None)
        tb = TokenBucket("test2", rate=2, period=1)
        # Drain 2 tokens
        tb.acquire(timeout=5.0)
        tb.acquire(timeout=5.0)
        assert tb._mem_tokens < 1.0
        # After 1 second, tokens should refill
        time.sleep(1.1)
        tb.acquire(timeout=5.0)  # Should succeed after refill

    def test_acquire_raises_timeout_when_no_tokens(self, monkeypatch):
        monkeypatch.setattr("modules.utils.resilience._get_redis", lambda: None)
        tb = TokenBucket("test3", rate=1, period=60)
        tb._mem_tokens = 0.0  # Drain manually
        with pytest.raises(TimeoutError):
            tb.acquire(timeout=0.1)


# ---------------------------------------------------------------------------
# retry_with_backoff
# ---------------------------------------------------------------------------

class TestRetryWithBackoff:
    def test_succeeds_on_first_attempt(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, service="test")
        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = func()
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, service="test")
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = func()
        assert result == "recovered"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        @retry_with_backoff(max_retries=2, base_delay=0.01, service="test")
        def always_fails():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            always_fails()

    def test_only_catches_specified_exceptions(self):
        @retry_with_backoff(
            max_retries=3,
            base_delay=0.01,
            exceptions=(ConnectionError,),
            service="test",
        )
        def func():
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            func()

    def test_no_args_decorator_form(self):
        call_count = 0

        @retry_with_backoff
        def func():
            nonlocal call_count
            call_count += 1
            return call_count

        result = func()
        assert result == 1

    def test_http_404_is_not_retried(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, service="test")
        def func():
            nonlocal call_count
            call_count += 1
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("not found", response=response)

        with pytest.raises(requests.HTTPError, match="not found"):
            func()
        assert call_count == 1

    def test_factory_singletons(self, monkeypatch):
        monkeypatch.setattr("modules.utils.resilience._get_redis", lambda: None)
        cb1 = get_circuit_breaker("singleton_test")
        cb2 = get_circuit_breaker("singleton_test")
        assert cb1 is cb2

        tb1 = get_token_bucket("singleton_tb")
        tb2 = get_token_bucket("singleton_tb")
        assert tb1 is tb2

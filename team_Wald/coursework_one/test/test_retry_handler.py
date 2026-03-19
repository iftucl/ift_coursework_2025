"""
Tests for circuit breaker, rate limiter, and retry handler utilities.

Covers:
  - CircuitBreaker state transitions and thread safety
  - TokenBucketRateLimiter token consumption and blocking
  - @retry decorator with configurable backoff strategies
"""

import threading
import time
from unittest.mock import MagicMock

from modules.utils.circuit_breaker import CircuitBreaker, CircuitState
from modules.utils.rate_limiter import TokenBucketRateLimiter
from modules.utils.retry_handler import _compute_delay, retry

# =========================================================================
# CircuitBreaker tests
# =========================================================================


class TestCircuitBreakerStates:
    """Tests for circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_requests(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert not cb.allow_request()

    def test_closed_allows_requests(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        assert cb.allow_request()

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_request(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.allow_request()

    def test_half_open_closes_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1, success_threshold=2)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        # After success reset, need 3 more failures to trip
        assert cb.state == CircuitState.CLOSED

    def test_reset_method(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_total_trips_counted(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb._total_trips == 1
        time.sleep(0.1)
        cb.record_failure()  # re-open from half-open
        assert cb._total_trips == 2

    def test_to_dict(self):
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout=30)
        d = cb.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "CLOSED"
        assert d["failure_threshold"] == 5
        assert d["recovery_timeout"] == 30

    def test_thread_safety(self):
        """Multiple threads recording failures concurrently."""
        cb = CircuitBreaker("test", failure_threshold=50)
        errors = []

        def record_failures():
            try:
                for _ in range(25):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert cb.state == CircuitState.OPEN


# =========================================================================
# TokenBucketRateLimiter tests
# =========================================================================


class TestTokenBucketRateLimiter:
    """Tests for token bucket rate limiter."""

    def test_initial_tokens_equal_capacity(self):
        rl = TokenBucketRateLimiter(rate=10.0, capacity=5, name="test")
        assert rl.available_tokens <= 5.0

    def test_acquire_consumes_token(self):
        rl = TokenBucketRateLimiter(rate=10.0, capacity=5, name="test")
        wait = rl.acquire()
        assert wait == 0.0
        assert rl.available_tokens < 5.0

    def test_acquire_blocks_when_empty(self):
        rl = TokenBucketRateLimiter(rate=100.0, capacity=2, name="test")
        rl.acquire()
        rl.acquire()
        start = time.monotonic()
        rl.acquire()
        elapsed = time.monotonic() - start
        # Should have waited for at least a small amount
        assert elapsed >= 0.005

    def test_refill_over_time(self):
        rl = TokenBucketRateLimiter(rate=100.0, capacity=5, name="test")
        for _ in range(5):
            rl.acquire()
        time.sleep(0.05)  # 5 tokens at 100/s
        assert rl.available_tokens >= 3.0

    def test_capacity_not_exceeded(self):
        rl = TokenBucketRateLimiter(rate=1000.0, capacity=3, name="test")
        time.sleep(0.1)  # Would produce 100 tokens at 1000/s
        assert rl.available_tokens <= 3.0

    def test_to_dict(self):
        rl = TokenBucketRateLimiter(rate=5.0, capacity=10, name="test_api")
        d = rl.to_dict()
        assert d["name"] == "test_api"
        assert d["rate"] == 5.0
        assert d["capacity"] == 10
        assert "available_tokens" in d
        assert "total_waits" in d

    def test_thread_safety(self):
        """Multiple threads acquiring tokens concurrently."""
        rl = TokenBucketRateLimiter(rate=100.0, capacity=50, name="test")
        acquired = [0]
        lock = threading.Lock()

        def acquire_tokens():
            for _ in range(10):
                rl.acquire()
                with lock:
                    acquired[0] += 1

        threads = [threading.Thread(target=acquire_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert acquired[0] == 50

    def test_zero_wait_when_tokens_available(self):
        rl = TokenBucketRateLimiter(rate=10.0, capacity=10, name="test")
        wait = rl.acquire()
        assert wait == 0.0


# =========================================================================
# @retry decorator tests
# =========================================================================


class TestRetryDecorator:
    """Tests for the @retry decorator."""

    def test_no_retry_on_success(self):
        call_count = [0]

        @retry(max_attempts=3, jitter=False)
        def succeed():
            call_count[0] += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count[0] == 1

    def test_retries_on_exception(self):
        call_count = [0]

        @retry(max_attempts=3, backoff_base=0.01, jitter=False)
        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient")
            return "ok"

        result = fail_twice()
        assert result == "ok"
        assert call_count[0] == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, backoff_base=0.01, jitter=False)
        def always_fail():
            raise RuntimeError("permanent")

        try:
            always_fail()
            assert False, "Should have raised"
        except RuntimeError as e:
            assert str(e) == "permanent"

    def test_only_retries_specified_exceptions(self):
        call_count = [0]

        @retry(
            max_attempts=3,
            backoff_base=0.01,
            jitter=False,
            retryable_exceptions=(ValueError,),
        )
        def raise_type_error():
            call_count[0] += 1
            raise TypeError("not retryable")

        try:
            raise_type_error()
        except TypeError:
            pass

        assert call_count[0] == 1  # No retries for TypeError

    def test_exponential_backoff_strategy(self):
        delay = _compute_delay(attempt=2, base=2.0, strategy="exponential", max_delay=60.0, jitter=False)
        assert delay == 4.0  # 2^2

    def test_linear_backoff_strategy(self):
        delay = _compute_delay(attempt=3, base=2.0, strategy="linear", max_delay=60.0, jitter=False)
        assert delay == 6.0  # 2*3

    def test_constant_backoff_strategy(self):
        delay = _compute_delay(attempt=5, base=2.0, strategy="constant", max_delay=60.0, jitter=False)
        assert delay == 2.0

    def test_max_delay_cap(self):
        delay = _compute_delay(attempt=10, base=2.0, strategy="exponential", max_delay=30.0, jitter=False)
        assert delay == 30.0

    def test_jitter_applied(self):
        delays = set()
        for _ in range(10):
            d = _compute_delay(attempt=1, base=2.0, strategy="exponential", max_delay=60.0, jitter=True)
            delays.add(round(d, 4))
        # With jitter, we should get varied delays (not all 2.0)
        assert len(delays) > 1

    def test_on_retry_callback(self):
        callback = MagicMock()
        call_count = [0]

        @retry(max_attempts=3, backoff_base=0.01, jitter=False, on_retry=callback)
        def fail_once():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("transient")
            return "ok"

        result = fail_once()
        assert result == "ok"
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == 1  # attempt number
        assert isinstance(args[1], ValueError)  # exception
        assert isinstance(args[2], float)  # delay

    def test_preserves_function_name(self):
        @retry(max_attempts=2)
        def my_function():
            return True

        assert my_function.__name__ == "my_function"

    def test_stores_retry_metadata(self):
        @retry(max_attempts=5, backoff_strategy="linear")
        def my_function():
            return True

        assert my_function._max_attempts == 5
        assert my_function._backoff_strategy == "linear"

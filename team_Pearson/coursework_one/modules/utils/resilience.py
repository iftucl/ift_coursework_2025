"""Resilience primitives: Circuit Breaker, Token Bucket, and retry with backoff.

State is stored in Redis so it is shared across processes and survives pipeline
restarts. A pure-Python in-memory fallback is still available for local tests,
but production runs can require Redis explicitly via ``REDIS_REQUIRED=true``.

Typical usage::

    from modules.utils.resilience import get_circuit_breaker, get_token_bucket

    cb  = get_circuit_breaker("finnhub")
    tb  = get_token_bucket("finnhub", rate=60, period=60)

    @cb.protect
    def fetch_news(symbol: str):
        tb.acquire()          # blocks until a token is available
        return requests.get(...)
"""

from __future__ import annotations

import logging
import os
import random
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)
_JITTER_RNG = random.SystemRandom()

# ---------------------------------------------------------------------------
# Redis connection (lazy, shared)
# ---------------------------------------------------------------------------

_redis_client: Any = None
_token_bucket_script: Any = None


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a bool-like environment variable."""
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _get_redis() -> Any:
    """Return a shared Redis client, or ``None`` when Redis is unreachable.

    :returns: ``redis.Redis`` instance or ``None``.
    :rtype: redis.Redis | None
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        url = str(os.getenv("REDIS_URL", "")).strip()
        db = int(os.getenv("REDIS_DB", "0"))
        password = str(os.getenv("REDIS_PASSWORD", "")).strip() or None
        decode_responses = True
        socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))
        connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2"))
        health_check_interval = int(os.getenv("REDIS_HEALTHCHECK_INTERVAL", "30"))

        if url:
            client = redis.from_url(
                url,
                db=db,
                password=password,
                decode_responses=decode_responses,
                socket_timeout=socket_timeout,
                socket_connect_timeout=connect_timeout,
                health_check_interval=health_check_interval,
                retry_on_timeout=True,
            )
            target = url
        else:
            host = os.getenv("REDIS_HOST", "localhost")
            port = int(os.getenv("REDIS_PORT", "6380"))
            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=decode_responses,
                socket_timeout=socket_timeout,
                socket_connect_timeout=connect_timeout,
                health_check_interval=health_check_interval,
                retry_on_timeout=True,
            )
            target = f"{host}:{port}/{db}"
        client.ping()
        _redis_client = client
        logger.debug("resilience: Redis connected at %s", target)
        return _redis_client
    except Exception as exc:
        if _env_flag("REDIS_REQUIRED") and os.getenv("CW1_TEST_MODE") != "1":
            raise RuntimeError(f"Redis is required but unavailable: {exc}") from exc
        logger.warning("resilience: Redis unavailable (%s). Falling back to in-memory state.", exc)
        return None


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitState(str, Enum):
    """Three states of the circuit breaker pattern."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN.

    :param service: Name of the downstream service.
    :type service: str
    """

    def __init__(self, service: str) -> None:
        super().__init__(f"Circuit OPEN for service '{service}'. Call blocked.")
        self.service = service


class CircuitBreaker:
    """Three-state circuit breaker with Redis-backed persistence.

    State machine::

        CLOSED  --[N failures]--> OPEN
        OPEN    --[timeout]-----> HALF_OPEN
        HALF_OPEN --[success]--> CLOSED
        HALF_OPEN --[failure]--> OPEN

    :param service: Logical name of the protected service (used as Redis key prefix).
    :param failure_threshold: Consecutive failures before opening the circuit.
    :param recovery_timeout: Seconds to wait in OPEN state before trying HALF_OPEN.
    :param half_open_max_calls: Number of probe calls allowed in HALF_OPEN state.
    """

    def __init__(
        self,
        service: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 1,
    ) -> None:
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        # In-memory fallback state (used when Redis is unavailable).
        self._mem_state: str = CircuitState.CLOSED
        self._mem_failures: int = 0
        self._mem_opened_at: float = 0.0
        self._mem_half_open_calls: int = 0

    # -- Redis key helpers ---------------------------------------------------

    def _key(self, suffix: str) -> str:
        return f"cw1:cb:{self.service}:{suffix}"

    # -- State accessors (Redis-first, memory fallback) ---------------------

    def _get_state(self) -> CircuitState:
        r = _get_redis()
        if r is None:
            return CircuitState(self._mem_state)
        raw = r.get(self._key("state"))
        return CircuitState(raw) if raw else CircuitState.CLOSED

    def _set_state(self, state: CircuitState) -> None:
        r = _get_redis()
        if r is None:
            self._mem_state = state
            return
        r.set(self._key("state"), state, ex=86400)  # 24 h TTL

    def _get_failures(self) -> int:
        r = _get_redis()
        if r is None:
            return self._mem_failures
        raw = r.get(self._key("failures"))
        return int(raw) if raw else 0

    def _incr_failures(self) -> int:
        r = _get_redis()
        if r is None:
            self._mem_failures += 1
            return self._mem_failures
        count = r.incr(self._key("failures"))
        r.expire(self._key("failures"), 86400)
        return int(count)

    def _reset_failures(self) -> None:
        r = _get_redis()
        if r is None:
            self._mem_failures = 0
            return
        r.delete(self._key("failures"))

    def _get_opened_at(self) -> float:
        r = _get_redis()
        if r is None:
            return self._mem_opened_at
        raw = r.get(self._key("opened_at"))
        return float(raw) if raw else 0.0

    def _set_opened_at(self, ts: float) -> None:
        r = _get_redis()
        if r is None:
            self._mem_opened_at = ts
            return
        r.set(self._key("opened_at"), str(ts), ex=86400)

    def _get_half_open_calls(self) -> int:
        r = _get_redis()
        if r is None:
            return self._mem_half_open_calls
        raw = r.get(self._key("half_open_calls"))
        return int(raw) if raw else 0

    def _incr_half_open_calls(self) -> int:
        r = _get_redis()
        if r is None:
            self._mem_half_open_calls += 1
            return self._mem_half_open_calls
        count = r.incr(self._key("half_open_calls"))
        r.expire(self._key("half_open_calls"), 86400)
        return int(count)

    def _reset_half_open_calls(self) -> None:
        r = _get_redis()
        if r is None:
            self._mem_half_open_calls = 0
            return
        r.delete(self._key("half_open_calls"))

    # -- Core logic ----------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> CircuitState:
        """Transition OPEN → HALF_OPEN if recovery_timeout has elapsed."""
        opened_at = self._get_opened_at()
        if opened_at > 0 and (time.time() - opened_at) >= self.recovery_timeout:
            logger.info("circuit_breaker service=%s OPEN->HALF_OPEN", self.service)
            self._set_state(CircuitState.HALF_OPEN)
            self._reset_half_open_calls()
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow_request(self) -> bool:
        """Return ``True`` if the circuit allows the call to proceed.

        :returns: Whether the call should be attempted.
        :rtype: bool
        :raises CircuitOpenError: When the circuit is firmly OPEN.
        """
        state = self._get_state()
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            state = self._maybe_transition_to_half_open()
            if state == CircuitState.OPEN:
                raise CircuitOpenError(self.service)
        if state == CircuitState.HALF_OPEN:
            calls = self._incr_half_open_calls()
            if calls > self.half_open_max_calls:
                raise CircuitOpenError(self.service)
        return True

    def record_success(self) -> None:
        """Record a successful call; close the circuit if in HALF_OPEN.

        :rtype: None
        """
        state = self._get_state()
        if state == CircuitState.HALF_OPEN:
            logger.info("circuit_breaker service=%s HALF_OPEN->CLOSED", self.service)
            self._reset_failures()
            self._reset_half_open_calls()
            self._set_state(CircuitState.CLOSED)
        elif state == CircuitState.CLOSED:
            self._reset_failures()

    def record_failure(self) -> None:
        """Record a failed call; open the circuit when threshold is reached.

        :rtype: None
        """
        state = self._get_state()
        if state == CircuitState.HALF_OPEN:
            logger.warning(
                "circuit_breaker service=%s HALF_OPEN->OPEN (probe failed)", self.service
            )
            self._reset_half_open_calls()
            self._set_state(CircuitState.OPEN)
            self._set_opened_at(time.time())
            return

        failures = self._incr_failures()
        logger.debug("circuit_breaker service=%s failures=%s", self.service, failures)
        if failures >= self.failure_threshold:
            logger.error(
                "circuit_breaker service=%s CLOSED->OPEN failures=%s threshold=%s",
                self.service,
                failures,
                self.failure_threshold,
            )
            self._set_state(CircuitState.OPEN)
            self._set_opened_at(time.time())

    def protect(self, func: Callable) -> Callable:
        """Decorator: wrap *func* with circuit-breaker protection.

        :param func: The function to protect.
        :type func: Callable
        :returns: Wrapped function.
        :rtype: Callable
        """

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.allow_request()  # raises CircuitOpenError if OPEN
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except CircuitOpenError:
                raise
            except Exception:
                self.record_failure()
                raise

        return wrapper


# ---------------------------------------------------------------------------
# Token Bucket (rate limiter)
# ---------------------------------------------------------------------------


class TokenBucket:
    """Redis-backed token-bucket rate limiter.

    Tokens refill at ``rate`` tokens per ``period`` seconds.  A call to
    :meth:`acquire` blocks (with a short sleep loop) until a token is
    available.

    :param name: Logical name (used as Redis key prefix).
    :param rate: Number of tokens added per period.
    :param period: Refill interval in seconds.
    """

    def __init__(self, name: str, *, rate: int = 60, period: int = 60) -> None:
        self.name = name
        self.rate = rate
        self.period = period
        # In-memory fallback
        self._mem_tokens: float = float(rate)
        self._mem_last_refill: float = time.time()

    def _key(self) -> str:
        return f"cw1:tb:{self.name}"

    def _refill_and_consume_redis(self, r: Any) -> bool:
        """Atomic token-bucket consume via Lua script.

        :param r: Redis client.
        :returns: ``True`` if a token was consumed.
        :rtype: bool
        """
        global _token_bucket_script
        if _token_bucket_script is None:
            lua_script = """
            local key     = KEYS[1]
            local rate    = tonumber(ARGV[1])
            local period  = tonumber(ARGV[2])
            local now     = tonumber(ARGV[3])

            local data      = redis.call('HMGET', key, 'tokens', 'last_refill')
            local tokens    = tonumber(data[1]) or rate
            local last_ref  = tonumber(data[2]) or now

            local elapsed   = now - last_ref
            local refill    = math.floor(elapsed / period * rate)
            tokens = math.min(rate, tokens + refill)

            if tokens >= 1 then
                tokens = tokens - 1
                redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
                redis.call('EXPIRE', key, period * 2)
                return 1
            end
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
            redis.call('EXPIRE', key, period * 2)
            return 0
            """
            _token_bucket_script = r.register_script(lua_script)
        result = _token_bucket_script(
            keys=[self._key()], args=[self.rate, self.period, time.time()]
        )
        return bool(result)

    def _refill_and_consume_mem(self) -> bool:
        """Pure-Python fallback token bucket.

        :returns: ``True`` if a token was consumed.
        :rtype: bool
        """
        now = time.time()
        elapsed = now - self._mem_last_refill
        refill = elapsed / self.period * self.rate
        self._mem_tokens = min(float(self.rate), self._mem_tokens + refill)
        self._mem_last_refill = now
        if self._mem_tokens >= 1:
            self._mem_tokens -= 1
            return True
        return False

    def acquire(self, timeout: float = 120.0) -> None:
        """Block until a token is available, then consume it.

        :param timeout: Maximum seconds to wait before raising ``TimeoutError``.
        :type timeout: float
        :raises TimeoutError: If no token becomes available within *timeout* seconds.
        :rtype: None
        """
        deadline = time.time() + timeout
        sleep_interval = max(self.period / self.rate, 0.01)  # seconds per token at full rate
        r = _get_redis()

        while time.time() < deadline:
            consumed = (
                self._refill_and_consume_redis(r)
                if r is not None
                else self._refill_and_consume_mem()
            )
            if consumed:
                return
            time.sleep(max(0.0, min(sleep_interval, deadline - time.time())))

        raise TimeoutError(f"TokenBucket '{self.name}': could not acquire token within {timeout}s")


# ---------------------------------------------------------------------------
# Exponential backoff with jitter
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    func: Optional[F] = None,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    service: str = "unknown",
) -> Any:
    """Decorator: retry *func* with full-jitter exponential backoff.

    Can be used with or without arguments::

        @retry_with_backoff
        def call_api(): ...

        @retry_with_backoff(max_retries=5, base_delay=2.0)
        def call_api(): ...

    :param max_retries: Maximum number of retry attempts after the first failure.
    :param base_delay: Base delay in seconds for exponential backoff.
    :param max_delay: Maximum delay cap in seconds.
    :param exceptions: Tuple of exception types that trigger a retry.
    :param service: Label used in log messages.
    :returns: Decorated function or decorator factory.
    """

    def decorator(f: F) -> F:
        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception = RuntimeError("No attempts made")
            for attempt in range(max_retries + 1):
                try:
                    return f(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    if status_code in {400, 401, 403, 404}:
                        raise
                    if attempt == max_retries:
                        break
                    # Full-jitter backoff: sleep in [0, min(cap, base * 2^attempt)]
                    cap = min(max_delay, base_delay * (2**attempt))
                    delay = _JITTER_RNG.uniform(0, cap)
                    logger.warning(
                        "retry service=%s attempt=%s/%s delay=%.1fs error=%s",
                        service,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            raise last_exc

        return wrapper  # type: ignore[return-value]

    if func is not None:
        # Called as @retry_with_backoff (no args)
        return decorator(func)
    # Called as @retry_with_backoff(...) with args
    return decorator


# ---------------------------------------------------------------------------
# Module-level factory helpers
# ---------------------------------------------------------------------------

_circuit_breakers: dict[str, CircuitBreaker] = {}
_token_buckets: dict[str, TokenBucket] = {}


def get_circuit_breaker(
    service: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
) -> CircuitBreaker:
    """Return (or create) a named :class:`CircuitBreaker`.

    :param service: Logical service name.
    :param failure_threshold: Failures before opening the circuit.
    :param recovery_timeout: Seconds to stay OPEN before attempting HALF_OPEN.
    :returns: Shared :class:`CircuitBreaker` instance for *service*.
    :rtype: CircuitBreaker
    """
    if service not in _circuit_breakers:
        _circuit_breakers[service] = CircuitBreaker(
            service,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _circuit_breakers[service]


def get_token_bucket(
    name: str,
    *,
    rate: int = 60,
    period: int = 60,
) -> TokenBucket:
    """Return (or create) a named :class:`TokenBucket`.

    :param name: Logical name for this rate limiter.
    :param rate: Tokens per *period*.
    :param period: Refill period in seconds.
    :returns: Shared :class:`TokenBucket` instance for *name*.
    :rtype: TokenBucket
    """
    if name not in _token_buckets:
        _token_buckets[name] = TokenBucket(name, rate=rate, period=period)
    return _token_buckets[name]

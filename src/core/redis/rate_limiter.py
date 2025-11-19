"""
Redis Rate Limiter for Lumen (2025)

Purpose
-------
Production-grade, **distributed** rate limiting built on top of Redis with:

- Token Bucket (smooth, burst-friendly)
- Fixed Window (simple, fast)
- Config-driven defaults and behavior
- Graceful degradation when Redis is unavailable or unhealthy
- Structured logging and latency metrics via RedisMetrics
- Integration with RedisResilience (circuit breaker / retry) without
  duplicating stateful operations

Responsibilities
----------------
- Provide a **pure infrastructure** rate limiting primitive.
- Expose a small, clear async API for:
  - `check_limit` → bool allow/deny
  - `check_or_raise` → raises `RateLimitExceededError` on deny
  - `get_remaining` → remaining tokens/requests in current bucket/window
  - `reset_limit` → clear all limit state for a logical key
  - `get_status` → configuration + runtime snapshot for observability
- Remain business-logic agnostic (no player/guild/domain knowledge).

Lumen 2025 Compliance
---------------------
- Fully async, production-ready infra component.
- No cross-layer pollution (uses RedisService + ConfigManager only).
- All behavior is **config-driven**, no gameplay values are hardcoded.
- Strong observability:
  - Structured logs on initialization, failures, and limit breaches.
  - Per-operation latency metrics via `RedisMetrics`.
  - Uses `RedisResilience` for circuit breaker behavior with **no retries**
    for rate-limit operations (to avoid double-charging).
- Clear, domain-specific exception (`RateLimitExceededError`) for services
  and cogs to consume.

Design Decisions
----------------
- Uses `RedisService` singleton for:
  - Access to the async Redis client.
  - Access to `RedisResilience` (circuit breaker).
- Token Bucket implementation:
  - Single Lua script for atomic refill + consume.
  - TTL for bucket key is configurable (`bucket_ttl_seconds`).
- Fixed Window implementation:
  - Uses `INCRBY` to support multi-token operations.
  - TTL for each window key is configurable via multiplier.
- Fallback behavior is controlled by config:
  - `"allow"` (default): fail-open on infra issues.
  - `"deny"`: fail-closed when Redis / script errors occur.

Dependencies
------------
- `src.core.redis.service.RedisService`
- `src.core.redis.metrics.RedisMetrics`
- `src.core.config.ConfigManager`
- `src.core.logging.logger.get_logger`
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Callable, Awaitable, Any

from src.core.config import ConfigManager
from src.core.logging.logger import get_logger
from src.core.redis.metrics import RedisMetrics

if TYPE_CHECKING:
    from redis.asyncio.client import Redis as AsyncRedis
    from src.core.redis.service import RedisService
    from src.core.redis.resilience import RedisResilience


logger = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Exceptions
# ════════════════════════════════════════════════════════════════════════


class RateLimitExceededError(Exception):
    """Raised when a rate limit has been exceeded for a given logical key."""

    def __init__(self, key: str, algorithm: str, rate: int, period_seconds: int, tokens: int) -> None:
        message = (
            f"Rate limit exceeded for key='{key}' "
            f"(algorithm={algorithm}, rate={rate}, period_seconds={period_seconds}, tokens={tokens})"
        )
        super().__init__(message)
        self.key = key
        self.algorithm = algorithm
        self.rate = rate
        self.period_seconds = period_seconds
        self.tokens = tokens


# ════════════════════════════════════════════════════════════════════════
# Redis Rate Limiter
# ════════════════════════════════════════════════════════════════════════


class RedisRateLimiter:
    """
    Distributed rate limiter using Redis (token bucket & fixed window).

    Characteristics
    ---------------
    - Safe in multi-instance deployments (single shared Redis).
    - Fully async.
    - Token bucket implemented via atomic Lua script.
    - Fixed window via simple counters.
    - Uses RedisResilience for circuit breaker behavior **without retries**,
      avoiding double-charging in rate limit logic.
    """

    # ────────────────────────────────────────────────────────────────────
    # Lua Token Bucket Script
    # ────────────────────────────────────────────────────────────────────
    #
    # KEYS:
    #   1: bucket key
    #
    # ARGV:
    #   1: max_tokens
    #   2: refill_rate (tokens per second)
    #   3: requested (tokens to consume)
    #   4: now (current timestamp, seconds)
    #   5: ttl_seconds (expiration for bucket key)
    #
    # Returns:
    #   1 -> allowed (requested tokens consumed)
    #   0 -> denied  (not enough tokens available after refill)
    #
    _LUA_TOKEN_BUCKET = """
    local key = KEYS[1]
    local max_tokens = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local requested = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])
    local ttl_seconds = tonumber(ARGV[5])

    local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
    local tokens = tonumber(bucket[1])
    local last_refill = tonumber(bucket[2])

    if tokens == nil or last_refill == nil then
        tokens = max_tokens
        last_refill = now
    end

    if now < last_refill then
        -- Clock skew safety: do not go backwards
        last_refill = now
    end

    local time_passed = now - last_refill
    if time_passed < 0 then
        time_passed = 0
    end

    local new_tokens = tokens + (time_passed * refill_rate)
    if new_tokens > max_tokens then
        new_tokens = max_tokens
    end

    local allowed = 0

    if new_tokens >= requested then
        new_tokens = new_tokens - requested
        allowed = 1
    end

    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    if ttl_seconds and ttl_seconds > 0 then
        redis.call('EXPIRE', key, ttl_seconds)
    end

    return allowed
    """

    # ════════════════════════════════════════════════════════════════════
    # Initialization
    # ════════════════════════════════════════════════════════════════════

    def __init__(self, redis_service: type[RedisService], config_manager: ConfigManager) -> None:
        """
        Create a Redis-backed rate limiter bound to the core RedisService.

        Parameters
        ----------
        redis_service : type[RedisService]
            The RedisService singleton type used to obtain the client and
            resilience layer.
        config_manager : ConfigManager
            The config manager instance to use for configuration
        """
        self._redis_service: type[RedisService] = redis_service
        self._config_manager = config_manager

        # Core behavior configuration
        algorithm = self._get_config_str("core.redis.rate_limiter.algorithm", "token_bucket").strip().lower()
        if algorithm not in {"token_bucket", "fixed_window"}:
            logger.warning(
                "Unsupported rate limit algorithm configured; falling back to token_bucket",
                extra={"configured_algorithm": algorithm},
            )
            algorithm = "token_bucket"
        self._algorithm: str = algorithm

        self._default_rate: int = self._get_config_int("core.redis.rate_limiter.default_rate", 10)
        self._default_period_seconds: int = self._get_config_int(
            "core.redis.rate_limiter.default_period_sec",
            60,
        )

        fallback_mode = self._get_config_str("core.redis.rate_limiter.fallback_mode", "allow").strip().lower()
        if fallback_mode not in {"allow", "deny"}:
            logger.warning(
                "Unsupported rate limiter fallback_mode; defaulting to 'allow'",
                extra={"configured_fallback_mode": fallback_mode},
            )
            fallback_mode = "allow"
        self._fallback_mode: str = fallback_mode

        # Token bucket expiry configuration
        self._bucket_ttl_seconds: int = self._get_config_int(
            "core.redis.rate_limiter.bucket_ttl_seconds",
            3600,
        )

        # Fixed window expiry & scan configuration
        self._fixed_window_ttl_multiplier: int = self._get_config_int(
            "core.redis.rate_limiter.fixed_window_ttl_multiplier",
            2,
        )
        self._scan_batch_size: int = self._get_config_int(
            "core.redis.rate_limiter.scan_batch_size",
            100,
        )

        # Resilience behavior (no retries by default for rate limiting)
        self._max_attempts: int = self._get_config_int(
            "core.redis.rate_limiter.max_retry_attempts",
            1,
        )

        logger.debug(
            "RedisRateLimiter initialized",
            extra={
                "algorithm": self._algorithm,
                "default_rate": self._default_rate,
                "default_period_seconds": self._default_period_seconds,
                "fallback_mode": self._fallback_mode,
                "bucket_ttl_seconds": self._bucket_ttl_seconds,
                "fixed_window_ttl_multiplier": self._fixed_window_ttl_multiplier,
                "scan_batch_size": self._scan_batch_size,
                "max_attempts": self._max_attempts,
            },
        )

    # ════════════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════════════

    async def check_limit(
        self,
        key: str,
        rate: Optional[int] = None,
        period_seconds: Optional[int] = None,
        tokens: int = 1,
    ) -> bool:
        """
        Check if an operation is allowed under the configured rate limit.

        Parameters
        ----------
        key : str
            Logical rate limit key (e.g., "command:ping:user:123").
        rate : Optional[int]
            Maximum allowed operations per period. Defaults to configured
            `default_rate`.
        period_seconds : Optional[int]
            Length of the limiting period in seconds. Defaults to
            `default_period_sec` from config.
        tokens : int
            Number of "units" to consume in this operation (for bursty
            operations). Defaults to 1.

        Returns
        -------
        bool
            True if the operation is allowed, False if denied.
            If a Redis / resilience failure occurs, the decision is controlled
            by `fallback_mode` ("allow" or "deny").
        """
        effective_rate = rate if rate is not None else self._default_rate
        effective_period = period_seconds if period_seconds is not None else self._default_period_seconds

        try:
            if self._algorithm == "token_bucket":
                return await self._check_token_bucket(
                    key=key,
                    rate=effective_rate,
                    period_seconds=effective_period,
                    tokens=tokens,
                )

            if self._algorithm == "fixed_window":
                return await self._check_fixed_window(
                    key=key,
                    rate=effective_rate,
                    period_seconds=effective_period,
                    tokens=tokens,
                )

            # Unknown algorithm fallback (should be impossible after __init__ validation)
            logger.warning(
                "Unknown rate limit algorithm at runtime; defaulting to token_bucket",
                extra={"algorithm": self._algorithm},
            )
            return await self._check_token_bucket(
                key=key,
                rate=effective_rate,
                period_seconds=effective_period,
                tokens=tokens,
            )

        except Exception as exc:
            logger.error(
                "Rate limit check failed",
                extra={
                    "key": key,
                    "algorithm": self._algorithm,
                    "rate": effective_rate,
                    "period_seconds": effective_period,
                    "tokens": tokens,
                    "fallback_mode": self._fallback_mode,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

            if self._fallback_mode == "allow":
                logger.warning(
                    "ALLOWING operation due to rate limiter failure (fallback mode: allow)",
                    extra={"key": key},
                )
                return True

            logger.warning(
                "DENYING operation due to rate limiter failure (fallback mode: deny)",
                extra={"key": key},
            )
            return False

    async def check_or_raise(
        self,
        key: str,
        rate: Optional[int] = None,
        period_seconds: Optional[int] = None,
        tokens: int = 1,
    ) -> None:
        """
        Check a rate limit and raise `RateLimitExceededError` if denied.

        This is a convenience wrapper for service/cog layers that prefer
        exception-based control flow.

        Raises
        ------
        RateLimitExceededError
            If the limit is exceeded or if fallback_mode is "deny" and a
            Redis failure occurs.
        """
        effective_rate = rate if rate is not None else self._default_rate
        effective_period = period_seconds if period_seconds is not None else self._default_period_seconds

        allowed = await self.check_limit(
            key=key,
            rate=effective_rate,
            period_seconds=effective_period,
            tokens=tokens,
        )
        if not allowed:
            raise RateLimitExceededError(
                key=key,
                algorithm=self._algorithm,
                rate=effective_rate,
                period_seconds=effective_period,
                tokens=tokens,
            )

    async def reset_limit(self, key: str) -> None:
        """
        Reset both token bucket & fixed window limits for a logical key.

        This is primarily intended for administrative / testing use cases.
        """
        client: AsyncRedis = self._redis_service.client()
        pattern = f"ratelimit:fw:{key}:*"
        start_time = time.monotonic()

        try:
            # Delete token bucket state
            await client.delete(self._token_bucket_key(key))

            # Delete all fixed-window keys for this logical key
            cursor = 0
            batch_size = max(self._scan_batch_size, 1)

            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=batch_size)
                if keys:
                    # keys is a list[bytes|str]; delete accepts varargs
                    await client.delete(*keys)

                if cursor == 0:
                    break

            latency_ms = self._record_metric("RATELIMIT_RESET", start_time, success=True)
            logger.info(
                "Rate limit reset for key",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                },
            )

        except Exception as exc:
            latency_ms = self._record_metric("RATELIMIT_RESET", start_time, success=False)
            logger.error(
                "Failed to reset rate limit",
                extra={
                    "key": key,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )

    async def get_remaining(self, key: str, rate: Optional[int] = None) -> Optional[int]:
        """
        Get the remaining "tokens" or allowed operations for the current window/bucket.

        Behavior
        --------
        - Token Bucket:
          - Reads current `tokens` and `last_refill` and **virtually refills**
            based on elapsed time, without mutating Redis.
          - Returns a non-negative integer representing the best-effort view
            of remaining tokens (clamped to `[0, rate]`).
        - Fixed Window:
          - Reads the counter for the current window and returns
            `max(0, rate - current_count)`.
        - Unknown algorithm:
          - Returns None.

        Returns
        -------
        Optional[int]
            Remaining operations for the current bucket/window, or None if
            the algorithm is unknown or a failure occurred.
        """
        client: AsyncRedis = self._redis_service.client()
        effective_rate = rate if rate is not None else self._default_rate
        start_time = time.monotonic()

        try:
            if self._algorithm == "token_bucket":
                bucket_key = self._token_bucket_key(key)
                tokens_str, last_refill_str = await client.hmget(bucket_key, ["tokens", "last_refill"])  # type: ignore[misc]

                if tokens_str is None or last_refill_str is None:
                    # No state yet; full bucket by definition
                    latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=True)
                    logger.debug(
                        "Rate limiter bucket not yet initialized; assuming full capacity",
                        extra={
                            "key": key,
                            "algorithm": "token_bucket",
                            "rate": effective_rate,
                            "latency_ms": round(latency_ms, 2),
                        },
                    )
                    return effective_rate

                try:
                    tokens = float(tokens_str)
                    last_refill = float(last_refill_str)
                except (TypeError, ValueError):
                    # Corrupt state: fail to "unknown"
                    latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=False)
                    logger.warning(
                        "Corrupt token bucket state encountered while reading remaining tokens",
                        extra={
                            "key": key,
                            "tokens_raw": tokens_str,
                            "last_refill_raw": last_refill_str,
                            "latency_ms": round(latency_ms, 2),
                        },
                    )
                    return None

                now = self._now()
                if now < last_refill:
                    last_refill = now

                elapsed = max(0.0, now - last_refill)
                refill_rate = effective_rate / self._default_period_seconds if self._default_period_seconds > 0 else 0
                new_tokens = tokens + (elapsed * refill_rate)
                if new_tokens > effective_rate:
                    new_tokens = effective_rate

                remaining = max(0, int(new_tokens))
                latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=True)
                logger.debug(
                    "Computed remaining tokens for token bucket",
                    extra={
                        "key": key,
                        "rate": effective_rate,
                        "remaining": remaining,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
                return remaining

            if self._algorithm == "fixed_window":
                period_seconds = self._default_period_seconds
                window_key = self._fixed_window_key(key, period_seconds)
                count_raw = await client.get(window_key)

                if count_raw is None:
                    latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=True)
                    logger.debug(
                        "Fixed window not yet initialized; assuming full capacity",
                        extra={
                            "key": key,
                            "rate": effective_rate,
                            "latency_ms": round(latency_ms, 2),
                        },
                    )
                    return effective_rate

                try:
                    count = int(count_raw)
                except (TypeError, ValueError):
                    latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=False)
                    logger.warning(
                        "Corrupt fixed window counter encountered while reading remaining tokens",
                        extra={
                            "key": key,
                            "count_raw": count_raw,
                            "latency_ms": round(latency_ms, 2),
                        },
                    )
                    return None

                remaining = max(0, effective_rate - count)
                latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=True)
                logger.debug(
                    "Computed remaining tokens for fixed window",
                    extra={
                        "key": key,
                        "rate": effective_rate,
                        "current_count": count,
                        "remaining": remaining,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
                return remaining

            latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=False)
            logger.warning(
                "Unknown rate limiter algorithm when querying remaining tokens",
                extra={
                    "key": key,
                    "algorithm": self._algorithm,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            return None

        except Exception as exc:
            latency_ms = self._record_metric("RATELIMIT_GET_REMAINING", start_time, success=False)
            logger.warning(
                "Failed to get remaining tokens",
                extra={
                    "key": key,
                    "algorithm": self._algorithm,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return None

    def get_status(self) -> dict[str, Any]:
        """
        Return a configuration snapshot for observability / diagnostics.

        Returns
        -------
        dict[str, Any]
            Current rate limiter configuration and algorithm.
        """
        return {
            "algorithm": self._algorithm,
            "default_rate": self._default_rate,
            "default_period_seconds": self._default_period_seconds,
            "fallback_mode": self._fallback_mode,
            "bucket_ttl_seconds": self._bucket_ttl_seconds,
            "fixed_window_ttl_multiplier": self._fixed_window_ttl_multiplier,
            "scan_batch_size": self._scan_batch_size,
            "max_attempts": self._max_attempts,
        }

    # ════════════════════════════════════════════════════════════════════
    # Token Bucket Implementation
    # ════════════════════════════════════════════════════════════════════

    async def _check_token_bucket(
        self,
        key: str,
        rate: int,
        period_seconds: int,
        tokens: int,
    ) -> bool:
        """
        Token bucket algorithm using a single atomic Lua script.

        The bucket is represented as a Redis hash:
        - `tokens`: current token count
        - `last_refill`: timestamp of last refill/consume operation
        """
        client: AsyncRedis = self._redis_service.client()
        resilience: RedisResilience = self._redis_service.get_resilience()

        # Refill rate in tokens per second
        refill_rate = rate / period_seconds if period_seconds > 0 else 0
        now = self._now()
        bucket_key = self._token_bucket_key(key)
        start_time = time.monotonic()

        async def operation() -> Any:
            return await client.eval(  # type: ignore[misc]
                self._LUA_TOKEN_BUCKET,
                1,
                bucket_key,
                rate,
                refill_rate,
                tokens,
                now,
                self._bucket_ttl_seconds,
            )

        try:
            result = await resilience.execute(
                operation=operation,
                operation_name=f"RATELIMIT_TOKEN_BUCKET:{bucket_key}",
                max_attempts=self._max_attempts,
            )
            allowed = bool(result)
            latency_ms = self._record_metric("RATELIMIT_TOKEN_BUCKET", start_time, success=True)

            if not allowed:
                logger.info(
                    "Rate limit exceeded (token bucket)",
                    extra={
                        "key": key,
                        "redis_key": bucket_key,
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "tokens_requested": tokens,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            else:
                logger.debug(
                    "Rate limit allowed (token bucket)",
                    extra={
                        "key": key,
                        "redis_key": bucket_key,
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "tokens_requested": tokens,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

            return allowed

        except Exception as exc:
            latency_ms = self._record_metric("RATELIMIT_TOKEN_BUCKET", start_time, success=False)
            logger.error(
                "Token bucket algorithm error",
                extra={
                    "key": key,
                    "redis_key": bucket_key,
                    "rate": rate,
                    "period_seconds": period_seconds,
                    "tokens_requested": tokens,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    # ════════════════════════════════════════════════════════════════════
    # Fixed Window Implementation
    # ════════════════════════════════════════════════════════════════════

    async def _check_fixed_window(
        self,
        key: str,
        rate: int,
        period_seconds: int,
        tokens: int,
    ) -> bool:
        """
        Simple fixed-window counter using INCRBY.

        Each window is represented by a unique key:
        `ratelimit:fw:{logical_key}:{window_id}`.
        """
        client: AsyncRedis = self._redis_service.client()
        resilience: RedisResilience = self._redis_service.get_resilience()

        window_key = self._fixed_window_key(key, period_seconds)
        ttl_seconds = max(1, period_seconds * max(self._fixed_window_ttl_multiplier, 1))
        start_time = time.monotonic()

        async def operation() -> Any:
            # Increment by `tokens` so multi-token requests are supported
            count = await client.incrby(window_key, tokens)
            if count == tokens:
                # First increment for this window -> set TTL
                await client.expire(window_key, ttl_seconds)
            return count

        try:
            count_raw = await resilience.execute(
                operation=operation,
                operation_name=f"RATELIMIT_FIXED_WINDOW:{window_key}",
                max_attempts=self._max_attempts,
            )
            count = int(count_raw)
            allowed = count <= rate
            latency_ms = self._record_metric("RATELIMIT_FIXED_WINDOW", start_time, success=True)

            if not allowed:
                logger.info(
                    "Rate limit exceeded (fixed window)",
                    extra={
                        "key": key,
                        "redis_key": window_key,
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "tokens_requested": tokens,
                        "current_count": count,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            else:
                logger.debug(
                    "Rate limit allowed (fixed window)",
                    extra={
                        "key": key,
                        "redis_key": window_key,
                        "rate": rate,
                        "period_seconds": period_seconds,
                        "tokens_requested": tokens,
                        "current_count": count,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

            return allowed

        except Exception as exc:
            latency_ms = self._record_metric("RATELIMIT_FIXED_WINDOW", start_time, success=False)
            logger.error(
                "Fixed window algorithm error",
                extra={
                    "key": key,
                    "redis_key": window_key,
                    "rate": rate,
                    "period_seconds": period_seconds,
                    "tokens_requested": tokens,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise

    # ════════════════════════════════════════════════════════════════════
    # Helpers & Config Access
    # ════════════════════════════════════════════════════════════════════

    @staticmethod
    def _now() -> float:
        """Get the current UNIX timestamp in seconds (float)."""
        return time.time()

    @staticmethod
    def _token_bucket_key(key: str) -> str:
        """Build the Redis key for token bucket state."""
        return f"ratelimit:tb:{key}"

    @staticmethod
    def _fixed_window_key(key: str, period_seconds: int) -> str:
        """Build the Redis key for the current fixed window."""
        if period_seconds <= 0:
            period_seconds = 1
        window_id = int(time.time() / period_seconds)
        return f"ratelimit:fw:{key}:{window_id}"

    @staticmethod
    def _record_metric(operation: str, start_time: float, success: bool) -> float:
        """
        Record a RedisMetrics entry for a logical rate limiter operation.

        Returns
        -------
        float
            Latency in milliseconds.
        """
        latency_ms = (time.monotonic() - start_time) * 1000
        try:
            RedisMetrics.record_operation(operation, latency_ms, success=success)
        except Exception as exc:
            # Metrics failures must never affect mainline behavior
            logger.warning(
                "Failed to record rate limiter metric (non-critical)",
                extra={
                    "operation": operation,
                    "success": success,
                    "latency_ms": round(latency_ms, 2),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        return latency_ms

    def _get_config_str(self, key: str, default: str) -> str:
        try:
            value = self._config_manager.get(key)
            if isinstance(value, str):
                return value
        except Exception:
            # Config failures should not break infra components
            logger.debug(
                "Failed to read string config value for rate limiter; using default",
                extra={"key": key, "default": default},
            )
        return default

    def _get_config_int(self, key: str, default: int) -> int:
        try:
            value = self._config_manager.get(key)
            if isinstance(value, int):
                return value
        except Exception:
            logger.debug(
                "Failed to read int config value for rate limiter; using default",
                extra={"key": key, "default": default},
            )
        return default

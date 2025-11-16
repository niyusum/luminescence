"""
Redis Resilience Module for Lumen (2025)

Purpose
-------
Unified resilience layer for Redis combining circuit breaking, retry logic,
and failure recovery into a single cohesive interface that ensures consistent
failure handling across all Redis operations.

This module consolidates circuit breaker and retry patterns because Redis
correctness is deeply tied to:
- Distributed locks (require consistent Redis availability)
- Timeouts (must be coordinated with retry/circuit state)
- Retry logic (when and how to retry failed operations)
- Failure recovery (automatic vs manual recovery)
- Circuit breaker state (when to fail fast vs allow retries)
- Health checks (continuous background monitoring)

These concerns are highly interdependent. Managing them separately leads to:
- Race conditions between circuit breaker and retry logic
- Unclear ownership of failure detection
- Duplicated configuration and metrics
- Complex integration points

Responsibilities
----------------
- Execute operations with circuit breaker protection
- Apply automatic retry with exponential backoff
- Track failure rates and circuit state transitions
- Coordinate with health monitoring
- Provide unified status API
- Emit structured logs for all resilience events

Non-Responsibilities
--------------------
- No Redis operations (wraps them, doesn't execute)
- No business logic
- No metrics storage (delegates to metrics.py)
- No health monitoring (delegates to health_monitor.py)

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure resilience
- Config-driven: all thresholds and timings via ConfigManager
- Observability: structured logging for all state changes
- Concurrency safety: asyncio.Lock for state management
- Domain exceptions: clear, typed exceptions for failures
- Zero business logic

Configuration Keys
------------------
Circuit Breaker:
- core.redis.resilience.circuit.failure_threshold    : int (default 5)
- core.redis.resilience.circuit.success_threshold    : int (default 2)
- core.redis.resilience.circuit.timeout_seconds      : int (default 60)

Retry Policy:
- core.redis.resilience.retry.max_attempts          : int (default 3)
- core.redis.resilience.retry.initial_delay_seconds : float (default 0.1)
- core.redis.resilience.retry.max_delay_seconds     : float (default 2.0)
- core.redis.resilience.retry.backoff_multiplier    : float (default 2.0)
- core.redis.resilience.retry.jitter                : bool (default True)

Architecture Notes
------------------
- Single entry point: execute() handles both circuit breaking and retry
- Circuit breaker checks occur BEFORE retry attempts
- Failures during retry update circuit breaker state
- Successes reset both retry counter and circuit breaker
- Thread-safe state management via asyncio.Lock
- Exponential backoff with jitter to prevent thundering herd
"""

from __future__ import annotations

import asyncio
import random
import time
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from src.core.config import ConfigManager
from src.core.logging.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ═════════════════════════════════════════════════════════════════════════════
# DOMAIN EXCEPTIONS
# ═════════════════════════════════════════════════════════════════════════════


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreakerOpenError(Exception):
    """
    Raised when circuit breaker is OPEN and operation is rejected.
    
    This indicates Redis is experiencing sustained failures and the
    circuit has opened to prevent cascading failures.
    """

    pass


# ═════════════════════════════════════════════════════════════════════════════
# REDIS RESILIENCE
# ═════════════════════════════════════════════════════════════════════════════


class RedisResilience:
    """
    Unified resilience layer for Redis operations.

    Combines circuit breaker pattern and retry logic with exponential backoff
    into a single cohesive interface. All Redis operations should flow through
    this class to ensure consistent failure handling and recovery.

    Thread Safety
    -------------
    All state mutations are protected by asyncio.Lock to ensure safe
    concurrent access from multiple coroutines.

    Example
    -------
    >>> resilience = RedisResilience()
    >>> result = await resilience.execute(
    ...     operation=lambda: redis_client.get("key"),
    ...     operation_name="get_key"
    ... )
    """

    # Transient exceptions that should be retried
    RETRYABLE_EXCEPTIONS = (
        RedisConnectionError,
        RedisTimeoutError,
        ConnectionRefusedError,
        ConnectionResetError,
        OSError,  # Network errors
    )

    def __init__(self) -> None:
        """Initialize Redis resilience with circuit breaker and retry policy."""
        # Circuit breaker state
        self._circuit_state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._lock: asyncio.Lock = asyncio.Lock()

        # Load circuit breaker configuration
        self._circuit_failure_threshold = self._get_config_int(
            "core.redis.resilience.circuit.failure_threshold", 5
        )
        self._circuit_success_threshold = self._get_config_int(
            "core.redis.resilience.circuit.success_threshold", 2
        )
        self._circuit_timeout_seconds = self._get_config_int(
            "core.redis.resilience.circuit.timeout_seconds", 60
        )

        # Load retry policy configuration
        self._retry_max_attempts = self._get_config_int(
            "core.redis.resilience.retry.max_attempts", 3
        )
        self._retry_initial_delay = self._get_config_float(
            "core.redis.resilience.retry.initial_delay_seconds", 0.1
        )
        self._retry_max_delay = self._get_config_float(
            "core.redis.resilience.retry.max_delay_seconds", 2.0
        )
        self._retry_backoff_multiplier = self._get_config_float(
            "core.redis.resilience.retry.backoff_multiplier", 2.0
        )
        self._retry_jitter = self._get_config_bool(
            "core.redis.resilience.retry.jitter", True
        )

        logger.info(
            "RedisResilience initialized",
            extra={
                "circuit_state": self._circuit_state.value,
                "circuit_failure_threshold": self._circuit_failure_threshold,
                "circuit_success_threshold": self._circuit_success_threshold,
                "circuit_timeout_seconds": self._circuit_timeout_seconds,
                "retry_max_attempts": self._retry_max_attempts,
                "retry_initial_delay_seconds": self._retry_initial_delay,
                "retry_max_delay_seconds": self._retry_max_delay,
                "retry_backoff_multiplier": self._retry_backoff_multiplier,
                "jitter_enabled": self._retry_jitter,
            },
        )

    # ═════════════════════════════════════════════════════════════════════════
    # MAIN EXECUTION API
    # ═════════════════════════════════════════════════════════════════════════

    async def execute(
        self,
        operation: Callable[[], Any],
        operation_name: str,
        max_attempts: Optional[int] = None,
    ) -> Any:
        """
        Execute Redis operation with circuit breaker and retry logic.

        This is the main entry point for all Redis operations. It:
        1. Checks if circuit breaker allows execution
        2. Executes operation with retry logic
        3. Updates circuit breaker state based on result
        4. Returns result or raises exception

        Parameters
        ----------
        operation : Callable
            The async operation to execute
        operation_name : str
            Human-readable operation name for logging
        max_attempts : Optional[int]
            Override default max retry attempts

        Returns
        -------
        T
            The result of the successful operation

        Raises
        ------
        CircuitBreakerOpenError
            If circuit breaker is OPEN and won't allow execution
        Exception
            The last exception if all retries are exhausted
        """
        # Check circuit breaker before attempting operation
        if not await self._can_execute():
            raise CircuitBreakerOpenError(
                f"Redis circuit breaker is OPEN, operation '{operation_name}' rejected"
            )

        attempts = max_attempts if max_attempts is not None else self._retry_max_attempts
        last_exception: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                # Execute operation
                result = await operation()

                # Success - record and return
                await self._record_success()

                if attempt > 1:
                    logger.info(
                        "Redis operation succeeded after retry",
                        extra={
                            "operation": operation_name,
                            "attempt": attempt,
                            "total_attempts": attempts,
                        },
                    )

                return result

            except self.RETRYABLE_EXCEPTIONS as exc:
                last_exception = exc
                await self._record_failure()

                # Check if we have more attempts
                if attempt >= attempts:
                    logger.error(
                        "Redis operation failed after all retries",
                        extra={
                            "operation": operation_name,
                            "attempts": attempt,
                            "circuit_state": self._circuit_state.value,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                        exc_info=True,
                    )
                    raise

                # Calculate delay with exponential backoff
                delay = self._calculate_delay(attempt)

                logger.warning(
                    "Redis operation failed, retrying",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
                        "total_attempts": attempts,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "retry_delay_seconds": round(delay, 3),
                        "circuit_state": self._circuit_state.value,
                    },
                )

                # Wait before retry
                await asyncio.sleep(delay)

            except Exception as exc:
                # Non-retryable exception, record failure and fail immediately
                await self._record_failure()

                logger.error(
                    "Redis operation failed with non-retryable error",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
                        "circuit_state": self._circuit_state.value,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                raise

        # Should never reach here, but handle gracefully
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Redis operation '{operation_name}' failed without exception")

    # ═════════════════════════════════════════════════════════════════════════
    # CIRCUIT BREAKER LOGIC
    # ═════════════════════════════════════════════════════════════════════════

    async def _can_execute(self) -> bool:
        """
        Check if operation can be executed based on circuit breaker state.

        Returns
        -------
        bool
            True if operation should proceed, False if circuit is OPEN
        """
        async with self._lock:
            # If CLOSED, always allow
            if self._circuit_state == CircuitState.CLOSED:
                return True

            # If OPEN, check if timeout has elapsed
            if self._circuit_state == CircuitState.OPEN:
                if self._opened_at is None:
                    # Should never happen, but handle gracefully
                    logger.warning("Circuit OPEN but no opened_at timestamp, allowing operation")
                    return True

                elapsed = time.time() - self._opened_at
                if elapsed >= self._circuit_timeout_seconds:
                    # Timeout elapsed, transition to HALF_OPEN
                    await self._transition_to_half_open()
                    return True
                else:
                    # Still in timeout period, reject
                    return False

            # If HALF_OPEN, allow (to test recovery)
            if self._circuit_state == CircuitState.HALF_OPEN:
                return True

            return False

    async def _record_success(self) -> None:
        """Record successful operation and update circuit state."""
        async with self._lock:
            self._success_count += 1
            self._failure_count = 0  # Reset failure count on success

            logger.debug(
                "Redis resilience recorded success",
                extra={
                    "circuit_state": self._circuit_state.value,
                    "success_count": self._success_count,
                },
            )

            # If HALF_OPEN and enough successes, close circuit
            if self._circuit_state == CircuitState.HALF_OPEN:
                if self._success_count >= self._circuit_success_threshold:
                    await self._transition_to_closed()

    async def _record_failure(self) -> None:
        """Record failed operation and update circuit state."""
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0  # Reset success count on failure
            self._last_failure_time = time.time()

            logger.debug(
                "Redis resilience recorded failure",
                extra={
                    "circuit_state": self._circuit_state.value,
                    "failure_count": self._failure_count,
                },
            )

            # If CLOSED and threshold exceeded, open circuit
            if self._circuit_state == CircuitState.CLOSED:
                if self._failure_count >= self._circuit_failure_threshold:
                    await self._transition_to_open()

            # If HALF_OPEN and any failure, re-open circuit
            elif self._circuit_state == CircuitState.HALF_OPEN:
                await self._transition_to_open()

    async def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        old_state = self._circuit_state
        self._circuit_state = CircuitState.OPEN
        self._opened_at = time.time()
        self._success_count = 0

        logger.warning(
            "Circuit breaker transitioned to OPEN",
            extra={
                "previous_state": old_state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._circuit_failure_threshold,
                "timeout_seconds": self._circuit_timeout_seconds,
            },
        )

    async def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        old_state = self._circuit_state
        self._circuit_state = CircuitState.HALF_OPEN
        self._failure_count = 0
        self._success_count = 0

        logger.info(
            "Circuit breaker transitioned to HALF_OPEN",
            extra={
                "previous_state": old_state.value,
                "timeout_elapsed_seconds": (
                    round(time.time() - self._opened_at, 2) if self._opened_at else 0
                ),
            },
        )

    async def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        old_state = self._circuit_state
        self._circuit_state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None

        logger.info(
            "Circuit breaker transitioned to CLOSED",
            extra={
                "previous_state": old_state.value,
                "success_threshold_met": self._circuit_success_threshold,
            },
        )

    # ═════════════════════════════════════════════════════════════════════════
    # RETRY LOGIC
    # ═════════════════════════════════════════════════════════════════════════

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate retry delay with exponential backoff.

        Parameters
        ----------
        attempt : int
            Current attempt number (1-indexed)

        Returns
        -------
        float
            Delay in seconds before next retry
        """
        # Exponential backoff: initial_delay * multiplier^(attempt-1)
        delay = self._retry_initial_delay * (
            self._retry_backoff_multiplier ** (attempt - 1)
        )

        # Cap at max delay
        delay = min(delay, self._retry_max_delay)

        # Add jitter to prevent thundering herd
        if self._retry_jitter:
            jitter_amount = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0.0, delay)  # Ensure non-negative

    # ═════════════════════════════════════════════════════════════════════════
    # MANUAL CONTROL
    # ═════════════════════════════════════════════════════════════════════════

    async def reset(self) -> None:
        """
        Manually reset circuit breaker to CLOSED state.
        
        Use this to manually recover from circuit breaker OPEN state,
        typically after confirming Redis has recovered.
        """
        async with self._lock:
            old_state = self._circuit_state
            self._circuit_state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None
            self._last_failure_time = None

            logger.info(
                "Redis resilience manually reset",
                extra={"previous_state": old_state.value},
            )

    async def force_open(self) -> None:
        """
        Manually force circuit breaker to OPEN state.
        
        Use this to manually disable Redis operations, typically
        for maintenance or emergency situations.
        """
        async with self._lock:
            await self._transition_to_open()
            logger.warning("Redis resilience manually forced to OPEN")

    # ═════════════════════════════════════════════════════════════════════════
    # STATUS API
    # ═════════════════════════════════════════════════════════════════════════

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._circuit_state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is CLOSED (normal operation)."""
        return self._circuit_state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is OPEN (failing)."""
        return self._circuit_state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is HALF_OPEN (testing)."""
        return self._circuit_state == CircuitState.HALF_OPEN

    def get_status(self) -> dict:
        """
        Get current resilience status.

        Returns
        -------
        dict
            Complete status including circuit state, counts, and configuration
        """
        return {
            # Circuit breaker state
            "circuit_state": self._circuit_state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "circuit_failure_threshold": self._circuit_failure_threshold,
            "circuit_success_threshold": self._circuit_success_threshold,
            "circuit_timeout_seconds": self._circuit_timeout_seconds,
            "opened_at": self._opened_at,
            "last_failure_time": self._last_failure_time,
            "time_until_half_open": (
                max(0, self._circuit_timeout_seconds - (time.time() - self._opened_at))
                if self._opened_at and self._circuit_state == CircuitState.OPEN
                else None
            ),
            # Retry configuration
            "retry_max_attempts": self._retry_max_attempts,
            "retry_initial_delay_seconds": self._retry_initial_delay,
            "retry_max_delay_seconds": self._retry_max_delay,
            "retry_backoff_multiplier": self._retry_backoff_multiplier,
            "retry_jitter_enabled": self._retry_jitter,
        }

    # ═════════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_config_int(key: str, default: int) -> int:
        """Get integer config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, int):
                return val
        except Exception:
            pass
        return default

    @staticmethod
    def _get_config_float(key: str, default: float) -> float:
        """Get float config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        except Exception:
            pass
        return default

    @staticmethod
    def _get_config_bool(key: str, default: bool) -> bool:
        """Get boolean config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, bool):
                return val
        except Exception:
            pass
        return default
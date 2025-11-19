"""
Circuit Breaker Pattern for Database Operations (LES 2025)
===========================================================

Purpose
-------
Implements the circuit breaker pattern to prevent cascading failures when
the database becomes unavailable or slow. Provides automatic fail-fast behavior
and recovery detection.

Responsibilities
----------------
- Track consecutive database operation failures
- Open circuit when failure threshold is reached (fail-fast mode)
- Allow periodic test requests to detect recovery (half-open state)
- Close circuit when database recovers (normal operation)
- Record detailed metrics and state transitions
- Thread-safe state management for concurrent access

Non-Responsibilities
--------------------
- Database connection management (handled by DatabaseService)
- Query execution (handled by SQLAlchemy)
- Retry logic (handled by DatabaseRetryPolicy)
- Health monitoring (handled by DatabaseHealthMonitor)

Circuit States
--------------
**CLOSED** (Normal Operation):
- All requests pass through
- Track failure count
- Open circuit if failures exceed threshold

**OPEN** (Fail-Fast):
- Immediately reject all requests
- Prevent cascading failures
- Transition to HALF_OPEN after timeout

**HALF_OPEN** (Recovery Testing):
- Allow limited test requests
- Close circuit if tests succeed
- Re-open circuit if tests fail

Configuration
-------------
All values sourced from Config with safe defaults:
- CIRCUIT_BREAKER_FAILURE_THRESHOLD (default: 5)
- CIRCUIT_BREAKER_RECOVERY_TIMEOUT_MS (default: 60000)  # 60 seconds
- CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS (default: 3)

LES 2025 Compliance
-------------------
- Config-driven with safe defaults
- Structured logging with state transitions
- Maximum observability via metrics
- Thread-safe for concurrent access
- Graceful degradation

Usage Example
-------------
>>> circuit_breaker = CircuitBreaker()
>>>
>>> # Wrap database operations
>>> if not circuit_breaker.allow_request():
>>>     raise CircuitBreakerOpenError("Database circuit breaker is open")
>>>
>>> try:
>>>     result = await database_operation()
>>>     circuit_breaker.record_success()
>>> except Exception as exc:
>>>     circuit_breaker.record_failure()
>>>     raise
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.core.config.config import Config
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# CIRCUIT BREAKER EXCEPTIONS
# ============================================================================


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and requests are rejected."""

    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)


# ============================================================================
# CIRCUIT BREAKER STATES
# ============================================================================


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Fail-fast, all requests rejected
    HALF_OPEN = "half_open"  # Testing recovery, limited requests allowed


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker monitoring."""

    state: CircuitState
    failure_count: int
    success_count: int
    consecutive_failures: int
    last_failure_time: Optional[float]
    last_state_change_time: float
    total_requests: int
    rejected_requests: int
    half_open_test_count: int


# ============================================================================
# CIRCUIT BREAKER IMPLEMENTATION
# ============================================================================


class CircuitBreaker:
    """
    Circuit breaker for database operations.

    Thread-safe implementation using asyncio.Lock for state management.
    Automatically transitions between states based on failure patterns.
    """

    def __init__(
        self,
        failure_threshold: Optional[int] = None,
        recovery_timeout_ms: Optional[int] = None,
        half_open_max_requests: Optional[int] = None,
    ) -> None:
        """
        Initialize circuit breaker.

        Parameters
        ----------
        failure_threshold : Optional[int]
            Number of consecutive failures before opening circuit.
            Defaults to Config.CIRCUIT_BREAKER_FAILURE_THRESHOLD or 5.
        recovery_timeout_ms : Optional[int]
            Time to wait before attempting recovery (milliseconds).
            Defaults to Config.CIRCUIT_BREAKER_RECOVERY_TIMEOUT_MS or 60000.
        half_open_max_requests : Optional[int]
            Maximum test requests in HALF_OPEN state.
            Defaults to Config.CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS or 3.
        """
        # Load configuration
        self._failure_threshold = failure_threshold or int(
            getattr(Config, "CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
        )
        self._recovery_timeout_ms = recovery_timeout_ms or int(
            getattr(Config, "CIRCUIT_BREAKER_RECOVERY_TIMEOUT_MS", 60_000)
        )
        self._half_open_max_requests = half_open_max_requests or int(
            getattr(Config, "CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS", 3)
        )

        # State management
        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()

        # Failure tracking
        self._consecutive_failures = 0
        self._failure_count = 0
        self._success_count = 0

        # Timing
        self._last_failure_time: Optional[float] = None
        self._last_state_change_time = time.perf_counter()

        # Request tracking
        self._total_requests = 0
        self._rejected_requests = 0
        self._half_open_test_count = 0

        logger.info(
            "Circuit breaker initialized",
            extra={
                "failure_threshold": self._failure_threshold,
                "recovery_timeout_ms": self._recovery_timeout_ms,
                "half_open_max_requests": self._half_open_max_requests,
            },
        )

    # ========================================================================
    # STATE MANAGEMENT
    # ========================================================================

    @property
    def state(self) -> CircuitState:
        """Get current circuit state (thread-safe)."""
        return self._state

    async def allow_request(self) -> bool:
        """
        Check if a request should be allowed through the circuit breaker.

        Returns
        -------
        bool
            True if request is allowed, False if circuit is open.

        Notes
        -----
        - CLOSED: Always allows requests
        - OPEN: Rejects all requests (unless recovery timeout has passed)
        - HALF_OPEN: Allows limited test requests
        """
        async with self._lock:
            self._total_requests += 1

            # CLOSED state: allow all requests
            if self._state == CircuitState.CLOSED:
                return True

            # OPEN state: check if recovery timeout has passed
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    await self._transition_to_half_open()
                    return True
                else:
                    self._rejected_requests += 1
                    logger.debug(
                        "Request rejected: circuit breaker is OPEN",
                        extra={
                            "consecutive_failures": self._consecutive_failures,
                            "last_failure_time": self._last_failure_time,
                        },
                    )
                    return False

            # HALF_OPEN state: allow limited test requests
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_test_count < self._half_open_max_requests:
                    self._half_open_test_count += 1
                    return True
                else:
                    self._rejected_requests += 1
                    logger.debug(
                        "Request rejected: HALF_OPEN test limit reached",
                        extra={"half_open_test_count": self._half_open_test_count},
                    )
                    return False

            # Should never reach here, but be safe
            return False

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True

        elapsed_ms = (time.perf_counter() - self._last_failure_time) * 1000
        return elapsed_ms >= self._recovery_timeout_ms

    # ========================================================================
    # REQUEST RECORDING
    # ========================================================================

    async def record_success(self) -> None:
        """
        Record a successful request.

        Behavior
        --------
        - CLOSED: Reset consecutive failures
        - HALF_OPEN: Close circuit if enough successes
        - OPEN: Should not be called (requests shouldn't reach here)
        """
        async with self._lock:
            self._success_count += 1
            self._consecutive_failures = 0

            if self._state == CircuitState.HALF_OPEN:
                # Close circuit after successful recovery test
                await self._transition_to_closed()
                logger.info(
                    "Circuit breaker recovery successful",
                    extra={
                        "half_open_test_count": self._half_open_test_count,
                        "total_failures": self._failure_count,
                        "total_successes": self._success_count,
                    },
                )

    async def record_failure(self) -> None:
        """
        Record a failed request.

        Behavior
        --------
        - CLOSED: Increment failures, open circuit if threshold reached
        - HALF_OPEN: Re-open circuit (recovery failed)
        - OPEN: Log additional failure
        """
        async with self._lock:
            self._failure_count += 1
            self._consecutive_failures += 1
            self._last_failure_time = time.perf_counter()

            logger.warning(
                "Circuit breaker recorded failure",
                extra={
                    "state": self._state.value,
                    "consecutive_failures": self._consecutive_failures,
                    "failure_threshold": self._failure_threshold,
                },
            )

            if self._state == CircuitState.CLOSED:
                if self._consecutive_failures >= self._failure_threshold:
                    await self._transition_to_open()

            elif self._state == CircuitState.HALF_OPEN:
                # Recovery failed, re-open circuit
                await self._transition_to_open()
                logger.warning(
                    "Circuit breaker recovery failed",
                    extra={
                        "half_open_test_count": self._half_open_test_count,
                    },
                )

    # ========================================================================
    # STATE TRANSITIONS
    # ========================================================================

    async def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state (fail-fast mode)."""
        if self._state != CircuitState.OPEN:
            old_state = self._state
            self._state = CircuitState.OPEN
            self._last_state_change_time = time.perf_counter()

            logger.error(
                "Circuit breaker opened (fail-fast mode)",
                extra={
                    "old_state": old_state.value,
                    "consecutive_failures": self._consecutive_failures,
                    "failure_threshold": self._failure_threshold,
                    "recovery_timeout_ms": self._recovery_timeout_ms,
                },
            )

    async def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state (recovery testing)."""
        if self._state != CircuitState.HALF_OPEN:
            old_state = self._state
            self._state = CircuitState.HALF_OPEN
            self._half_open_test_count = 0
            self._last_state_change_time = time.perf_counter()

            logger.info(
                "Circuit breaker entering recovery mode (HALF_OPEN)",
                extra={
                    "old_state": old_state.value,
                    "max_test_requests": self._half_open_max_requests,
                },
            )

    async def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state (normal operation)."""
        if self._state != CircuitState.CLOSED:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_test_count = 0
            self._last_state_change_time = time.perf_counter()

            logger.info(
                "Circuit breaker closed (normal operation resumed)",
                extra={
                    "old_state": old_state.value,
                    "total_failures": self._failure_count,
                    "total_successes": self._success_count,
                },
            )

    # ========================================================================
    # METRICS & MONITORING
    # ========================================================================

    def get_metrics(self) -> CircuitBreakerMetrics:
        """
        Get current circuit breaker metrics.

        Returns
        -------
        CircuitBreakerMetrics
            Snapshot of current circuit breaker state and counters.
        """
        return CircuitBreakerMetrics(
            state=self._state,
            failure_count=self._failure_count,
            success_count=self._success_count,
            consecutive_failures=self._consecutive_failures,
            last_failure_time=self._last_failure_time,
            last_state_change_time=self._last_state_change_time,
            total_requests=self._total_requests,
            rejected_requests=self._rejected_requests,
            half_open_test_count=self._half_open_test_count,
        )

    async def reset(self) -> None:
        """
        Manually reset circuit breaker to CLOSED state.

        WARNING: Only use this for administrative/testing purposes.
        Normal operation should rely on automatic state transitions.
        """
        async with self._lock:
            logger.warning(
                "Circuit breaker manually reset",
                extra={
                    "old_state": self._state.value,
                    "consecutive_failures": self._consecutive_failures,
                },
            )
            await self._transition_to_closed()
            self._failure_count = 0
            self._success_count = 0
            self._total_requests = 0
            self._rejected_requests = 0

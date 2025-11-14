"""
Redis Circuit Breaker for Lumen (2025)

Purpose
-------
Implement circuit breaker pattern for Redis operations to prevent cascading
failures and provide graceful degradation when Redis is unhealthy.

States:
- CLOSED: Normal operation, all requests pass through
- OPEN: Redis is failing, all requests fail fast
- HALF_OPEN: Testing if Redis has recovered

Responsibilities
----------------
- Monitor Redis operation success/failure rates
- Automatically open circuit when failure threshold exceeded
- Periodically test Redis health in half-open state
- Close circuit when Redis recovers
- Emit events on state transitions
- Provide circuit status for monitoring

Non-Responsibilities
--------------------
- No Redis operations (wraps them, doesn't execute)
- No retry logic (handled by retry_policy.py)
- No metrics collection (handled by metrics.py)
- No business logic

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure pattern
- Config-driven: thresholds and timeouts
- Observability: structured logging for state transitions
- Event emission: circuit state changes
- Thread-safe state management

Configuration Keys
------------------
- core.redis.circuit_breaker.failure_threshold    : int (default 5)
- core.redis.circuit_breaker.success_threshold    : int (default 2)
- core.redis.circuit_breaker.timeout_seconds      : int (default 60)
- core.redis.circuit_breaker.half_open_timeout_sec: int (default 5)

Architecture Notes
------------------
- Uses asyncio.Lock for thread-safe state transitions
- Tracks consecutive failures/successes in rolling window
- Automatically transitions between states based on thresholds
- Fails fast when circuit is OPEN to prevent resource exhaustion
- Logs all state transitions for debugging and monitoring
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

from src.core.logging.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    
    CLOSED = "CLOSED"           # Normal operation
    OPEN = "OPEN"               # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"     # Testing recovery


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is OPEN and operation is rejected."""
    pass


class RedisCircuitBreaker:
    """
    Circuit breaker for Redis operations.
    
    Implements the circuit breaker pattern to prevent cascading failures
    when Redis becomes unhealthy. Automatically transitions between states
    based on failure/success rates.
    """
    
    def __init__(self) -> None:
        """Initialize circuit breaker in CLOSED state."""
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        
        # Load configuration
        self._failure_threshold = self._get_config_int(
            "core.redis.circuit_breaker.failure_threshold", 5
        )
        self._success_threshold = self._get_config_int(
            "core.redis.circuit_breaker.success_threshold", 2
        )
        self._timeout_seconds = self._get_config_int(
            "core.redis.circuit_breaker.timeout_seconds", 60
        )
        self._half_open_timeout = self._get_config_int(
            "core.redis.circuit_breaker.half_open_timeout_sec", 5
        )
        
        logger.info(
            "RedisCircuitBreaker initialized",
            extra={
                "initial_state": self._state.value,
                "failure_threshold": self._failure_threshold,
                "success_threshold": self._success_threshold,
                "timeout_seconds": self._timeout_seconds,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATE MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is CLOSED (normal operation)."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is OPEN (failing)."""
        return self._state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit is HALF_OPEN (testing)."""
        return self._state == CircuitState.HALF_OPEN
    
    async def can_execute(self) -> bool:
        """
        Check if operation can be executed.
        
        Returns
        -------
        bool
            True if operation should proceed, False if circuit is OPEN
        """
        async with self._lock:
            # If CLOSED, always allow
            if self._state == CircuitState.CLOSED:
                return True
            
            # If OPEN, check if timeout has elapsed
            if self._state == CircuitState.OPEN:
                if self._opened_at is None:
                    # Should never happen, but handle gracefully
                    return True
                
                elapsed = time.time() - self._opened_at
                if elapsed >= self._timeout_seconds:
                    # Timeout elapsed, transition to HALF_OPEN
                    await self._transition_to_half_open()
                    return True
                else:
                    # Still in timeout period, reject
                    return False
            
            # If HALF_OPEN, allow (to test recovery)
            if self._state == CircuitState.HALF_OPEN:
                return True
            
            return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # RECORDING RESULTS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def record_success(self) -> None:
        """Record successful operation."""
        async with self._lock:
            self._success_count += 1
            self._failure_count = 0  # Reset failure count on success
            
            logger.debug(
                "Circuit breaker recorded success",
                extra={
                    "state": self._state.value,
                    "success_count": self._success_count,
                },
            )
            
            # If HALF_OPEN and enough successes, close circuit
            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self._success_threshold:
                    await self._transition_to_closed()
    
    async def record_failure(self) -> None:
        """Record failed operation."""
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0  # Reset success count on failure
            self._last_failure_time = time.time()
            
            logger.debug(
                "Circuit breaker recorded failure",
                extra={
                    "state": self._state.value,
                    "failure_count": self._failure_count,
                },
            )
            
            # If CLOSED and threshold exceeded, open circuit
            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self._failure_threshold:
                    await self._transition_to_open()
            
            # If HALF_OPEN and any failure, re-open circuit
            elif self._state == CircuitState.HALF_OPEN:
                await self._transition_to_open()
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATE TRANSITIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        old_state = self._state
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._success_count = 0
        
        logger.warning(
            "Circuit breaker transitioned to OPEN",
            extra={
                "previous_state": old_state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "timeout_seconds": self._timeout_seconds,
            },
        )
    
    async def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        old_state = self._state
        self._state = CircuitState.HALF_OPEN
        self._failure_count = 0
        self._success_count = 0
        
        logger.info(
            "Circuit breaker transitioned to HALF_OPEN",
            extra={
                "previous_state": old_state.value,
                "timeout_elapsed_seconds": round(time.time() - self._opened_at, 2) if self._opened_at else 0,
            },
        )
    
    async def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        old_state = self._state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        
        logger.info(
            "Circuit breaker transitioned to CLOSED",
            extra={
                "previous_state": old_state.value,
                "success_threshold_met": self._success_threshold,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # MANUAL CONTROL
    # ═══════════════════════════════════════════════════════════════════════
    
    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        async with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None
            self._last_failure_time = None
            
            logger.info(
                "Circuit breaker manually reset",
                extra={"previous_state": old_state.value},
            )
    
    async def force_open(self) -> None:
        """Manually force circuit breaker to OPEN state."""
        async with self._lock:
            await self._transition_to_open()
            
            logger.warning("Circuit breaker manually forced to OPEN")
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATUS
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> dict:
        """
        Get current circuit breaker status.
        
        Returns
        -------
        dict
            Status information including state, counts, and timing
        """
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self._failure_threshold,
            "success_threshold": self._success_threshold,
            "timeout_seconds": self._timeout_seconds,
            "opened_at": self._opened_at,
            "last_failure_time": self._last_failure_time,
            "time_until_half_open": (
                max(0, self._timeout_seconds - (time.time() - self._opened_at))
                if self._opened_at and self._state == CircuitState.OPEN
                else None
            ),
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════
    
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
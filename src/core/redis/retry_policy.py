"""
Redis Retry Policy for Lumen (2025)

Purpose
-------
Implement retry logic with exponential backoff for transient Redis failures.

Handles:
- Connection errors
- Timeout errors
- Temporary unavailability
- Network issues

Responsibilities
----------------
- Execute operations with automatic retry on transient failures
- Apply exponential backoff between retries
- Respect maximum retry limits
- Log retry attempts and outcomes
- Distinguish between transient and permanent failures

Non-Responsibilities
--------------------
- No circuit breaking (handled by circuit_breaker.py)
- No metrics collection (handled by metrics.py)
- No business logic

Lumen 2025 Compliance
---------------------
- Strict layering: pure infrastructure pattern
- Config-driven: retry counts and backoff settings
- Observability: structured logging for retry attempts
- Graceful degradation: respects max retry limits

Configuration Keys
------------------
- core.redis.retry.max_attempts         : int (default 3)
- core.redis.retry.initial_delay_seconds: float (default 0.1)
- core.redis.retry.max_delay_seconds    : float (default 2.0)
- core.redis.retry.backoff_multiplier   : float (default 2.0)
- core.redis.retry.jitter               : bool (default True)

Architecture Notes
------------------
- Uses exponential backoff: delay = min(initial * multiplier^attempt, max_delay)
- Optional jitter to prevent thundering herd
- Only retries on transient exceptions (ConnectionError, TimeoutError)
- Permanent errors (e.g., authentication) are not retried
- All retry attempts are logged with context
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Optional, TypeVar

from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from src.core.logging.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger(__name__)

T = TypeVar('T')


class RedisRetryPolicy:
    """
    Retry policy for Redis operations with exponential backoff.
    
    Automatically retries transient failures with increasing delays
    between attempts to allow Redis time to recover.
    """
    
    # Transient exceptions that should be retried
    RETRYABLE_EXCEPTIONS = (
        RedisConnectionError,
        RedisTimeoutError,
        ConnectionRefusedError,
        ConnectionResetError,
    )
    
    def __init__(self) -> None:
        """Initialize retry policy with config-driven settings."""
        self._max_attempts = self._get_config_int("core.redis.retry.max_attempts", 3)
        self._initial_delay = self._get_config_float("core.redis.retry.initial_delay_seconds", 0.1)
        self._max_delay = self._get_config_float("core.redis.retry.max_delay_seconds", 2.0)
        self._backoff_multiplier = self._get_config_float("core.redis.retry.backoff_multiplier", 2.0)
        self._jitter = self._get_config_bool("core.redis.retry.jitter", True)
        
        logger.debug(
            "RedisRetryPolicy initialized",
            extra={
                "max_attempts": self._max_attempts,
                "initial_delay_seconds": self._initial_delay,
                "max_delay_seconds": self._max_delay,
                "backoff_multiplier": self._backoff_multiplier,
                "jitter_enabled": self._jitter,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # RETRY EXECUTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def execute(
        self,
        operation: Callable[[], Any],
        operation_name: str,
        max_attempts: Optional[int] = None,
    ) -> T:
        """
        Execute operation with retry logic.
        
        Parameters
        ----------
        operation : Callable
            The async operation to execute
        operation_name : str
            Human-readable operation name for logging
        max_attempts : Optional[int]
            Override default max attempts
            
        Returns
        -------
        T
            The result of the successful operation
            
        Raises
        ------
        Exception
            The last exception if all retries are exhausted
        """
        attempts = max_attempts if max_attempts is not None else self._max_attempts
        last_exception: Optional[Exception] = None
        
        for attempt in range(1, attempts + 1):
            try:
                result = await operation()
                
                # Success
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
                
                # Check if we have more attempts
                if attempt >= attempts:
                    logger.error(
                        "Redis operation failed after all retries",
                        extra={
                            "operation": operation_name,
                            "attempts": attempt,
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
                    },
                )
                
                # Wait before retry
                await asyncio.sleep(delay)
            
            except Exception as exc:
                # Non-retryable exception, fail immediately
                logger.error(
                    "Redis operation failed with non-retryable error",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt,
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
    
    # ═══════════════════════════════════════════════════════════════════════
    # BACKOFF CALCULATION
    # ═══════════════════════════════════════════════════════════════════════
    
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
        delay = self._initial_delay * (self._backoff_multiplier ** (attempt - 1))
        
        # Cap at max delay
        delay = min(delay, self._max_delay)
        
        # Add jitter to prevent thundering herd
        if self._jitter:
            jitter_amount = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_amount, jitter_amount)
        
        return max(0.0, delay)  # Ensure non-negative
    
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
"""
Database Retry Policy - Infrastructure Resilience (Lumen 2025)

Purpose
-------
Configurable retry policy for handling transient database failures with
exponential backoff, jitter, and comprehensive observability.

Executes async operations with automatic retry semantics for retriable errors
such as connection drops, deadlocks, and operational failures.

Responsibilities
----------------
- Execute async operations with retry logic
- Classify errors as retriable or non-retriable
- Implement exponential backoff with jitter
- Emit metrics and structured logs for each attempt
- Support config-driven retry behavior
- Prevent thundering herd via jitter

Non-Responsibilities
--------------------
- Transaction management (caller owns transactions)
- Business logic or domain rules
- Circuit breaking (handled elsewhere)
- Rate limiting (handled elsewhere)
- Discord integration

LUMEN 2025 Compliance
---------------------
✓ Article I: No state mutations, execution wrapper only
✓ Article II: Comprehensive structured logging
✓ Article III: Config-driven with safe defaults
✓ Article IX: Graceful degradation with clear error propagation
✓ Article X: Maximum observability via metrics and logs

Architecture Notes
------------------
**Retry Classification**:
- Retriable: OperationalError, DBAPIError (connection/transient issues)
- Non-retriable: All other exceptions (logic errors, constraints, etc.)

**Backoff Strategy**:
- Exponential: base_ms * (2 ^ (attempt - 1))
- Capped: Never exceeds max_backoff_ms
- Jittered: Random jitter added to prevent thundering herd
- Formula: min(base * 2^(attempt-1), max) + random(0, jitter)

**Metrics Emission**:
- Every attempt recorded with will_retry flag
- Final give-up recorded separately
- Allows monitoring retry rates and success patterns

Configuration
-------------
All values sourced from Config:
- DATABASE_RETRY_MAX_ATTEMPTS (default: 3)
- DATABASE_RETRY_INITIAL_BACKOFF_MS (default: 50)
- DATABASE_RETRY_MAX_BACKOFF_MS (default: 1000)
- DATABASE_RETRY_JITTER_MS (default: 50)

Usage Example
-------------
Basic usage with transaction:

>>> from src.core.database.retry_policy import DatabaseRetryPolicy
>>> from src.core.database.service import DatabaseService
>>>
>>> retry_policy = DatabaseRetryPolicy.from_config()
>>>
>>> async def update_player_lumees(player_id: int, amount: int) -> None:
>>>     async with DatabaseService.get_transaction() as session:
>>>         player = await session.get(Player, player_id, with_for_update=True)
>>>         player.lumees += amount
>>>
>>> await retry_policy.execute(
>>>     lambda: update_player_lumees(player_id=123, amount=1000),
>>>     operation_name="player.update_lumees",
>>> )

With context:

>>> async def risky_operation() -> dict:
>>>     async with DatabaseService.get_transaction() as session:
>>>         # ... complex database work ...
>>>         return {"status": "success"}
>>>
>>> result = await retry_policy.execute(
>>>     risky_operation,
>>>     operation_name="complex.batch_update",
>>>     context={"batch_id": "batch_123", "user_id": 456},
>>> )

Custom configuration:

>>> from src.core.database.retry_policy import DatabaseRetryConfig
>>>
>>> config = DatabaseRetryConfig(
>>>     max_attempts=5,
>>>     initial_backoff_ms=100,
>>>     max_backoff_ms=5000,
>>>     jitter_ms=200,
>>> )
>>> retry_policy = DatabaseRetryPolicy(config)

Error handling:

>>> try:
>>>     result = await retry_policy.execute(
>>>         operation,
>>>         operation_name="player.update",
>>>     )
>>> except OperationalError as exc:
>>>     # Retries exhausted, still failed
>>>     logger.error(f"Operation failed after retries: {exc}")
>>>     raise

Best Practices
--------------
**When to Use**:
- Operations susceptible to transient failures
- High-value operations worth retrying
- Operations with idempotent semantics

**When to Skip**:
- Operations with non-retriable errors (constraints, logic)
- Operations already wrapped in retry logic
- Low-value operations where failure is acceptable

**Operation Naming**:
- Use stable identifiers: "module.operation"
- Good: "player.update_lumees", "inventory.fusion"
- Bad: "op1", "database_write"

**Transaction Ownership**:
- Caller creates transaction inside operation
- Retry policy executes entire operation (including transaction)
- Don't wrap transaction in retry, wrap operation that creates transaction

Retry Patterns
--------------
**Good Pattern** (retry entire operation including transaction):
```python
async def operation():
    async with DatabaseService.get_transaction() as session:
        # ... work ...
        pass

await retry_policy.execute(operation, operation_name="...")
```

**Bad Pattern** (retry inside transaction):
```python
async with DatabaseService.get_transaction() as session:
    # DON'T DO THIS - creates nested transaction issues
    await retry_policy.execute(some_db_work, ...)
```
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.metrics import DatabaseMetrics

logger = get_logger(__name__)

# Type variable for operation return type
T = TypeVar("T")


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class DatabaseRetryConfig:
    """
    Configuration for database retry behavior.

    Attributes
    ----------
    max_attempts : int
        Maximum number of attempts (including initial attempt).
    initial_backoff_ms : int
        Initial backoff duration in milliseconds.
    max_backoff_ms : int
        Maximum backoff duration in milliseconds.
    jitter_ms : int
        Maximum random jitter to add to backoff in milliseconds.
    retriable_exceptions : Tuple[Type[BaseException], ...]
        Exception types considered retriable.
    """

    max_attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
    jitter_ms: int
    retriable_exceptions: Tuple[Type[BaseException], ...] = (
        OperationalError,
        DBAPIError,
    )

    @classmethod
    def from_config(cls) -> DatabaseRetryConfig:
        """
        Build retry configuration from Config with safe defaults.

        All values sourced from Config to comply with LES config-driven
        architecture.

        Returns
        -------
        DatabaseRetryConfig
            Configuration instance sourced from Config.

        Configuration Keys
        ------------------
        - DATABASE_RETRY_MAX_ATTEMPTS (default: 3)
        - DATABASE_RETRY_INITIAL_BACKOFF_MS (default: 50)
        - DATABASE_RETRY_MAX_BACKOFF_MS (default: 1000)
        - DATABASE_RETRY_JITTER_MS (default: 50)
        """
        max_attempts = int(getattr(Config, "DATABASE_RETRY_MAX_ATTEMPTS", 3))
        initial_backoff_ms = int(
            getattr(Config, "DATABASE_RETRY_INITIAL_BACKOFF_MS", 50)
        )
        max_backoff_ms = int(getattr(Config, "DATABASE_RETRY_MAX_BACKOFF_MS", 1000))
        jitter_ms = int(getattr(Config, "DATABASE_RETRY_JITTER_MS", 50))

        return cls(
            max_attempts=max_attempts,
            initial_backoff_ms=initial_backoff_ms,
            max_backoff_ms=max_backoff_ms,
            jitter_ms=jitter_ms,
        )


# ============================================================================
# Retry Policy
# ============================================================================


class DatabaseRetryPolicy:
    """
    Execute async database operations with retry semantics.

    Implements exponential backoff with jitter for transient database failures.
    Records comprehensive metrics and logs for each attempt.

    Public API
    ----------
    - __init__(config) -> Create policy with configuration
    - from_config() -> Create policy from Config
    - execute(operation, operation_name, context) -> Execute with retries

    Usage
    -----
    >>> retry_policy = DatabaseRetryPolicy.from_config()
    >>>
    >>> async def db_operation():
    >>>     async with DatabaseService.get_transaction() as session:
    >>>         # ... database work ...
    >>>         pass
    >>>
    >>> result = await retry_policy.execute(
    >>>     db_operation,
    >>>     operation_name="player.update_lumees"
    >>> )
    """

    def __init__(self, config: DatabaseRetryConfig) -> None:
        """
        Initialize retry policy with configuration.

        Parameters
        ----------
        config : DatabaseRetryConfig
            Configuration specifying retry behavior.
        """
        self._config = config

    @classmethod
    def from_config(cls) -> DatabaseRetryPolicy:
        """
        Create a retry policy configured from Config.

        Returns
        -------
        DatabaseRetryPolicy
            Policy instance ready to execute operations.

        See Also
        --------
        DatabaseRetryConfig.from_config : Configuration factory
        """
        return cls(DatabaseRetryConfig.from_config())

    def _is_retriable(self, exc: BaseException) -> bool:
        """
        Determine if an exception is retriable.

        Parameters
        ----------
        exc : BaseException
            Exception to classify.

        Returns
        -------
        bool
            True if exception is retriable, False otherwise.
        """
        return isinstance(exc, self._config.retriable_exceptions)

    def _compute_backoff_ms(self, attempt: int) -> int:
        """
        Compute backoff duration for given attempt with jitter.

        Implements exponential backoff: base * (2 ^ (attempt - 1))
        Capped at max_backoff_ms and jittered to prevent thundering herd.

        Parameters
        ----------
        attempt : int
            Current attempt number (1-indexed).

        Returns
        -------
        int
            Backoff duration in milliseconds.
        """
        # Exponential backoff: base * 2^(attempt-1)
        exponent = max(attempt - 1, 0)
        base = self._config.initial_backoff_ms * (2**exponent)

        # Cap at maximum
        capped = min(base, self._config.max_backoff_ms)

        # Add jitter
        jitter = (
            random.randint(0, self._config.jitter_ms)
            if self._config.jitter_ms > 0
            else 0
        )

        return capped + jitter

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        operation_name: str,
        context: Optional[dict[str, Any]] = None,
    ) -> T:
        """
        Execute async operation with retry logic for transient failures.

        Retries retriable exceptions up to max_attempts with exponential
        backoff and jitter. Emits metrics and logs for each attempt.

        Parameters
        ----------
        operation : Callable[[], Awaitable[T]]
            Zero-argument async callable performing database work.
        operation_name : str
            Stable identifier for metrics/logging (e.g., "player.update_lumees").
        context : Optional[dict[str, Any]]
            Additional structured context for logs.

        Returns
        -------
        T
            Result from successful operation execution.

        Raises
        ------
        BaseException
            Propagates the last exception when retries exhausted or
            when a non-retriable exception occurs.

        Notes
        -----
        - Always re-raises final exception after exhausting retries
        - Metrics emitted for every attempt and final give-up
        - Backoff includes random jitter to prevent thundering herd
        - Non-retriable exceptions fail immediately without retry

        Examples
        --------
        >>> async def update_player():
        >>>     async with DatabaseService.get_transaction() as session:
        >>>         player = await session.get(Player, 123, with_for_update=True)
        >>>         player.lumees += 1000
        >>>
        >>> retry_policy = DatabaseRetryPolicy.from_config()
        >>> await retry_policy.execute(
        >>>     update_player,
        >>>     operation_name="player.update_lumees",
        >>>     context={"player_id": 123, "amount": 1000}
        >>> )
        """
        # Build context for logging
        ctx_extra = context.copy() if context else {}
        ctx_extra["operation"] = operation_name

        attempt = 0

        while True:
            attempt += 1

            try:
                logger.debug(
                    "Executing database operation with retry policy",
                    extra={**ctx_extra, "attempt": attempt},
                )

                result = await operation()
                return result

            except Exception as exc:
                error_type = type(exc).__name__
                retriable = self._is_retriable(exc)
                will_retry = retriable and attempt < self._config.max_attempts

                # Record attempt metrics
                DatabaseMetrics.record_retry_attempt(
                    operation=operation_name,
                    attempt=attempt,
                    will_retry=will_retry,
                    error_type=error_type,
                )

                # Log failure
                logger.warning(
                    "Database operation failed",
                    extra={
                        **ctx_extra,
                        "attempt": attempt,
                        "error_type": error_type,
                        "retriable": retriable,
                        "will_retry": will_retry,
                    },
                    exc_info=True,
                )

                # Determine if we should retry
                if not retriable or not will_retry:
                    # Record give-up metrics
                    DatabaseMetrics.record_retry_give_up(
                        operation=operation_name,
                        attempt=attempt,
                        error_type=error_type,
                    )

                    # Log exhaustion
                    logger.error(
                        "Database operation retries exhausted or not retriable",
                        extra={
                            **ctx_extra,
                            "attempt": attempt,
                            "error_type": error_type,
                            "retriable": retriable,
                            "max_attempts": self._config.max_attempts,
                        },
                    )

                    raise

                # Compute backoff and sleep
                backoff_ms = self._compute_backoff_ms(attempt)

                logger.debug(
                    "Backing off before retry",
                    extra={
                        **ctx_extra,
                        "attempt": attempt,
                        "backoff_ms": backoff_ms,
                    },
                )

                await asyncio.sleep(backoff_ms / 1000.0)

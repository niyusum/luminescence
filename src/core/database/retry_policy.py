"""
Database retry policy utilities for Lumen 2025.

Purpose
-------
Provide a configurable, infra-pure retry policy for transient database
failures, such as connection drops or deadlocks, with:

- Config-driven maximum attempts and backoff timings.
- Jitter to avoid thundering herds.
- Metrics and structured logs for each attempt and final outcome.

Responsibilities
----------------
- Execute an async callable with retry semantics.
- Classify retriable vs non-retriable errors (OperationalError, DBAPIError).
- Emit metrics via `DatabaseMetrics` for attempts and give-ups.
- Avoid domain-level concerns; the caller owns business semantics.

Non-Responsibilities
--------------------
- Does not manage transactions (callers should wrap operations with
  `DatabaseService.get_transaction()` as appropriate).
- Does not know about domain services, models, or Discord.

Design Notes
------------
- This is a generic infra primitive that can be reused by services performing
  database operations that may legitimately be retried.
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

T = TypeVar("T")


@dataclass
class DatabaseRetryConfig:
    """Configuration for database retry behavior."""

    max_attempts: int
    initial_backoff_ms: int
    max_backoff_ms: int
    jitter_ms: int
    retriable_exceptions: Tuple[Type[BaseException], ...] = (
        OperationalError,
        DBAPIError,
    )

    @classmethod
    def from_config(cls) -> "DatabaseRetryConfig":
        """
        Build config from global Config values with safe defaults.

        All values are read from Config to comply with Lumen's config-driven
        behavior rule.
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


class DatabaseRetryPolicy:
    """
    Execute async operations against the database with retry semantics.

    Typical usage
    -------------
    >>> retry_policy = DatabaseRetryPolicy.from_config()
    >>> async def op():
    ...     async with DatabaseService.get_transaction() as session:
    ...         ...
    >>> result = await retry_policy.execute(op, operation_name="player.update_lumees")
    """

    def __init__(self, config: DatabaseRetryConfig) -> None:
        self._config = config

    @classmethod
    def from_config(cls) -> "DatabaseRetryPolicy":
        return cls(DatabaseRetryConfig.from_config())

    def _is_retriable(self, exc: BaseException) -> bool:
        return isinstance(exc, self._config.retriable_exceptions)

    def _compute_backoff_ms(self, attempt: int) -> int:
        """Exponential backoff with jitter, bounded by max_backoff_ms."""
        base = self._config.initial_backoff_ms * (2 ** max(attempt - 1, 0))
        capped = min(base, self._config.max_backoff_ms)
        jitter = random.randint(0, self._config.jitter_ms) if self._config.jitter_ms > 0 else 0
        return capped + jitter

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        operation_name: str,
        context: Optional[dict[str, Any]] = None,
    ) -> T:
        """
        Execute `operation` with retries for transient database errors.

        Parameters
        ----------
        operation:
            Zero-arg async callable performing the actual DB work.
        operation_name:
            Stable identifier for metrics/logging (e.g. "player.update_lumees").
        context:
            Optional additional structured context for logs.

        Raises
        ------
        BaseException
            Propagates the last encountered exception when retries are exhausted
            or a non-retriable exception occurs.
        """
        ctx_extra = context.copy() if context else {}
        ctx_extra.update({"operation": operation_name})

        attempt = 0
        while True:
            attempt += 1
            try:
                logger.debug(
                    "Executing database operation with retry",
                    extra={**ctx_extra, "attempt": attempt},
                )
                result = await operation()
                return result
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                retriable = self._is_retriable(exc)
                will_retry = retriable and attempt < self._config.max_attempts

                DatabaseMetrics.record_retry_attempt(
                    operation=operation_name,
                    attempt=attempt,
                    will_retry=will_retry,
                    error_type=error_type,
                )

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

                if not retriable or not will_retry:
                    DatabaseMetrics.record_retry_give_up(
                        operation=operation_name,
                        attempt=attempt,
                        error_type=error_type,
                    )
                    logger.error(
                        "Database operation retries exhausted or not retriable",
                        extra={
                            **ctx_extra,
                            "attempt": attempt,
                            "error_type": error_type,
                            "retriable": retriable,
                        },
                    )
                    raise

                backoff_ms = self._compute_backoff_ms(attempt)
                logger.debug(
                    "Backing off before retrying database operation",
                    extra={
                        **ctx_extra,
                        "attempt": attempt,
                        "backoff_ms": backoff_ms,
                    },
                )
                await asyncio.sleep(backoff_ms / 1000.0)

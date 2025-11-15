"""
Query Observer - Infrastructure Observability Helper (Lumen 2025)

Purpose
-------
Lightweight, opt-in query observability helpers that measure latency and
success/failure of database operations and emit metrics to DatabaseMetrics.

Provides an async context manager for wrapping individual logical database
operations with automatic timing, success tracking, and metrics emission.

Responsibilities
----------------
- Measure query execution time with high precision
- Track success/failure status and error types
- Emit metrics via DatabaseMetrics for monitoring
- Emit structured logs for debugging and diagnostics
- Support optional tagging for dimensionality

Non-Responsibilities
--------------------
- Altering SQLAlchemy behavior or query execution
- Automatic instrumentation (must be explicitly wrapped)
- Attaching SQLAlchemy event listeners
- Domain logic or business rules
- Discord integration

LUMEN 2025 Compliance
---------------------
✓ Article I: No state mutations, observability only
✓ Article II: Comprehensive structured logging
✓ Article III: Config-agnostic (pure infrastructure)
✓ Article IX: Graceful degradation (always completes)
✓ Article X: Maximum observability via metrics and logs

Architecture Notes
------------------
**Opt-In Design**:
- Nothing runs automatically
- Caller explicitly wraps operations in track_query()
- No global hooks or event listeners
- Minimal performance overhead

**Usage Pattern**:
```python
async with QueryObserver.track_query("Player.select_by_id") as ctx:
    player = await session.get(Player, player_id)
```

**Context Object**:
- QueryContext dataclass provided to caller
- Contains operation metadata and outcome
- Can be used for additional logging/metrics

**Error Handling**:
- Exceptions are always re-raised
- Metrics and logs still emitted on failure
- Error type captured for diagnostics

Configuration
-------------
No configuration required. Uses DatabaseMetrics backend configured elsewhere.

Usage Example
-------------
Basic query tracking:

>>> from src.core.database.query_observer import QueryObserver
>>> from src.core.database.service import DatabaseService
>>>
>>> async with DatabaseService.get_transaction() as session:
>>>     async with QueryObserver.track_query("Player.select_by_id") as ctx:
>>>         player = await session.get(Player, player_id, with_for_update=True)
>>>     # Metrics automatically recorded

With extra tags:

>>> async with QueryObserver.track_query(
>>>     "Inventory.bulk_update",
>>>     extra_tags={"shard": "shard_1", "module": "fusion"}
>>> ) as ctx:
>>>     await session.execute(update_stmt)

Multiple operations in sequence:

>>> async with DatabaseService.get_transaction() as session:
>>>     async with QueryObserver.track_query("Player.select") as ctx:
>>>         player = await session.get(Player, player_id, with_for_update=True)
>>>
>>>     async with QueryObserver.track_query("Player.update_lumees") as ctx:
>>>         player.lumees += 1000
>>>
>>>     async with QueryObserver.track_query("TransactionLog.create") as ctx:
>>>         log = TransactionLog(player_id=player.id, change=1000)
>>>         session.add(log)

Error handling example:

>>> try:
>>>     async with QueryObserver.track_query("risky_operation") as ctx:
>>>         await session.execute(risky_stmt)
>>> except Exception as exc:
>>>     # Metrics already recorded with error_type
>>>     logger.error(f"Operation failed: {exc}")
>>>     raise

Best Practices
--------------
**Operation Naming**:
- Use stable, descriptive names: "Model.operation"
- Good: "Player.select_by_id", "Inventory.bulk_update"
- Bad: "query1", "db_op", "select"

**Granularity**:
- Track logical operations, not individual statements
- One track_query() per semantic operation
- Combine related statements under single operation

**When to Use**:
- Performance-critical operations
- Operations with high failure rates
- Complex multi-statement operations
- Operations requiring detailed monitoring

**When to Skip**:
- Simple, fast operations with low value
- Already instrumented operations
- Operations with negligible failure rates
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

from src.core.logging.logger import get_logger
from src.core.database.metrics import DatabaseMetrics

logger = get_logger(__name__)


# ============================================================================
# Query Context
# ============================================================================


@dataclass
class QueryContext:
    """
    Context and outcome of an observed database query.

    Attributes
    ----------
    operation : str
        Stable operation identifier.
    duration_ms : float
        Query duration in milliseconds.
    success : bool
        True if query succeeded, False if exception raised.
    error_type : Optional[str]
        Exception type name if query failed, None otherwise.
    extra_tags : Optional[dict[str, Any]]
        Additional tags for metrics dimensionality.
    """

    operation: str
    duration_ms: float
    success: bool
    error_type: Optional[str]
    extra_tags: Optional[dict[str, Any]] = None


# ============================================================================
# Query Observer
# ============================================================================


class QueryObserver:
    """
    Static helpers for opt-in query observability.

    Provides track_query() context manager for timing and instrumenting
    database operations with automatic metrics emission.

    Public API
    ----------
    - track_query(operation, extra_tags) -> Async context manager

    Usage
    -----
    >>> async with QueryObserver.track_query("Player.select_by_id") as ctx:
    >>>     player = await session.get(Player, player_id)
    >>> # Metrics and logs automatically emitted
    """

    @staticmethod
    @asynccontextmanager
    async def track_query(
        operation: str,
        *,
        extra_tags: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[QueryContext, None]:
        """
        Time a logical database operation and emit metrics/logs.

        Measures execution time, tracks success/failure, captures error types,
        and emits all data to DatabaseMetrics for monitoring.

        Parameters
        ----------
        operation : str
            Stable, human-readable operation identifier.
            Use format: "Model.operation" (e.g., "Player.select_by_id").
        extra_tags : Optional[dict[str, Any]]
            Additional tags for metrics dimensionality (e.g., shard, module).

        Yields
        ------
        QueryContext
            Context object containing operation metadata and outcome.
            Updated with actual values upon exit.

        Notes
        -----
        - Always re-raises exceptions after recording metrics
        - Metrics and logs emitted even on failure
        - High-precision timing via time.perf_counter()
        - Zero overhead when DatabaseMetrics has no backend

        Examples
        --------
        >>> async with QueryObserver.track_query("Player.select") as ctx:
        >>>     player = await session.get(Player, player_id)
        >>>
        >>> async with QueryObserver.track_query(
        >>>     "Inventory.bulk_update",
        >>>     extra_tags={"module": "fusion"}
        >>> ) as ctx:
        >>>     await session.execute(update_stmt)
        """
        start = time.perf_counter()
        ctx = QueryContext(
            operation=operation,
            duration_ms=0.0,
            success=False,
            error_type=None,
            extra_tags=extra_tags,
        )

        try:
            yield ctx
            ctx.success = True

        except Exception as exc:
            ctx.success = False
            ctx.error_type = type(exc).__name__
            raise

        finally:
            ctx.duration_ms = (time.perf_counter() - start) * 1000.0

            # Emit metrics
            DatabaseMetrics.record_query(
                operation=ctx.operation,
                duration_ms=ctx.duration_ms,
                success=ctx.success,
                error_type=ctx.error_type,
                extra_tags=ctx.extra_tags,
            )

            # Emit structured log
            logger.debug(
                "Observed database query",
                extra={
                    "operation": ctx.operation,
                    "duration_ms": ctx.duration_ms,
                    "success": ctx.success,
                    "error_type": ctx.error_type,
                    "extra_tags": ctx.extra_tags,
                },
            )
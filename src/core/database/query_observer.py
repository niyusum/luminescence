"""
Query observer utilities for Lumen 2025.

Purpose
-------
Provide lightweight, opt-in query observability helpers that measure
latency and success/failure of arbitrary database operations and send
measurements to `DatabaseMetrics`.

Responsibilities
----------------
- Offer an async context manager (`track_query`) to wrap a single logical
  database operation (typically one or more SQLAlchemy calls).
- Record timing, success/failure, and error type into `DatabaseMetrics`.
- Emit structured logs for debugging and diagnostics.

Non-Responsibilities
--------------------
- Does not alter SQLAlchemy behavior.
- Does not attach SQLAlchemy event listeners automatically.
- Does not know anything about domain models or services.

Design Notes
------------
- This is intentionally **opt-in** and call-site driven. To instrument a query,
  wrap the relevant awaitable code in `track_query("operation_name")`.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional

from src.core.logging.logger import get_logger
from src.core.database.metrics import DatabaseMetrics

logger = get_logger(__name__)


@dataclass
class QueryContext:
    """Observed query context and outcome."""

    operation: str
    duration_ms: float
    success: bool
    error_type: Optional[str]
    extra_tags: Optional[Dict[str, Any]] = None


class QueryObserver:
    """
    Static helpers for query observability.

    Typical usage
    -------------
    >>> async with QueryObserver.track_query("Player.select") as ctx:
    ...     result = await session.execute(select(Player))

    The `ctx` instance is a `QueryContext` containing metadata about the
    just-finished operation.
    """

    @staticmethod
    @asynccontextmanager
    async def track_query(
        operation: str,
        *,
        extra_tags: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[QueryContext, None]:
        """
        Time a logical database operation and emit metrics/logs.

        Parameters
        ----------
        operation:
            A stable, human-readable identifier for the operation, e.g.
            "Player.select_by_id" or "Inventory.bulk_update".
        extra_tags:
            Optional dictionary of additional tags (shard, module, etc.).
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

            DatabaseMetrics.record_query(
                operation=ctx.operation,
                duration_ms=ctx.duration_ms,
                success=ctx.success,
                error_type=ctx.error_type,
                extra_tags=ctx.extra_tags,
            )

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

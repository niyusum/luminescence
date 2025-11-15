"""
Error Handling Helpers for Lumen EventBus (2025).

Purpose
-------
Provides centralized error handling utilities for event listener execution,
ensuring consistent error logging, metrics recording, and error isolation.

Responsibilities
----------------
- Log listener execution errors with full context
- Update metrics when errors occur
- Provide consistent error formatting
- Ensure error isolation (one failing listener doesn't affect others)

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides error handling utilities
for the event system.

Design Decisions
----------------
- **Centralized error handling**: Single function for all listener errors
- **Full error context**: Logs event name, listener ID, priority, and stack trace
- **Metrics integration**: Optionally updates error metrics
- **Type safety**: Proper type hints for all parameters

Dependencies
------------
- src.core.event.types (EventListener)
- src.core.event.metrics (EventMetricsRecorder)
- logging.Logger (for structured logging)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Structured logging
✓ Metrics integration
✓ Error isolation pattern
"""

from __future__ import annotations

from logging import Logger
from typing import Optional

from src.core.event.types import EventListener
from src.core.event.metrics import EventMetricsRecorder


def handle_listener_error(
    *,
    logger: Logger,
    event_name: str,
    listener: EventListener,
    exc: Exception,
    metrics: Optional[EventMetricsRecorder],
) -> None:
    """
    Log listener execution error and update metrics.

    This function provides centralized error handling for all listener
    execution failures, ensuring consistent logging and metrics recording.

    Parameters
    ----------
    logger:
        Logger instance to use for error logging.
    event_name:
        Name of the event that was being processed.
    listener:
        The EventListener that raised the exception.
    exc:
        The exception that was raised.
    metrics:
        Optional EventMetricsRecorder to update. If None, metrics are skipped.

    Notes
    -----
    This function never raises exceptions. It provides error isolation by
    catching and logging all listener errors.

    Examples
    --------
    >>> try:
    ...     await listener.callback(payload)
    ... except Exception as exc:
    ...     handle_listener_error(
    ...         logger=logger,
    ...         event_name="player.level_up",
    ...         listener=listener,
    ...         exc=exc,
    ...         metrics=metrics_recorder,
    ...     )
    """
    # Update metrics if enabled
    if metrics is not None:
        metrics.record_error(event_name)

    # Log error with full context and stack trace
    logger.error(
        "EventBus listener error",
        extra={
            "event_name": event_name,
            "listener_id": listener.identifier,
            "priority": listener.priority.name,
            "error": str(exc),
            "error_type": type(exc).__name__,
        },
        exc_info=True,
    )

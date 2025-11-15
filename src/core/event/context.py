"""
Event Log Context Helpers for Lumen EventBus (2025).

Purpose
-------
Provides utilities for enriching LogContext with event-specific metadata,
enabling better structured logging and observability throughout event dispatch.

Responsibilities
----------------
- Apply event name and payload keys to LogContext
- Gracefully handle failures without breaking event dispatch
- Support structured logging throughout the event system

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides logging utilities for
the event system.

Design Decisions
----------------
- **Best-effort context**: Never allows logging setup to break event dispatch
- **Minimal payload exposure**: Only logs payload keys, not values, to avoid
  logging sensitive data by default
- **Silent failure**: Swallows all exceptions to prevent log setup from
  disrupting business logic

Dependencies
------------
- src.core.logging.logger (LogContext utilities)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Graceful failure handling
✓ Privacy-conscious (only logs keys, not values)
"""

from __future__ import annotations

from typing import Any

from src.core.logging.logger import get_logger, set_log_context

logger = get_logger(__name__)


def apply_event_log_context(event_name: str, payload: dict[str, Any]) -> None:
    """
    Apply event-related fields to LogContext for structured logging.

    This enriches all subsequent log entries in the current async context with
    event metadata, making it easier to trace event flow through the system.

    Parameters
    ----------
    event_name:
        The name of the event being published.
    payload:
        The event payload dictionary. Only keys are logged, not values, to
        avoid accidentally logging sensitive data.

    Notes
    -----
    This is best-effort; failures are swallowed to avoid breaking event dispatch.
    Any exceptions are logged at debug level but never propagated.

    Examples
    --------
    >>> apply_event_log_context("player.level_up", {"player_id": 123, "new_level": 10})
    # Subsequent logs will include event_name and event_keys fields
    """
    try:
        set_log_context(
            event_name=event_name,
            event_keys=list(payload.keys()),
        )
    except Exception as exc:
        # Never let logging context setup break event dispatch.
        # Log at debug level since this is an internal issue.
        logger.debug(
            "Failed to apply event log context",
            extra={
                "event_name": event_name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
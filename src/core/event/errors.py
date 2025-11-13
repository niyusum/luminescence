"""
Error handling helpers for EventBus listener execution.
"""

from __future__ import annotations

from src.core.event.types import EventListener
from src.core.event.metrics import EventMetricsRecorder


def handle_listener_error(
    *,
    logger,
    event_name: str,
    listener: EventListener,
    exc: Exception,
    metrics: EventMetricsRecorder | None,
) -> None:
    """Log listener error and update metrics (if enabled)."""
    if metrics is not None:
        metrics.record_error(event_name)

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

"""
EventMetrics and EventMetricsRecorder for Lumen EventBus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
from collections import defaultdict


@dataclass
class EventMetrics:
    """Immutable snapshot of event bus metrics."""
    events_published: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    listener_errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_listeners: int = 0

    def get_summary(self) -> Dict[str, Any]:
        total_events = sum(self.events_published.values())
        total_errors = sum(self.listener_errors.values())
        error_rate = (total_errors / max(1, total_events)) * 100.0

        return {
            "total_events_published": total_events,
            "events_by_type": dict(self.events_published),
            "total_errors": total_errors,
            "errors_by_event": dict(self.listener_errors),
            "total_listeners": self.total_listeners,
            "error_rate": round(error_rate, 2),
        }


class EventMetricsRecorder:
    """
    Mutable metrics recorder for EventBus.

    Intended to be used from a single asyncio event loop.
    """

    def __init__(self) -> None:
        self._events_published = defaultdict(int)
        self._listener_errors = defaultdict(int)
        self._total_listeners = 0

    def record_publish(self, event_name: str) -> None:
        self._events_published[event_name] += 1

    def record_error(self, event_name: str) -> None:
        self._listener_errors[event_name] += 1

    @property
    def total_listeners(self) -> int:
        return self._total_listeners

    def increment_listener_count(self) -> None:
        self._total_listeners += 1

    def decrement_listener_count(self) -> None:
        self._total_listeners = max(0, self._total_listeners - 1)

    def reset_listener_count(self) -> None:
        self._total_listeners = 0

    def adjust_listener_count(self, delta: int) -> None:
        self._total_listeners = max(0, self._total_listeners + delta)

    def snapshot(self) -> EventMetrics:
        """
        Return an immutable snapshot of metrics.

        Uses new defaultdict instances to prevent accidental mutation leaks.
        """
        events_copy = defaultdict(int, self._events_published)
        errors_copy = defaultdict(int, self._listener_errors)
        return EventMetrics(
            events_published=events_copy,
            listener_errors=errors_copy,
            total_listeners=self._total_listeners,
        )

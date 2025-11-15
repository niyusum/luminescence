"""
EventMetrics and EventMetricsRecorder for Lumen EventBus (2025).

Purpose
-------
Provides metrics collection and reporting for the EventBus, enabling observability
into event publishing, listener execution, and error rates.

Responsibilities
----------------
- Record event publishes by event name
- Record listener errors by event name
- Track total listener count
- Provide immutable snapshots of metrics
- Generate formatted metric summaries

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides observability primitives
for the event system.

Design Decisions
----------------
- **Immutable snapshots**: EventMetrics is frozen; mutations go through recorder
- **Defaultdict usage**: Simplifies counting without key existence checks
- **Dataclass pattern**: Clean, typed data structures
- **Separation**: Recorder (mutable) vs Metrics (immutable snapshot)

Dependencies
------------
- dataclasses (Python stdlib)
- collections.defaultdict (Python stdlib)
- typing (Python stdlib)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Immutable snapshots
✓ Observable and measurable
✓ Clean data structures
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventMetrics:
    """
    Immutable snapshot of event bus metrics.

    This class provides a point-in-time view of EventBus metrics. It cannot
    be modified after creation, ensuring thread-safe reads.

    Attributes
    ----------
    events_published:
        Mapping of event names to publish counts.
    listener_errors:
        Mapping of event names to error counts.
    total_listeners:
        Current total number of registered listeners.

    Examples
    --------
    >>> metrics = EventMetrics(
    ...     events_published={"player.level_up": 42},
    ...     listener_errors={"player.level_up": 1},
    ...     total_listeners=10,
    ... )
    >>> summary = metrics.get_summary()
    >>> print(summary["error_rate"])
    2.38
    """

    events_published: dict[str, int] = field(default_factory=dict)
    listener_errors: dict[str, int] = field(default_factory=dict)
    total_listeners: int = 0

    def get_summary(self) -> dict[str, Any]:
        """
        Generate a formatted summary of metrics.

        Returns
        -------
        dict[str, Any]:
            Summary containing:
            - total_events_published: Sum of all event publishes
            - events_by_type: Dict mapping event names to counts
            - total_errors: Sum of all errors
            - errors_by_event: Dict mapping event names to error counts
            - total_listeners: Current listener count
            - error_rate: Percentage of events that had errors (0-100)

        Examples
        --------
        >>> metrics = EventMetrics(
        ...     events_published={"player.level_up": 100},
        ...     listener_errors={"player.level_up": 5},
        ...     total_listeners=10,
        ... )
        >>> summary = metrics.get_summary()
        >>> summary["error_rate"]
        5.0
        """
        total_events = sum(self.events_published.values())
        total_errors = sum(self.listener_errors.values())

        # Calculate error rate, avoiding division by zero
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

    This class is intended to be used from a single asyncio event loop.
    It provides mutable tracking of event metrics and can generate immutable
    snapshots via the snapshot() method.

    Thread Safety
    -------------
    Not thread-safe. Designed for single-threaded asyncio usage where all
    mutations occur on the same event loop.

    Examples
    --------
    >>> recorder = EventMetricsRecorder()
    >>> recorder.record_publish("player.level_up")
    >>> recorder.record_error("player.level_up")
    >>> recorder.increment_listener_count()
    >>> metrics = recorder.snapshot()
    >>> print(metrics.total_listeners)
    1
    """

    def __init__(self) -> None:
        """Initialize empty metrics recorder."""
        self._events_published: defaultdict[str, int] = defaultdict(int)
        self._listener_errors: defaultdict[str, int] = defaultdict(int)
        self._total_listeners: int = 0

    def record_publish(self, event_name: str) -> None:
        """
        Record an event publish.

        Parameters
        ----------
        event_name:
            The name of the event that was published.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.record_publish("player.level_up")
        >>> recorder.record_publish("player.level_up")
        >>> recorder.snapshot().events_published["player.level_up"]
        2
        """
        self._events_published[event_name] += 1

    def record_error(self, event_name: str) -> None:
        """
        Record a listener error.

        Parameters
        ----------
        event_name:
            The name of the event during which the error occurred.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.record_error("player.level_up")
        >>> recorder.snapshot().listener_errors["player.level_up"]
        1
        """
        self._listener_errors[event_name] += 1

    @property
    def total_listeners(self) -> int:
        """
        Get current total listener count.

        Returns
        -------
        int:
            Current number of registered listeners.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.increment_listener_count()
        >>> recorder.total_listeners
        1
        """
        return self._total_listeners

    def increment_listener_count(self) -> None:
        """
        Increment the total listener count by 1.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.increment_listener_count()
        >>> recorder.total_listeners
        1
        """
        self._total_listeners += 1

    def decrement_listener_count(self) -> None:
        """
        Decrement the total listener count by 1.

        The count is clamped to 0 (never goes negative).

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.increment_listener_count()
        >>> recorder.decrement_listener_count()
        >>> recorder.total_listeners
        0
        """
        self._total_listeners = max(0, self._total_listeners - 1)

    def reset_listener_count(self) -> None:
        """
        Reset the total listener count to 0.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.increment_listener_count()
        >>> recorder.reset_listener_count()
        >>> recorder.total_listeners
        0
        """
        self._total_listeners = 0

    def adjust_listener_count(self, delta: int) -> None:
        """
        Adjust the total listener count by a delta value.

        The count is clamped to 0 (never goes negative).

        Parameters
        ----------
        delta:
            The amount to adjust the count by (positive or negative).

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.adjust_listener_count(5)
        >>> recorder.total_listeners
        5
        >>> recorder.adjust_listener_count(-3)
        >>> recorder.total_listeners
        2
        """
        self._total_listeners = max(0, self._total_listeners + delta)

    def snapshot(self) -> EventMetrics:
        """
        Return an immutable snapshot of current metrics.

        Creates new dict instances to prevent accidental mutation leaks.

        Returns
        -------
        EventMetrics:
            Frozen snapshot of current metrics state.

        Examples
        --------
        >>> recorder = EventMetricsRecorder()
        >>> recorder.record_publish("player.level_up")
        >>> snapshot = recorder.snapshot()
        >>> snapshot.events_published["player.level_up"]
        1
        """
        return EventMetrics(
            events_published=dict(self._events_published),
            listener_errors=dict(self._listener_errors),
            total_listeners=self._total_listeners,
        )

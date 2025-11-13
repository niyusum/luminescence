"""
Core event types for Lumen EventBus.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Awaitable, Optional, Union

EventPayload = Dict[str, Any]


class ListenerPriority(Enum):
    """Priority levels for event listeners."""
    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


CallbackType = Union[Callable[[EventPayload], Any], Callable[[EventPayload], Awaitable[Any]]]


@dataclass(slots=True)
class EventListener:
    """
    Represents a registered event listener.

    Attributes
    ----------
    callback:
        Async or sync callable invoked with the event payload.
    priority:
        ListenerPriority, used by the scheduler.
    identifier:
        Logical identifier for dedup + unsubscription.
    once:
        If True, removed from registry before first execution.
    """

    callback: CallbackType
    priority: ListenerPriority
    identifier: str
    once: bool = False

    @classmethod
    def from_callback(
        cls,
        event_name: str,
        callback: CallbackType,
        priority: ListenerPriority,
        identifier: Optional[str],
        once: bool,
    ) -> "EventListener":
        if identifier is None:
            module = getattr(callback, "__module__", "unknown")
            qualname = getattr(callback, "__qualname__", getattr(callback, "__name__", "callback"))
            identifier = f"{module}.{qualname}@{event_name}"
        return cls(callback=callback, priority=priority, identifier=identifier, once=once)

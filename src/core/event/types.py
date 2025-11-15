"""
Core Event Types for Lumen EventBus (2025).

Purpose
-------
Provides fundamental type definitions for the event system, including event
payloads, listener priorities, callback types, and listener data structures.

Responsibilities
----------------
- Define EventPayload type alias
- Define ListenerPriority enumeration
- Define CallbackType union for async/sync callbacks
- Define EventListener dataclass
- Provide factory method for creating EventListener instances

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides type definitions used
throughout the event system.

Design Decisions
----------------
- **EventPayload as dict**: Simple, flexible, JSON-serializable structure
- **ListenerPriority enum**: Explicit priority levels with numeric values
  for stable sorting
- **CallbackType union**: Supports both async and sync callbacks seamlessly
- **EventListener with slots**: Memory-efficient dataclass for listener metadata
- **Factory pattern**: from_callback() provides clean listener creation with
  auto-generated identifiers

Priority Levels
---------------
- CRITICAL (0): Sequential, awaited, timeout-protected. Use for critical
  gameplay state mutations.
- HIGH (10): Sequential, awaited, timeout-protected. Use for important
  game logic and rewards.
- NORMAL (50): Concurrent, awaited. Use for analytics and notifications.
- LOW (100): Fire-and-forget. Use for logging and metrics.

Dependencies
------------
- dataclasses (Python stdlib)
- enum (Python stdlib)
- typing (Python stdlib)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Modern Python patterns
✓ Memory-efficient (slots)
✓ Clean factory pattern
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Union

# Type alias for event payload
# Simple dict structure that should be JSON-serializable for best observability
EventPayload = dict[str, Any]


class ListenerPriority(Enum):
    """
    Priority levels for event listeners.

    The numeric values determine execution order (lower = earlier).
    These values are used by the scheduler to partition and order listeners.

    Values
    ------
    CRITICAL (0):
        Sequential execution with timeout protection.
        Use for: critical gameplay state mutations, integrity checks.

    HIGH (10):
        Sequential execution with timeout protection.
        Use for: important game logic, rewards, progression.

    NORMAL (50):
        Concurrent execution (asyncio.gather).
        Use for: analytics, notifications, moderate-priority side effects.

    LOW (100):
        Fire-and-forget background tasks.
        Use for: logging, metrics, low-priority analytics.

    Examples
    --------
    >>> priority = ListenerPriority.CRITICAL
    >>> priority.value
    0
    >>> priority.name
    'CRITICAL'
    """

    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


# Type alias for listener callbacks
# Supports both sync and async callables taking a single EventPayload parameter
CallbackType = Union[
    Callable[[EventPayload], Any],
    Callable[[EventPayload], Awaitable[Any]],
]


@dataclass(slots=True, frozen=True)
class EventListener:
    """
    Represents a registered event listener.

    This is an immutable data structure containing all metadata needed to
    execute a listener callback.

    Attributes
    ----------
    callback:
        Async or sync callable invoked with the event payload.
    priority:
        ListenerPriority enum value determining execution order and concurrency.
    identifier:
        Unique string identifier for deduplication and unsubscription.
    once:
        If True, the listener is removed from the registry before its first
        execution (one-shot listener).

    Examples
    --------
    >>> def my_callback(payload: EventPayload) -> None:
    ...     print(f"Received: {payload}")
    ...
    >>> listener = EventListener(
    ...     callback=my_callback,
    ...     priority=ListenerPriority.NORMAL,
    ...     identifier="my_module.my_callback@player.level_up",
    ...     once=False,
    ... )
    >>> listener.priority.name
    'NORMAL'
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
    ) -> EventListener:
        """
        Factory method to create an EventListener with auto-generated identifier.

        Parameters
        ----------
        event_name:
            Name of the event this listener is registered for.
        callback:
            The callback function (async or sync).
        priority:
            ListenerPriority enum value.
        identifier:
            Optional explicit identifier. If None, auto-generates one from
            callback metadata and event name.
        once:
            If True, listener will be removed before its first execution.

        Returns
        -------
        EventListener:
            New immutable EventListener instance.

        Examples
        --------
        >>> def my_callback(payload: EventPayload) -> None:
        ...     pass
        ...
        >>> listener = EventListener.from_callback(
        ...     event_name="player.level_up",
        ...     callback=my_callback,
        ...     priority=ListenerPriority.NORMAL,
        ...     identifier=None,  # Auto-generated
        ...     once=False,
        ... )
        >>> listener.identifier
        'mymodule.my_callback@player.level_up'
        """
        # Auto-generate identifier if not provided
        if identifier is None:
            module = getattr(callback, "__module__", "unknown")
            qualname = getattr(
                callback, "__qualname__", getattr(callback, "__name__", "callback")
            )
            identifier = f"{module}.{qualname}@{event_name}"

        return cls(
            callback=callback,
            priority=priority,
            identifier=identifier,
            once=once,
        )
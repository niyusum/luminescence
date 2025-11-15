"""
ListenerRegistry: Storage and lookup for EventBus listeners (2025).

Purpose
-------
Provides efficient storage and retrieval of event listeners, supporting both
exact event names and wildcard patterns.

Responsibilities
----------------
- Store exact event listeners (e.g., "player.level_up")
- Store wildcard event listeners (e.g., "player.*", "*.created")
- Retrieve all listeners matching an event name (exact + wildcard)
- Maintain deterministic listener ordering by priority and identifier
- Atomically prune once=True listeners during retrieval
- Prevent duplicate listener registration
- Provide introspection (counts, all event keys)

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides data storage primitives
for the event system.

Design Decisions
----------------
- **No async/await**: Registry methods are synchronous because asyncio's
  event loop is single-threaded, making dictionary mutations atomic between
  awaits. This avoids unnecessary locking complexity.
- **Deterministic ordering**: Listeners sorted by (priority, identifier) to
  ensure consistent execution order.
- **Atomic once-pruning**: extract_listeners_for_event() atomically retrieves
  and prunes once=True listeners to minimize race conditions.
- **Separation of exact/wildcard**: Different storage structures for efficiency.

Dependencies
------------
- src.core.event.types (EventListener)
- src.core.event.router (EventRouter for wildcard matching)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Deterministic ordering
✓ Atomic operations
✓ No async complexity where not needed
"""

from __future__ import annotations

from src.core.event.types import EventListener
from src.core.event.router import EventRouter


class ListenerRegistry:
    """
    Registry for event listeners (exact and wildcard).

    This class provides efficient storage and lookup for event listeners,
    supporting both exact event names and wildcard patterns.

    Thread Safety
    -------------
    Not thread-safe. Designed for single-threaded asyncio usage where all
    modifications occur on the same event loop. Dictionary mutations are
    atomic between awaits, so no explicit locking is needed.

    Examples
    --------
    >>> registry = ListenerRegistry()
    >>> listener = EventListener.from_callback(
    ...     event_name="player.level_up",
    ...     callback=my_callback,
    ...     priority=ListenerPriority.NORMAL,
    ...     identifier=None,
    ...     once=False,
    ... )
    >>> registry.add_listener("player.level_up", listener, allow_duplicates=False)
    True
    >>> listeners = registry.extract_listeners_for_event("player.level_up")
    >>> len(listeners)
    1
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        # Exact event name -> list of listeners
        self._listeners: dict[str, list[EventListener]] = {}

        # List of (wildcard_pattern, listener) tuples
        self._wildcard_listeners: list[tuple[str, EventListener]] = []

    # ------------------------------------------------------------------ #
    # Modification
    # ------------------------------------------------------------------ #

    def add_listener(
        self,
        event_name: str,
        listener: EventListener,
        *,
        allow_duplicates: bool,
    ) -> bool:
        """
        Register a listener for an event or wildcard pattern.

        Parameters
        ----------
        event_name:
            Event name like "player.level_up" or wildcard like "player.*".
        listener:
            EventListener to register.
        allow_duplicates:
            If False, prevents registering the same (event_name, identifier)
            twice. If True, allows duplicates.

        Returns
        -------
        bool:
            True if the listener was added, False if it was prevented as
            a duplicate.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> listener = EventListener(...)
        >>> registry.add_listener("player.level_up", listener, allow_duplicates=False)
        True
        >>> registry.add_listener("player.level_up", listener, allow_duplicates=False)
        False
        """
        # Wildcard patterns
        if "*" in event_name:
            if not allow_duplicates:
                # Check for existing listener with same identifier and pattern
                if any(
                    lst.identifier == listener.identifier
                    for pattern, lst in self._wildcard_listeners
                    if pattern == event_name
                ):
                    return False

            # Add wildcard listener as tuple
            self._wildcard_listeners.append((event_name, listener))

            # Sort by (priority, identifier) for deterministic ordering
            self._wildcard_listeners.sort(
                key=lambda pl: (pl[1].priority.value, pl[1].identifier)
            )
            return True

        # Exact patterns
        listeners = self._listeners.setdefault(event_name, [])

        if not allow_duplicates:
            # Check for existing listener with same identifier
            if any(lst.identifier == listener.identifier for lst in listeners):
                return False

        listeners.append(listener)

        # Sort by (priority, identifier) for deterministic ordering
        listeners.sort(key=lambda lst: (lst.priority.value, lst.identifier))
        return True

    def remove_listener(self, event_name: str, identifier: str) -> bool:
        """
        Remove a listener by identifier for a given event or wildcard pattern.

        Parameters
        ----------
        event_name:
            Event name or wildcard pattern used during subscription.
        identifier:
            Listener identifier to remove.

        Returns
        -------
        bool:
            True if a listener was removed, False otherwise.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> listener = EventListener(...)
        >>> registry.add_listener("player.level_up", listener, allow_duplicates=False)
        >>> registry.remove_listener("player.level_up", listener.identifier)
        True
        """
        removed = False

        # Remove from exact listeners
        if event_name in self._listeners:
            original_count = len(self._listeners[event_name])
            self._listeners[event_name] = [
                lst
                for lst in self._listeners[event_name]
                if lst.identifier != identifier
            ]
            removed = len(self._listeners[event_name]) < original_count

            # Clean up empty list
            if not self._listeners[event_name]:
                del self._listeners[event_name]

        # Remove from wildcard listeners
        original_wc_count = len(self._wildcard_listeners)
        self._wildcard_listeners = [
            (pattern, lst)
            for pattern, lst in self._wildcard_listeners
            if not (pattern == event_name and lst.identifier == identifier)
        ]
        removed = removed or (len(self._wildcard_listeners) < original_wc_count)

        return removed

    def clear_all(self) -> int:
        """
        Remove all listeners and return previous total count.

        Returns
        -------
        int:
            Total number of listeners before clearing.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> # ... add listeners ...
        >>> count = registry.clear_all()
        >>> registry.get_total_listener_count()
        0
        """
        total = self.get_total_listener_count()
        self._listeners.clear()
        self._wildcard_listeners.clear()
        return total

    # ------------------------------------------------------------------ #
    # Lookup & Once-Removal
    # ------------------------------------------------------------------ #

    def extract_listeners_for_event(self, event_name: str) -> list[EventListener]:
        """
        Atomically collect all listeners for an event and prune once=True listeners.

        This method:
        1. Collects all exact listeners for this event
        2. Collects all wildcard listeners matching this event
        3. Prunes once=True listeners from the registry
        4. Returns sorted list by (priority, identifier)

        This atomic operation minimizes race risk for one-shot listeners when
        multiple publish() calls are in flight.

        Parameters
        ----------
        event_name:
            The event name to match against.

        Returns
        -------
        list[EventListener]:
            All listeners that should receive this event, sorted by priority
            and identifier for deterministic execution order.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> # ... add listeners ...
        >>> listeners = registry.extract_listeners_for_event("player.level_up")
        >>> for listener in listeners:
        ...     await listener.callback(payload)
        """
        router = EventRouter()
        result: list[EventListener] = []

        # Process exact listeners
        exact_list = self._listeners.get(event_name, [])
        kept_exact: list[EventListener] = []

        for listener in exact_list:
            result.append(listener)
            # Keep non-once listeners
            if not listener.once:
                kept_exact.append(listener)

        # Update exact listeners (remove once=True)
        if kept_exact:
            self._listeners[event_name] = kept_exact
        elif event_name in self._listeners:
            # Remove key if no listeners remain
            del self._listeners[event_name]

        # Process wildcard listeners
        new_wildcards: list[tuple[str, EventListener]] = []

        for pattern, listener in self._wildcard_listeners:
            if router.matches(event_name, pattern):
                result.append(listener)
                # Only keep if not once=True
                if not listener.once:
                    new_wildcards.append((pattern, listener))
            else:
                # Keep non-matching wildcard listeners
                new_wildcards.append((pattern, listener))

        self._wildcard_listeners = new_wildcards

        # Sort combined results by (priority, identifier)
        # This ensures deterministic execution order
        result.sort(key=lambda lst: (lst.priority.value, lst.identifier))
        return result

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def get_listener_count_for_event(self, event_name: str) -> int:
        """
        Count listeners that would receive this event (exact + wildcard).

        Parameters
        ----------
        event_name:
            Event name to check.

        Returns
        -------
        int:
            Number of listeners that would receive this event.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> # ... add listeners ...
        >>> count = registry.get_listener_count_for_event("player.level_up")
        >>> print(f"Event has {count} listeners")
        """
        router = EventRouter()

        # Count exact listeners
        count = len(self._listeners.get(event_name, []))

        # Count matching wildcard listeners
        count += sum(
            1
            for pattern, _ in self._wildcard_listeners
            if router.matches(event_name, pattern)
        )

        return count

    def get_total_listener_count(self) -> int:
        """
        Return total number of registered listeners.

        Returns
        -------
        int:
            Total listener count (exact + wildcard).

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> # ... add listeners ...
        >>> total = registry.get_total_listener_count()
        >>> print(f"Total listeners: {total}")
        """
        total = sum(len(listeners) for listeners in self._listeners.values())
        total += len(self._wildcard_listeners)
        return total

    def get_all_event_keys(self) -> list[str]:
        """
        Return sorted list of all event names and wildcard patterns.

        Returns
        -------
        list[str]:
            Sorted, deduplicated list of all event keys.

        Examples
        --------
        >>> registry = ListenerRegistry()
        >>> # ... add listeners ...
        >>> events = registry.get_all_event_keys()
        >>> print(events)
        ['player.*', 'player.level_up', 'guild.created']
        """
        keys: list[str] = list(self._listeners.keys())
        keys.extend(pattern for pattern, _ in self._wildcard_listeners)
        return sorted(set(keys))

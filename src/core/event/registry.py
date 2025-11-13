"""
ListenerRegistry: storage and lookup for EventBus listeners.

Design
------
- Maintains:
  - _listeners: exact event name -> [EventListener]
  - _wildcard_listeners: (pattern, EventListener)[]
- No async/await inside registry methods.
  - The asyncio event loop is single-threaded; dictionary mutations are
    executed atomically between awaits.
  - This avoids the complexity of locks while still being safe for the
    intended usage pattern (subscriptions during startup; publish at runtime).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.core.event.types import EventListener
from src.core.event.router import EventRouter


class ListenerRegistry:
    """
    Registry for event listeners (exact and wildcard).

    This class is intentionally small and synchronous; callers ensure that all
    modifications occur on a single asyncio event loop.
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, List[EventListener]] = {}
        self._wildcard_listeners: List[Tuple[str, EventListener]] = []

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
        Register a listener.

        Returns True if added, False if prevented as duplicate.
        """
        # Wildcard patterns
        if "*" in event_name:
            if not allow_duplicates:
                if any(
                    l.identifier == listener.identifier
                    for pattern, l in self._wildcard_listeners
                    if pattern == event_name
                ):
                    return False
            self._wildcard_listeners.append(event_name, listener)  # type: ignore[arg-type]
            # sort by (priority, identifier) for deterministic ordering
            self._wildcard_listeners.sort(key=lambda pl: (pl[1].priority.value, pl[1].identifier))
            return True

        # Exact patterns
        listeners = self._listeners.setdefault(event_name, [])
        if not allow_duplicates and any(l.identifier == listener.identifier for l in listeners):
            return False

        listeners.append(listener)
        listeners.sort(key=lambda l: (l.priority.value, l.identifier))
        return True

    def remove_listener(self, event_name: str, identifier: str) -> bool:
        """
        Remove a listener by identifier for a given event or wildcard pattern.
        """
        removed = False

        if event_name in self._listeners:
            original = len(self._listeners[event_name])
            self._listeners[event_name] = [
                l for l in self._listeners[event_name] if l.identifier != identifier
            ]
            removed = removed or len(self._listeners[event_name]) < original

        original_wc = len(self._wildcard_listeners)
        self._wildcard_listeners = [
            (pattern, l)
            for pattern, l in self._wildcard_listeners
            if not (pattern == event_name and l.identifier == identifier)
        ]
        removed = removed or len(self._wildcard_listeners) < original_wc

        return removed

    def clear_all(self) -> int:
        """Remove all listeners and return previous total count."""
        total = self.get_total_listener_count()
        self._listeners.clear()
        self._wildcard_listeners.clear()
        return total

    # ------------------------------------------------------------------ #
    # Lookup & Once-removal
    # ------------------------------------------------------------------ #

    def extract_listeners_for_event(self, event_name: str) -> List[EventListener]:
        """
        Atomically collect all listeners that should receive this event
        (exact + wildcard) and prune once=True listeners from registry.

        This minimizes race risk for one-shot listeners when multiple publish()
        calls are in flight.
        """
        router = EventRouter()
        result: List[EventListener] = []

        # Exact listeners
        exact_list = self._listeners.get(event_name, [])
        kept_exact: List[EventListener] = []
        for listener in exact_list:
            result.append(listener)
            if not listener.once:
                kept_exact.append(listener)
        if kept_exact:
            self._listeners[event_name] = kept_exact
        elif event_name in self._listeners:
            # Remove key if no listeners remain.
            del self._listeners[event_name]

        # Wildcard listeners
        new_wildcards: List[Tuple[str, EventListener]] = []
        for pattern, listener in self._wildcard_listeners:
            if router.matches(event_name, pattern):
                result.append(listener)
                # Only keep wildcard listener if it's not once=True
                if not listener.once:
                    new_wildcards.append((pattern, listener))
            else:
                new_wildcards.append((pattern, listener))

        self._wildcard_listeners = new_wildcards

        # Already sorted by (priority, identifier) from add_listener
        # but exact + wildcard combined now need sort.
        result.sort(key=lambda l: (l.priority.value, l.identifier))
        return result

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def get_listener_count_for_event(self, event_name: str) -> int:
        """Count listeners that would receive this event (exact + wildcard)."""
        router = EventRouter()
        count = len(self._listeners.get(event_name, []))
        count += sum(
            1 for pattern, _ in self._wildcard_listeners if router.matches(event_name, pattern)
        )
        return count

    def get_total_listener_count(self) -> int:
        """Return total number of registered listeners."""
        total = sum(len(v) for v in self._listeners.values())
        total += len(self._wildcard_listeners)
        return total

    def get_all_event_keys(self) -> List[str]:
        """Return sorted list of all event names and wildcard patterns."""
        keys = list(self._listeners.keys())
        keys.extend(pattern for pattern, _ in self._wildcard_listeners)
        return sorted(set(keys))

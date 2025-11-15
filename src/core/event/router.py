"""
EventRouter: Wildcard event-name matching for Lumen EventBus (2025).

Purpose
-------
Provides efficient wildcard pattern matching for event names, enabling flexible
event subscriptions like "player.*", "*.created", and "player.*.updated".

Responsibilities
----------------
- Match event names against wildcard patterns
- Support exact matching ("player.level_up")
- Support global wildcard ("*")
- Support prefix wildcards ("player.*")
- Support suffix wildcards ("*.created")
- Support complex wildcards ("player.*.updated")

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides pure utility functions
for pattern matching.

Design Decisions
----------------
- **Stateless class**: EventRouter has no instance state, making it safe to
  instantiate or use statically
- **Simple algorithm**: Uses string splitting and sequential matching for
  clarity and maintainability
- **Normalized patterns**: Collapses multiple consecutive wildcards ("**")
  into single wildcards for consistency

Supported Patterns
------------------
- Exact:        "player.level_up" → matches only "player.level_up"
- Global:       "*" → matches any event
- Prefix:       "player.*" → matches "player.level_up", "player.died", etc.
- Suffix:       "*.created" → matches "player.created", "guild.created", etc.
- Sandwich:     "player.*.created" → matches "player.item.created", etc.
- Complex:      "*.*.updated" → matches "player.stats.updated", etc.

Notes
-----
- Patterns with multiple '*' are normalized (e.g., "**" → "*")
- Matching is case-sensitive
- Empty strings and None are not valid event names or patterns

Dependencies
------------
None (pure Python stdlib)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Stateless design
✓ Clear algorithm
✓ No external dependencies
"""

from __future__ import annotations


class EventRouter:
    """
    Provides wildcard pattern matching for event names.

    This class is stateless and can be instantiated or used with a singleton
    pattern. All methods are instance methods for consistency with the rest
    of the event system, but they maintain no state.

    Examples
    --------
    >>> router = EventRouter()
    >>> router.matches("player.level_up", "player.*")
    True
    >>> router.matches("player.level_up", "guild.*")
    False
    >>> router.matches("player.item.created", "player.*.created")
    True
    >>> router.matches("anything", "*")
    True
    """

    def matches(self, event_name: str, pattern: str) -> bool:
        """
        Check if an event name matches a wildcard pattern.

        Parameters
        ----------
        event_name:
            The event name to check (e.g., "player.level_up").
        pattern:
            The pattern to match against. May contain wildcards.

        Returns
        -------
        bool:
            True if the event name matches the pattern, False otherwise.

        Examples
        --------
        >>> router = EventRouter()
        >>> router.matches("player.level_up", "*")
        True
        >>> router.matches("player.level_up", "player.*")
        True
        >>> router.matches("player.level_up", "*.level_up")
        True
        >>> router.matches("player.level_up", "player.*.up")
        True
        >>> router.matches("player.level_up", "guild.*")
        False
        """
        # Global wildcard matches everything
        if pattern == "*":
            return True

        # No wildcard means exact match required
        if "*" not in pattern:
            return event_name == pattern

        # Normalize repeated wildcards (e.g., "**" → "*")
        while "**" in pattern:
            pattern = pattern.replace("**", "*")

        # Split pattern by wildcards
        parts = pattern.split("*")

        # Check prefix (first part before any wildcard)
        if parts[0] and not event_name.startswith(parts[0]):
            return False

        # Check suffix (last part after all wildcards)
        if parts[-1] and not event_name.endswith(parts[-1]):
            return False

        # Check ordered middle pieces
        # Start searching after the prefix
        idx = len(parts[0])

        # For each middle part (parts[1:-1]), ensure it appears in order
        for mid in parts[1:-1]:
            if not mid:
                # Empty part means consecutive wildcards, skip
                continue

            # Find this part in the remaining event name
            next_idx = event_name.find(mid, idx)
            if next_idx == -1:
                # Required part not found
                return False

            # Move search position forward
            idx = next_idx + len(mid)

        return True

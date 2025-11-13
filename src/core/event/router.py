"""
EventRouter: wildcard event-name matching for Lumen EventBus.

Supported patterns
------------------
- Exact:        "player.level_up"
- Global:       "*"
- Prefix:       "player.*"
- Suffix:       "*.created"
- Sandwich:     "player.*.created"

Notes
-----
- Patterns with multiple '*' are supported but normalized conceptually.
- This router is intentionally simple, in-process, and non-alloc heavy.
"""

from __future__ import annotations


class EventRouter:
    """Provides wildcard/event-name matching."""

    @staticmethod
    def matches(event_name: str, pattern: str) -> bool:
        # Global wildcard
        if pattern == "*":
            return True

        # No wildcard: exact match
        if "*" not in pattern:
            return event_name == pattern

        # Normalize repeated '*' as a single wildcard (e.g. '**' -> '*')
        while "**" in pattern:
            pattern = pattern.replace("**", "*")

        parts = pattern.split("*")

        # Check prefix
        if parts[0] and not event_name.startswith(parts[0]):
            return False

        # Check suffix
        if parts[-1] and not event_name.endswith(parts[-1]):
            return False

        # Check ordered middle pieces
        idx = len(parts[0])
        for mid in parts[1:-1]:
            if not mid:
                continue
            next_idx = event_name.find(mid, idx)
            if next_idx == -1:
                return False
            idx = next_idx + len(mid)

        return True

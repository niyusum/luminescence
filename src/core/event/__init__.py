"""
Event system for Lumen (2025).

Provides event bus, event types, listeners, and context management for
asynchronous event-driven architecture.
"""

from src.core.event.bus import EventBus
from src.core.event.context import apply_event_log_context
from src.core.event.types import CallbackType, EventListener, EventPayload, ListenerPriority

# Optional singleton
event_bus = EventBus()

__all__ = [
    "event_bus",
    "EventBus",
    "EventPayload",
    "ListenerPriority",
    "EventListener",
    "CallbackType",
    "apply_event_log_context",
]


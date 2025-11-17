"""
Event System for Lumen RPG (2025).

Purpose
-------
Provides a production-grade event-driven architecture with a global
singleton EventBus and optional system-level initialization utilities.
"""

from .bus import EventBus
from .context import apply_event_log_context
from .types import (
    CallbackType,
    EventListener,
    EventPayload,
    ListenerPriority,
)
from .setup import initialize_event_system, shutdown_event_system

# Global runtime singleton EventBus
event_bus = EventBus()

__all__ = [
    "event_bus",
    "EventBus",
    "EventPayload",
    "ListenerPriority",
    "EventListener",
    "CallbackType",
    "apply_event_log_context",
    "initialize_event_system",
    "shutdown_event_system",
]


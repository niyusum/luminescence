"""
Event System for Lumen RPG (2025).

Purpose
-------
Provides a production-grade, async event-driven architecture for decoupling
game modules and enabling observability, analytics, and side-effect handling.

Responsibilities
----------------
- Asynchronous publish/subscribe event bus
- Tiered concurrency (CRITICAL → HIGH → NORMAL → LOW)
- Wildcard event routing ("player.*", "*.created", etc.)
- Error isolation per listener
- Metrics collection and observability
- LogContext integration for structured logging

Architecture Compliance
-----------------------
This module is **infrastructure-layer** code that services and cogs depend on.
It enables event-driven decoupling without cross-module imports.

Design Decisions
----------------
- **Instance-based EventBus**: Allows testing and multiple bus instances
- **Singleton pattern**: Global `event_bus` instance for convenience
- **Tiered execution**: Preserves determinism for critical listeners while
  allowing concurrent execution for analytics/logging
- **Wildcard routing**: Enables flexible event subscriptions
- **Error isolation**: One failing listener never blocks others

Dependencies
------------
- src.core.logging (structured logging)
- src.core.config (ConfigManager for timeouts)

Lumen 2025 Compliance
---------------------
✓ Pure infrastructure layer
✓ No business logic
✓ Full type hints
✓ Structured logging
✓ Config-driven behavior
✓ Observable and measurable
✓ Error isolation
✓ Async-first design
"""

from src.core.event.bus import EventBus
from src.core.event.context import apply_event_log_context
from src.core.event.setup import initialize_event_system, shutdown_event_system
from src.core.event.types import (
    CallbackType,
    EventListener,
    EventPayload,
    ListenerPriority,
)

# Global singleton instance for application-wide use.
# Services and cogs should import this instance rather than creating new ones.
event_bus = EventBus()

__all__ = [
    # Primary singleton
    "event_bus",
    # Classes
    "EventBus",
    # Types
    "EventPayload",
    "ListenerPriority",
    "EventListener",
    "CallbackType",
    # Utilities
    "apply_event_log_context",
    # Lifecycle
    "initialize_event_system",
    "shutdown_event_system",
]

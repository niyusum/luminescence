"""
Event System Initialization for Lumen (2025)

Purpose
-------
Initialize all event listeners, consumers, and the event-driven architecture
during bot startup. This ensures all event subscriptions are registered before
the bot begins processing events.

Responsibilities
----------------
- Import listener modules to trigger their module-level subscriptions
- Instantiate and start event consumers (e.g., AuditConsumer)
- Store consumer references for graceful shutdown
- Provide shutdown mechanism to stop all consumers

Non-Responsibilities
--------------------
- Business logic (handled by services)
- Event routing (handled by EventBus)
- Event definitions (handled by individual modules)

Lumen 2025 Compliance
---------------------
- Centralized initialization for observability
- Graceful startup and shutdown
- Structured logging for all initialization steps
- Clean separation of concerns

Architecture Notes
------------------
- Called during bot setup_hook before "bot.setup_complete" event
- Stores consumer instances for cleanup during shutdown
- Listener modules use module-level subscriptions at import time
- Consumers must be explicitly started after instantiation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from src.core.logging.logger import get_logger

if TYPE_CHECKING:
    from src.modules.audit.consumer import AuditConsumer

logger = get_logger(__name__)

# Global registry of active consumers for shutdown
_active_consumers: List[AuditConsumer] = []


async def initialize_event_system() -> None:
    """
    Initialize all event listeners and consumers.

    This function:
    1. Imports listener modules to trigger their subscriptions
    2. Instantiates and starts event consumers
    3. Stores consumer references for graceful shutdown

    Should be called during bot setup, before the "bot.setup_complete" event
    is published.

    Raises
    ------
    Exception
        If any consumer fails to start (logged and re-raised)
    """
    logger.info("Initializing event system...")

    # ═══════════════════════════════════════════════════════════════════════
    # Import listener modules to trigger their subscriptions
    # ═══════════════════════════════════════════════════════════════════════

    # (No active listeners at this time)

    # ═══════════════════════════════════════════════════════════════════════
    # Initialize and start event consumers
    # ═══════════════════════════════════════════════════════════════════════

    # Audit Consumer
    try:
        from src.modules.audit.consumer import AuditConsumer
        from src.modules.audit.repository import AuditRepository
        from src.core.database.service import DatabaseService
        from src.core.event import event_bus

        # DatabaseService uses class methods, pass the class itself
        # (AuditRepository type hint is outdated from pre-refactor)
        audit_repo = AuditRepository(DatabaseService)  # type: ignore[arg-type]
        audit_consumer = AuditConsumer(event_bus, audit_repo)
        await audit_consumer.start()

        _active_consumers.append(audit_consumer)
        logger.info("✓ Audit consumer started")
    except ImportError as e:
        logger.warning(f"Audit consumer module not found: {e}")
    except Exception as e:
        logger.error(f"Failed to start audit consumer: {e}", exc_info=True)
        raise

    logger.info("Event system initialization complete")


async def shutdown_event_system() -> None:
    """
    Gracefully shutdown all event consumers.

    Should be called during bot shutdown to ensure:
    - All buffered events are flushed
    - Consumer background tasks are cancelled
    - Resources are cleaned up properly
    """
    logger.info("Shutting down event system...")

    for consumer in _active_consumers:
        try:
            await consumer.stop()
            logger.info(f"✓ {consumer.__class__.__name__} stopped")
        except Exception as e:
            logger.error(
                f"Error stopping {consumer.__class__.__name__}: {e}",
                exc_info=True,
            )

    _active_consumers.clear()
    logger.info("Event system shutdown complete")

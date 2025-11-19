"""
Lumen EventBus (2025): Production-grade async pub/sub with tiered concurrency.

Purpose
-------
Provides the core EventBus class implementing asynchronous publish/subscribe
with tiered listener execution, wildcard routing, and comprehensive observability.

Responsibilities
----------------
- Register/unregister event listeners with priorities
- Publish events to all matching listeners (exact + wildcard)
- Execute listeners according to tiered concurrency model:
  * CRITICAL: sequential, ordered, awaited with timeout
  * HIGH: sequential, ordered, awaited with timeout
  * NORMAL: concurrent (gather), awaited
  * LOW: fire-and-forget background tasks
- Error isolation (one failing listener never blocks others)
- Metrics collection and introspection
- LogContext integration for structured logging

Architecture Compliance
-----------------------
This is **infrastructure layer** code. It has zero business logic and is purely
a technical coordination mechanism for decoupling modules.

Design Decisions
----------------
- **Instance-based**: Allows multiple EventBus instances (useful for testing)
- **Tiered concurrency**: Balances determinism (CRITICAL/HIGH) with performance
  (NORMAL/LOW)
- **Wildcard support**: Enables flexible subscriptions like "player.*"
- **Error isolation**: Uses try/except per listener to prevent cascading failures
- **Config-driven timeouts**: Listener timeouts loaded from ConfigManager
- **Metrics optional**: Can be disabled for performance-critical scenarios

Dependencies
------------
- src.core.logging.logger (structured logging)
- src.core.config.config_manager (ConfigManager for timeout config)
- src.core.event.types (EventPayload, ListenerPriority, EventListener, CallbackType)
- src.core.event.registry (ListenerRegistry)
- src.core.event.router (EventRouter)
- src.core.event.scheduler (EventScheduler)
- src.core.event.metrics (EventMetricsRecorder, EventMetrics)
- src.core.event.context (apply_event_log_context)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Structured logging throughout
✓ Config-driven timeouts
✓ Observable via metrics
✓ Error isolation per listener
✓ Async-first design
✓ Deterministic listener ordering
"""

from __future__ import annotations

import inspect
from typing import Any, Optional

from src.core.logging.logger import get_logger
from src.core.config.manager import ConfigManager
from src.core.event.types import (
    CallbackType,
    EventListener,
    EventPayload,
    ListenerPriority,
)
from src.core.event.registry import ListenerRegistry
from src.core.event.router import EventRouter
from src.core.event.scheduler import EventScheduler
from src.core.event.metrics import EventMetrics, EventMetricsRecorder
from src.core.event.context import apply_event_log_context

logger = get_logger(__name__)


class EventBus:
    """
    Production-grade EventBus for Lumen RPG (2025).

    Implements tiered concurrency model:
    - CRITICAL: sequential, ordered, awaited with timeout
    - HIGH: sequential, ordered, awaited with timeout
    - NORMAL: concurrent (asyncio.gather), awaited
    - LOW: fire-and-forget background tasks

    This model preserves determinism for gameplay-critical listeners while
    allowing metrics, analytics, and logging to run concurrently in the background.

    Thread Safety
    -------------
    Designed for single-threaded asyncio usage. All methods must be called from
    the same event loop. Dictionary mutations are atomic between awaits.

    Examples
    --------
    >>> bus = EventBus()
    >>> bus.subscribe("player.level_up", on_level_up, priority=ListenerPriority.CRITICAL)
    >>> await bus.publish("player.level_up", {"player_id": 123, "new_level": 10})
    """

    def __init__(
        self,
        registry: Optional[ListenerRegistry] = None,
        router: Optional[EventRouter] = None,
        scheduler: Optional[EventScheduler] = None,
        metrics: Optional[EventMetricsRecorder] = None,
        config_manager: Optional[ConfigManager] = None,
        *,
        enable_metrics: bool = True,
        critical_timeout_seconds: Optional[float] = None,
        high_timeout_seconds: Optional[float] = None,
    ) -> None:
        """
        Initialize EventBus.

        Parameters
        ----------
        registry:
            Optional ListenerRegistry instance. Creates default if None.
        router:
            Optional EventRouter instance. Creates default if None.
        scheduler:
            Optional EventScheduler instance. Creates default if None.
        metrics:
            Optional EventMetricsRecorder. Creates default if None.
        config_manager:
            Optional ConfigManager instance for loading timeout config.
        enable_metrics:
            Whether to collect metrics. Default True.
        critical_timeout_seconds:
            Timeout for CRITICAL listeners. Uses config if None.
        high_timeout_seconds:
            Timeout for HIGH listeners. Uses config if None.
        """
        self._config_manager = config_manager
        self._registry = registry or ListenerRegistry()
        self._router = router or EventRouter()
        self._scheduler = scheduler or EventScheduler()
        self._metrics = metrics or EventMetricsRecorder()
        self._metrics_enabled = enable_metrics

        # Load listener timeouts from config with safe defaults.
        self._critical_timeout = self._load_timeout(
            key="core.event.listener_timeout.critical_seconds",
            override=critical_timeout_seconds,
            default=5.0,
        )
        self._high_timeout = self._load_timeout(
            key="core.event.listener_timeout.high_seconds",
            override=high_timeout_seconds,
            default=5.0,
        )

        logger.info(
            "EventBus initialized",
            extra={
                "metrics_enabled": self._metrics_enabled,
                "critical_timeout_seconds": self._critical_timeout,
                "high_timeout_seconds": self._high_timeout,
            },
        )

    # ------------------------------------------------------------------ #
    # Configuration Loading
    # ------------------------------------------------------------------ #

    def _load_timeout(self, key: str, override: Optional[float], default: float) -> float:
        """
        Load timeout value with fallback chain: override → config → default.

        Parameters
        ----------
        key:
            ConfigManager key to lookup.
        override:
            Optional direct override value.
        default:
            Fallback value if config lookup fails.

        Returns
        -------
        float:
            Resolved timeout in seconds.
        """
        if override is not None:
            return float(override)

        # If no config_manager provided, use default
        if self._config_manager is None:
            return float(default)

        try:
            value = self._config_manager.get(key, default)
            return float(value)
        except Exception as exc:
            logger.warning(
                "Failed to load timeout from config, using default",
                extra={
                    "config_key": key,
                    "default_value": default,
                    "error": str(exc),
                },
            )
            return float(default)

    # ------------------------------------------------------------------ #
    # Listener Validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_callback_signature(callback: CallbackType) -> None:
        """
        Ensure callback accepts exactly one parameter.

        This catches mis-registered listeners at subscription time rather than
        failing later at publish time.

        Parameters
        ----------
        callback:
            The callback function to validate.

        Raises
        ------
        ValueError:
            If callback signature is invalid.
        """
        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            # Built-ins or C-level callables may not expose a signature cleanly.
            # Trust the caller in this case.
            return

        params = list(sig.parameters.values())
        if len(params) != 1:
            callback_name = getattr(callback, "__qualname__", None) or getattr(
                callback, "__name__", repr(callback)
            )
            raise ValueError(
                f"Event listener must accept exactly 1 parameter (EventPayload), "
                f"got {len(params)} parameters for '{callback_name}'"
            )

    # ------------------------------------------------------------------ #
    # Subscription API
    # ------------------------------------------------------------------ #

    def subscribe(
        self,
        event_name: str,
        callback: CallbackType,
        *,
        priority: ListenerPriority = ListenerPriority.NORMAL,
        identifier: Optional[str] = None,
        once: bool = False,
        allow_duplicates: bool = False,
    ) -> str:
        """
        Subscribe a callback to an event.

        Parameters
        ----------
        event_name:
            Event name like "player.level_up" or wildcard like "player.*".
        callback:
            Async or sync callable taking a single EventPayload parameter.
        priority:
            ListenerPriority enum value (CRITICAL, HIGH, NORMAL, LOW).
        identifier:
            Optional unique identifier. Auto-generated if None.
        once:
            If True, listener is removed before its first execution.
        allow_duplicates:
            If False, prevents registering same (event_name, identifier) twice.

        Returns
        -------
        str:
            The listener identifier (for unsubscribing later).

        Raises
        ------
        ValueError:
            If callback signature is invalid.

        Examples
        --------
        >>> bus.subscribe("player.level_up", handle_level_up, priority=ListenerPriority.CRITICAL)
        >>> bus.subscribe("player.*", log_player_event, priority=ListenerPriority.LOW)
        """
        self._validate_callback_signature(callback)

        listener = EventListener.from_callback(
            event_name=event_name,
            callback=callback,
            priority=priority,
            identifier=identifier,
            once=once,
        )

        added = self._registry.add_listener(
            event_name=event_name,
            listener=listener,
            allow_duplicates=allow_duplicates,
        )

        if self._metrics_enabled and added:
            self._metrics.increment_listener_count()

        if added:
            logger.debug(
                "EventBus: subscribed listener",
                extra={
                    "event_name": event_name,
                    "listener_id": listener.identifier,
                    "priority": listener.priority.name,
                    "once": listener.once,
                },
            )
        else:
            logger.warning(
                "EventBus: duplicate listener prevented",
                extra={
                    "event_name": event_name,
                    "listener_id": listener.identifier,
                },
            )

        return listener.identifier

    def unsubscribe(self, event_name: str, identifier: str) -> bool:
        """
        Unsubscribe a listener from an event or wildcard pattern.

        Parameters
        ----------
        event_name:
            Event name or wildcard pattern used during subscription.
        identifier:
            Listener identifier returned from subscribe().

        Returns
        -------
        bool:
            True if a listener was removed, False otherwise.

        Examples
        --------
        >>> listener_id = bus.subscribe("player.level_up", callback)
        >>> bus.unsubscribe("player.level_up", listener_id)
        True
        """
        removed = self._registry.remove_listener(
            event_name=event_name, identifier=identifier
        )

        if removed and self._metrics_enabled:
            self._metrics.decrement_listener_count()

        if removed:
            logger.debug(
                "EventBus: unsubscribed listener",
                extra={"event_name": event_name, "listener_id": identifier},
            )

        return removed

    def clear(self) -> None:
        """
        Remove all listeners from all events.

        Primarily intended for tests or full system reinit.

        Examples
        --------
        >>> bus.clear()  # Remove all listeners
        """
        total = self._registry.clear_all()

        if self._metrics_enabled:
            self._metrics.reset_listener_count()

        logger.info(
            "EventBus: cleared all listeners",
            extra={"previous_listener_count": total},
        )

    # ------------------------------------------------------------------ #
    # Publish API
    # ------------------------------------------------------------------ #

    async def publish(self, event_name: str, data: EventPayload) -> list[Any]:
        """
        Publish an event to all subscribed listeners.

        Tiered concurrency is applied according to listener priority:
        - CRITICAL: sequential with timeout
        - HIGH: sequential with timeout
        - NORMAL: concurrent (asyncio.gather)
        - LOW: fire-and-forget background tasks

        Parameters
        ----------
        event_name:
            Name of the event to publish.
        data:
            Event payload dictionary. Should be JSON-serializable for best
            observability, but not enforced.

        Returns
        -------
        list[Any]:
            Results from CRITICAL/HIGH/NORMAL listeners. LOW-tier listeners
            are fire-and-forget and not included in the return value.

        Examples
        --------
        >>> await bus.publish("player.level_up", {
        ...     "player_id": 123,
        ...     "old_level": 9,
        ...     "new_level": 10,
        ... })
        """
        if self._metrics_enabled:
            self._metrics.record_publish(event_name)

        # Apply event context for structured logging.
        apply_event_log_context(event_name, data)

        logger.debug(
            "EventBus: publishing event",
            extra={
                "event_name": event_name,
                "payload_keys": list(data.keys()),
            },
        )

        # Atomically extract listeners and prune once=True listeners.
        listeners = self._registry.extract_listeners_for_event(event_name=event_name)

        if not listeners:
            logger.debug(
                "EventBus: no listeners for event",
                extra={"event_name": event_name},
            )
            return []

        logger.debug(
            "EventBus: executing listeners",
            extra={
                "event_name": event_name,
                "listener_count": len(listeners),
            },
        )

        results = await self._scheduler.execute(
            event_name=event_name,
            payload=data,
            listeners=listeners,
            metrics=self._metrics if self._metrics_enabled else None,
            logger=logger,
            critical_timeout=self._critical_timeout,
            high_timeout=self._high_timeout,
        )

        return results

    # ------------------------------------------------------------------ #
    # Metrics & Introspection
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> Optional[EventMetrics]:
        """
        Return an immutable snapshot of current event metrics.

        Returns
        -------
        Optional[EventMetrics]:
            Metrics snapshot if metrics are enabled, None otherwise.

        Examples
        --------
        >>> metrics = bus.get_metrics()
        >>> if metrics:
        ...     print(f"Total events: {sum(metrics.events_published.values())}")
        """
        if not self._metrics_enabled:
            return None
        return self._metrics.snapshot()

    def get_metrics_summary(self) -> dict[str, Any]:
        """
        Get a formatted metrics summary.

        Returns
        -------
        dict[str, Any]:
            Summary containing:
            - total_events_published: Total event count
            - events_by_type: Dict mapping event names to counts
            - total_errors: Total error count
            - errors_by_event: Dict mapping event names to error counts
            - total_listeners: Current listener count
            - error_rate: Percentage of events that had errors

        Examples
        --------
        >>> summary = bus.get_metrics_summary()
        >>> print(f"Error rate: {summary.get('error_rate', 0)}%")
        """
        metrics = self.get_metrics()
        if metrics is None:
            return {}
        return metrics.get_summary()

    def get_listener_count(self, event_name: Optional[str] = None) -> int:
        """
        Get the number of listeners.

        Parameters
        ----------
        event_name:
            If provided, returns count of listeners that would receive this
            event (including wildcard listeners). Otherwise returns total
            listener count.

        Returns
        -------
        int:
            Listener count.

        Examples
        --------
        >>> bus.get_listener_count()
        42
        >>> bus.get_listener_count("player.level_up")
        5
        """
        if event_name:
            return self._registry.get_listener_count_for_event(event_name)

        if self._metrics_enabled:
            return self._metrics.total_listeners

        return self._registry.get_total_listener_count()

    def get_all_events(self) -> list[str]:
        """
        Return a sorted list of all event names and wildcard patterns.

        Returns
        -------
        list[str]:
            Sorted list of event keys.

        Examples
        --------
        >>> bus.get_all_events()
        ['player.*', 'player.level_up', 'guild.created']
        """
        return self._registry.get_all_event_keys()

    # ------------------------------------------------------------------ #
    # Configuration Toggles
    # ------------------------------------------------------------------ #

    def enable_metrics(self) -> None:
        """
        Enable metrics collection.

        Examples
        --------
        >>> bus.enable_metrics()
        """
        if self._metrics is None:
            self._metrics = EventMetricsRecorder()
        self._metrics_enabled = True
        logger.info("EventBus: metrics enabled")

    def disable_metrics(self) -> None:
        """
        Disable metrics collection.

        Examples
        --------
        >>> bus.disable_metrics()
        """
        self._metrics_enabled = False
        logger.info("EventBus: metrics disabled")
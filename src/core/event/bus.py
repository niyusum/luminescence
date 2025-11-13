"""
Lumen EventBus (2025): instance-based async pub/sub with tiered concurrency.

Purpose
-------
Provide a single, composable EventBus instance with:

- Async publish/subscribe for game and infra events.
- Tiered concurrency (Option B):
  - CRITICAL: sequential & awaited
  - HIGH    : sequential & awaited
  - NORMAL  : concurrent (gather) & awaited
  - LOW     : fire-and-forget background tasks
- Error isolation per listener (one failing listener never blocks others).
- Optional metrics recording for observability.
- Wildcard routing ("player.*", "*.created", etc.).
- LogContext integration for event-name and payload metadata.

Design
------
This module defines the EventBus *class* only.
A concrete singleton instance is created in `event_bus.py` and should be used
by the rest of the application.

Dependencies
------------
- src.core.logging.logger.get_logger
- src.core.config.config_manager.ConfigManager
- src.core.event.event_types.EventListener, ListenerPriority, EventPayload
- src.core.event.event_registry.ListenerRegistry
- src.core.event.event_router.EventRouter
- src.core.event.event_scheduler.EventScheduler
- src.core.event.event_metrics.EventMetricsRecorder, EventMetrics
- src.core.event.event_context.apply_event_log_context
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Callable
import inspect

from src.core.logging.logger import get_logger
from src.core.config.config_manager import ConfigManager
from src.core.event.types import EventPayload, ListenerPriority, EventListener, CallbackType
from src.core.event.registry import ListenerRegistry
from src.core.event.router import EventRouter
from src.core.event.scheduler import EventScheduler
from src.core.event.metrics import EventMetricsRecorder, EventMetrics
from src.core.event.context import apply_event_log_context

logger = get_logger(__name__)


class EventBus:
    """
    Instance-based EventBus for Lumen (2025).

    Tiered concurrency model (Option B):
    - CRITICAL: sequential, ordered, awaited.
    - HIGH    : sequential, ordered, awaited.
    - NORMAL  : concurrent, awaited (asyncio.gather).
    - LOW     : fire-and-forget background tasks.

    This preserves determinism for gameplay-critical listeners, while allowing
    metrics/analytics/logging to run concurrently in the background.
    """

    def __init__(
        self,
        registry: Optional[ListenerRegistry] = None,
        router: Optional[EventRouter] = None,
        metrics: Optional[EventMetricsRecorder] = None,
        *,
        enable_metrics: bool = True,
        critical_timeout_seconds: Optional[float] = None,
        high_timeout_seconds: Optional[float] = None,
    ) -> None:
        self._registry = registry or ListenerRegistry()
        self._router = router or EventRouter()
        self._metrics = metrics or EventMetricsRecorder()
        self._metrics_enabled = enable_metrics

        # Listener timeouts for CRITICAL / HIGH tiers (seconds).
        # Config-driven with safe defaults.
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
                "critical_timeout_s": self._critical_timeout,
                "high_timeout_s": self._high_timeout,
            },
        )

    # ------------------------------------------------------------------ #
    # Internal utilities
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_timeout(key: str, override: Optional[float], default: float) -> float:
        if override is not None:
            return float(override)
        try:
            value = ConfigManager.get(key, default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _validate_callback_signature(callback: CallbackType) -> None:
        """
        Ensure callback accepts exactly one parameter.

        This catches mis-registered listeners at subscription time rather than
        failing later at publish time.
        """
        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            # Built-ins or C-level callables may not expose a signature cleanly.
            # In that case, we trust the caller.
            return

        params = list(sig.parameters.values())
        if len(params) != 1:
            raise ValueError(
                f"Event listener must accept exactly 1 parameter, "
                f"got {len(params)} for {getattr(callback, '__qualname__', callback)}"
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
            Exact name like "player.level_up" or wildcard like "player.*".
        callback:
            Async or sync callable taking a single `Dict[str, Any]` payload.
        priority:
            ListenerPriority; CRITICAL/HIGH/NORMAL/LOW.
        identifier:
            Optional unique identifier; if None, derived from callback + event.
        once:
            If True, the listener will be removed before its first execution.
        allow_duplicates:
            If False, registering the same (event_name, identifier) twice will
            be prevented.

        Returns
        -------
        str
            The listener identifier.
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

        if self._metrics_enabled and self._metrics is not None and added:
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

        Returns True if a listener was removed, False otherwise.
        """
        removed = self._registry.remove_listener(event_name=event_name, identifier=identifier)
        if removed and self._metrics_enabled and self._metrics is not None:
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
        """
        total = self._registry.clear_all()
        if self._metrics_enabled and self._metrics is not None:
            self._metrics.reset_listener_count()
        logger.info(
            "EventBus: cleared all listeners",
            extra={"previous_listener_count": total},
        )

    # ------------------------------------------------------------------ #
    # Publish API
    # ------------------------------------------------------------------ #

    async def publish(self, event_name: str, data: EventPayload) -> List[Any]:
        """
        Publish an event to all subscribed listeners.

        Tiered concurrency is applied according to listener priority.

        Parameters
        ----------
        event_name:
            Name of the event to publish.
        data:
            Event payload (may be any dict; JSON-serializable is recommended
            but not enforced here).

        Returns
        -------
        List[Any]
            Results from CRITICAL/HIGH/NORMAL listeners. LOW-tier listeners
            are fire-and-forget and not included in the return value.
        """
        if self._metrics_enabled and self._metrics is not None:
            self._metrics.record_publish(event_name)

        # Apply event context for logging.
        apply_event_log_context(event_name, data)

        logger.debug(
            "EventBus: publishing event",
            extra={"event_name": event_name, "payload_keys": list(data.keys())},
        )

        # Atomically extract listeners and prune once=True listeners inside registry
        listeners = self._registry.extract_listeners_for_event(
            event_name=event_name,
        )

        if not listeners:
            logger.debug(
                "EventBus: no listeners for event",
                extra={"event_name": event_name},
            )
            return []

        results = await EventScheduler.execute(
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
    # Metrics / Introspection
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> Optional[EventMetrics]:
        """Return a snapshot of the current event metrics."""
        if not self._metrics_enabled or self._metrics is None:
            return None
        return self._metrics.snapshot()

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get a formatted metrics summary.

        Returns
        -------
        Dict[str, Any]
            Summary containing counts and error rate.
        """
        metrics = self.get_metrics()
        if metrics is None:
            return {}
        return metrics.get_summary()

    def get_listener_count(self, event_name: Optional[str] = None) -> int:
        """
        Get the number of listeners.

        If event_name is provided, returns the count of listeners that would
        receive that event (including wildcard listeners). Otherwise returns
        total listener count.
        """
        if event_name:
            return self._registry.get_listener_count_for_event(event_name)

        if self._metrics_enabled and self._metrics is not None:
            return self._metrics.total_listeners

        return self._registry.get_total_listener_count()

    def get_all_events(self) -> List[str]:
        """Return a sorted list of all event names and wildcard patterns."""
        return self._registry.get_all_event_keys()

    # ------------------------------------------------------------------ #
    # Configuration toggles
    # ------------------------------------------------------------------ #

    def enable_metrics(self) -> None:
        """Enable metrics collection."""
        if self._metrics is None:
            self._metrics = EventMetricsRecorder()
        self._metrics_enabled = True

    def disable_metrics(self) -> None:
        """Disable metrics collection."""
        self._metrics_enabled = False


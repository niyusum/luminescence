"""
EventScheduler: Tiered concurrency execution for Lumen EventBus (2025).

Purpose
-------
Provides tiered execution of event listeners based on priority, implementing
the concurrency model that balances determinism with performance.

Responsibilities
----------------
- Execute CRITICAL listeners sequentially with timeout protection
- Execute HIGH listeners sequentially with timeout protection
- Execute NORMAL listeners concurrently (asyncio.gather)
- Execute LOW listeners as fire-and-forget background tasks
- Isolate listener errors (one failure doesn't affect others)
- Log execution details for observability
- Track background tasks to prevent premature garbage collection

Architecture Compliance
-----------------------
This is **infrastructure layer** code that provides execution coordination
for the event system.

Design Decisions
----------------
- **Tiered concurrency model**: Balances determinism (CRITICAL/HIGH) with
  performance (NORMAL/LOW)
- **Error isolation**: Each listener is try/except wrapped independently
- **Timeout protection**: CRITICAL and HIGH tiers have configurable timeouts
- **Background task tracking**: LOW-tier tasks are tracked in a set to prevent
  premature GC while maintaining fire-and-forget semantics
- **Sync callback support**: Sync callbacks are executed in thread pool executor

Execution Model (Tiered Concurrency)
------------------------------------
- CRITICAL (priority=0):
    - Sequential execution (one at a time, in order)
    - Awaited (blocking)
    - Timeout protected
    - Use for: critical gameplay state mutations, integrity checks

- HIGH (priority=10):
    - Sequential execution (one at a time, in order)
    - Awaited (blocking)
    - Timeout protected
    - Use for: important game logic, rewards, progression

- NORMAL (priority=50):
    - Concurrent execution (asyncio.gather, all at once)
    - Awaited (blocking until all complete)
    - No timeout
    - Use for: analytics, notifications, moderate-priority side effects

- LOW (priority=100):
    - Fire-and-forget background tasks
    - Not awaited (non-blocking)
    - No timeout
    - Use for: logging, metrics, low-priority analytics

Dependencies
------------
- asyncio (Python stdlib)
- src.core.event.types (EventListener, ListenerPriority, EventPayload)
- src.core.event.metrics (EventMetricsRecorder)
- src.core.event.errors (handle_listener_error)
- logging.Logger (for structured logging)

Lumen 2025 Compliance
---------------------
✓ Infrastructure layer only
✓ No business logic
✓ Full type hints
✓ Structured logging
✓ Error isolation
✓ Timeout protection
✓ Observable execution
"""

from __future__ import annotations

import asyncio
from logging import Logger
from typing import Any, Optional

from src.core.event.types import EventListener, EventPayload, ListenerPriority
from src.core.event.metrics import EventMetricsRecorder
from src.core.event.errors import handle_listener_error


class EventScheduler:
    """
    Executes event listeners according to the tiered concurrency model.

    This class provides the core execution logic for the EventBus, handling
    different priority tiers with appropriate concurrency strategies.

    Examples
    --------
    >>> scheduler = EventScheduler()
    >>> results = await scheduler.execute(
    ...     event_name="player.level_up",
    ...     payload={"player_id": 123},
    ...     listeners=[listener1, listener2],
    ...     metrics=metrics_recorder,
    ...     logger=logger,
    ...     critical_timeout=5.0,
    ...     high_timeout=5.0,
    ... )
    """

    def __init__(self) -> None:
        """Initialize the scheduler with background task tracking."""
        # Track background tasks to prevent premature garbage collection
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def execute(
        self,
        *,
        event_name: str,
        payload: EventPayload,
        listeners: list[EventListener],
        metrics: Optional[EventMetricsRecorder],
        logger: Logger,
        critical_timeout: Optional[float],
        high_timeout: Optional[float],
    ) -> list[Any]:
        """
        Execute listeners with tiered concurrency.

        Parameters
        ----------
        event_name:
            Name of the event being published.
        payload:
            Event payload dictionary.
        listeners:
            List of listeners to execute (already sorted by priority).
        metrics:
            Optional metrics recorder to update.
        logger:
            Logger instance for structured logging.
        critical_timeout:
            Timeout in seconds for CRITICAL listeners (None = no timeout).
        high_timeout:
            Timeout in seconds for HIGH listeners (None = no timeout).

        Returns
        -------
        list[Any]:
            Results from CRITICAL/HIGH/NORMAL listeners. LOW-tier listeners
            are fire-and-forget and not included in the return value.

        Examples
        --------
        >>> results = await scheduler.execute(
        ...     event_name="player.level_up",
        ...     payload={"player_id": 123},
        ...     listeners=listeners,
        ...     metrics=recorder,
        ...     logger=logger,
        ...     critical_timeout=5.0,
        ...     high_timeout=5.0,
        ... )
        """
        # Partition listeners by priority
        critical = [
            lst for lst in listeners if lst.priority == ListenerPriority.CRITICAL
        ]
        high = [lst for lst in listeners if lst.priority == ListenerPriority.HIGH]
        normal = [lst for lst in listeners if lst.priority == ListenerPriority.NORMAL]
        low = [lst for lst in listeners if lst.priority == ListenerPriority.LOW]

        results: list[Any] = []

        # CRITICAL: sequential with timeout
        for listener in critical:
            result = await self._run_with_timeout(
                listener=listener,
                event_name=event_name,
                payload=payload,
                metrics=metrics,
                logger=logger,
                tier="CRITICAL",
                timeout=critical_timeout,
            )
            results.append(result)

        # HIGH: sequential with timeout
        for listener in high:
            result = await self._run_with_timeout(
                listener=listener,
                event_name=event_name,
                payload=payload,
                metrics=metrics,
                logger=logger,
                tier="HIGH",
                timeout=high_timeout,
            )
            results.append(result)

        # NORMAL: concurrent, awaited
        if normal:
            normal_results = await asyncio.gather(
                *[
                    self._run_listener(
                        listener=lst,
                        event_name=event_name,
                        payload=payload,
                        metrics=metrics,
                        logger=logger,
                        tier="NORMAL",
                    )
                    for lst in normal
                ],
                return_exceptions=False,
            )
            results.extend(normal_results)

        # LOW: fire-and-forget, tracked tasks
        if low:
            loop = asyncio.get_running_loop()
            for listener in low:
                task = loop.create_task(
                    self._run_listener(
                        listener=listener,
                        event_name=event_name,
                        payload=payload,
                        metrics=metrics,
                        logger=logger,
                        tier="LOW",
                    ),
                    name=f"eventbus-low-{event_name}-{listener.identifier}",
                )
                self._background_tasks.add(task)
                # Auto-remove from set when task completes
                task.add_done_callback(self._background_tasks.discard)

        return results

    async def _run_with_timeout(
        self,
        *,
        listener: EventListener,
        event_name: str,
        payload: EventPayload,
        metrics: Optional[EventMetricsRecorder],
        logger: Logger,
        tier: str,
        timeout: Optional[float],
    ) -> Any:
        """
        Run a listener with optional timeout protection.

        Parameters
        ----------
        listener:
            The listener to execute.
        event_name:
            Name of the event being published.
        payload:
            Event payload dictionary.
        metrics:
            Optional metrics recorder.
        logger:
            Logger instance.
        tier:
            Priority tier name for logging (e.g., "CRITICAL", "HIGH").
        timeout:
            Timeout in seconds. None or <= 0 means no timeout.

        Returns
        -------
        Any:
            Result from the listener, or None if timeout or error occurred.
        """
        # No timeout protection if timeout is None or non-positive
        if timeout is None or timeout <= 0:
            return await self._run_listener(
                listener=listener,
                event_name=event_name,
                payload=payload,
                metrics=metrics,
                logger=logger,
                tier=tier,
            )

        # Execute with timeout
        try:
            return await asyncio.wait_for(
                self._run_listener(
                    listener=listener,
                    event_name=event_name,
                    payload=payload,
                    metrics=metrics,
                    logger=logger,
                    tier=tier,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            # Log timeout as an error
            logger.error(
                "EventBus listener timeout",
                extra={
                    "event_name": event_name,
                    "listener_id": listener.identifier,
                    "priority": listener.priority.name,
                    "tier": tier,
                    "timeout_seconds": timeout,
                },
            )

            # Update metrics
            handle_listener_error(
                logger=logger,
                event_name=event_name,
                listener=listener,
                exc=exc,
                metrics=metrics,
            )

            return None

    async def _run_listener(
        self,
        *,
        listener: EventListener,
        event_name: str,
        payload: EventPayload,
        metrics: Optional[EventMetricsRecorder],
        logger: Logger,
        tier: str,
    ) -> Any:
        """
        Run a single listener with error isolation.

        Async callbacks are executed directly. Sync callbacks are executed
        in the default thread pool executor to avoid blocking the event loop.

        Parameters
        ----------
        listener:
            The listener to execute.
        event_name:
            Name of the event being published.
        payload:
            Event payload dictionary.
        metrics:
            Optional metrics recorder.
        logger:
            Logger instance.
        tier:
            Priority tier name for logging (e.g., "CRITICAL", "HIGH", "NORMAL", "LOW").

        Returns
        -------
        Any:
            Result from the listener callback, or None if an error occurred.
        """
        try:
            logger.debug(
                "EventBus: executing listener",
                extra={
                    "event_name": event_name,
                    "listener_id": listener.identifier,
                    "priority": listener.priority.name,
                    "tier": tier,
                },
            )

            # Execute async callback directly
            if asyncio.iscoroutinefunction(listener.callback):
                return await listener.callback(payload)

            # Execute sync callback in thread pool executor
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, listener.callback, payload)

        except Exception as exc:
            # Error isolation: log and record error, but don't propagate
            handle_listener_error(
                logger=logger,
                event_name=event_name,
                listener=listener,
                exc=exc,
                metrics=metrics,
            )
            return None

    def get_background_task_count(self) -> int:
        """
        Get the current number of background tasks (LOW-tier listeners).

        Returns
        -------
        int:
            Number of currently running background tasks.

        Examples
        --------
        >>> scheduler = EventScheduler()
        >>> count = scheduler.get_background_task_count()
        >>> print(f"Background tasks: {count}")
        """
        return len(self._background_tasks)
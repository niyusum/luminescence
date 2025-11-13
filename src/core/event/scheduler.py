"""
EventScheduler: tiered concurrency execution for Lumen EventBus.

Execution model (Option B)
--------------------------
- CRITICAL:
    - Sequential, ordered, awaited, with timeout protection.
- HIGH:
    - Sequential, ordered, awaited, with timeout protection.
- NORMAL:
    - Concurrent (asyncio.gather), awaited.
- LOW:
    - Fire-and-forget background tasks, tracked until completion.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Set

from src.core.event.types import EventListener, ListenerPriority, EventPayload
from src.core.event.metrics import EventMetricsRecorder
from src.core.event.errors import handle_listener_error

_background_tasks: Set[asyncio.Task] = set()


class EventScheduler:
    """Executes event listeners according to the tiered concurrency model."""

    @classmethod
    async def execute(
        cls,
        *,
        event_name: str,
        payload: EventPayload,
        listeners: List[EventListener],
        metrics: Optional[EventMetricsRecorder],
        logger,
        critical_timeout: Optional[float],
        high_timeout: Optional[float],
    ) -> List[Any]:
        """
        Execute listeners with tiered concurrency.

        Returns
        -------
        List[Any]
            Results from CRITICAL/HIGH/NORMAL listeners; LOW-tier listeners
            are fire-and-forget and not included in the results list.
        """
        critical = [l for l in listeners if l.priority == ListenerPriority.CRITICAL]
        high = [l for l in listeners if l.priority == ListenerPriority.HIGH]
        normal = [l for l in listeners if l.priority == ListenerPriority.NORMAL]
        low = [l for l in listeners if l.priority == ListenerPriority.LOW]

        results: List[Any] = []

        # CRITICAL: sequential with timeout
        for listener in critical:
            res = await cls._run_with_timeout(
                listener, event_name, payload, metrics, logger, "CRITICAL", critical_timeout
            )
            results.append(res)

        # HIGH: sequential with timeout
        for listener in high:
            res = await cls._run_with_timeout(
                listener, event_name, payload, metrics, logger, "HIGH", high_timeout
            )
            results.append(res)

        # NORMAL: concurrent, awaited
        if normal:
            normal_results = await asyncio.gather(
                *[
                    cls._run_listener(listener, event_name, payload, metrics, logger, "NORMAL")
                    for listener in normal
                ],
                return_exceptions=False,
            )
            results.extend(normal_results)

        # LOW: fire-and-forget, tracked tasks
        loop = asyncio.get_running_loop()
        for listener in low:
            task = loop.create_task(
                cls._run_listener(listener, event_name, payload, metrics, logger, "LOW"),
                name=f"eventbus-low-{event_name}-{listener.identifier}",
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        return results

    @staticmethod
    async def _run_with_timeout(
        listener: EventListener,
        event_name: str,
        payload: EventPayload,
        metrics: Optional[EventMetricsRecorder],
        logger,
        tier: str,
        timeout: Optional[float],
    ) -> Any:
        """Run a listener with optional timeout."""
        if timeout is None or timeout <= 0:
            return await EventScheduler._run_listener(listener, event_name, payload, metrics, logger, tier)

        try:
            return await asyncio.wait_for(
                EventScheduler._run_listener(listener, event_name, payload, metrics, logger, tier),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            handle_listener_error(
                logger=logger,
                event_name=event_name,
                listener=listener,
                exc=exc,
                metrics=metrics,
            )
            return None

    @staticmethod
    async def _run_listener(
        listener: EventListener,
        event_name: str,
        payload: EventPayload,
        metrics: Optional[EventMetricsRecorder],
        logger,
        tier: str,
    ) -> Any:
        """
        Run a single listener with error isolation.

        Sync callbacks are executed in the default executor.
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

            if asyncio.iscoroutinefunction(listener.callback):
                return await listener.callback(payload)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, listener.callback, payload)

        except Exception as exc:
            handle_listener_error(
                logger=logger,
                event_name=event_name,
                listener=listener,
                exc=exc,
                metrics=metrics,
            )
            return None

"""
Async pub/sub event bus for RIKI RPG Bot.

RIKI LAW Compliance:
- Event-driven architecture for decoupling (Article VIII)
- Error isolation - one failing listener doesn't affect others (Article IX)
- Audit logging with event context (Article II)
- Priority-based execution for critical listeners

Production Features:
- Priority-based listener execution (CRITICAL > HIGH > NORMAL > LOW)
- Error isolation - exceptions caught and logged, don't stop other listeners
- Comprehensive metrics tracking (events published, errors by type, listener count)
- One-time listeners (automatically unsubscribe after first execution)
- Duplicate prevention (optional - prevents same callback registered twice)
- Wildcard event patterns (e.g., "player.*" matches all player events)
- Sync callback support (runs in executor to avoid blocking)
- LogContext integration for full audit trail

Architecture:
- Class-based singleton pattern (all methods are classmethods)
- Priority queue execution (listeners sorted by priority)
- Sequential execution within priority level (predictable order)
- Graceful degradation (listener errors don't crash event bus)

Usage:
    # Subscribe to events
    EventBus.subscribe("maiden_fused", handle_fusion, priority=ListenerPriority.HIGH)
    EventBus.subscribe("player.*", handle_all_player_events)  # Wildcard
    
    # Publish events
    await EventBus.publish("maiden_fused", {
        "player_id": 123,
        "tier": 5,
        "result": "success"
    })
    
    # One-time listeners
    EventBus.subscribe("tutorial_complete", show_celebration, once=True)
    
    # Metrics
    stats = EventBus.get_metrics_summary()
    # {"total_events_published": 1234, "error_rate": 0.5, ...}
"""

from typing import Callable, Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import traceback
from collections import defaultdict

from src.core.logger import get_logger, set_log_context

logger = get_logger(__name__)


class ListenerPriority(Enum):
    """Priority levels for event listeners."""
    CRITICAL = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100


@dataclass
class EventListener:
    """Represents a registered event listener."""
    callback: Callable[[Dict[str, Any]], Any]
    priority: ListenerPriority
    identifier: str
    once: bool = False


@dataclass
class EventMetrics:
    """Metrics for event bus operations."""
    events_published: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    listener_errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_listeners: int = 0
    
    def record_publish(self, event_name: str):
        self.events_published[event_name] += 1
    
    def record_error(self, event_name: str):
        self.listener_errors[event_name] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get formatted metrics summary."""
        return {
            "total_events_published": sum(self.events_published.values()),
            "events_by_type": dict(self.events_published),
            "total_errors": sum(self.listener_errors.values()),
            "errors_by_event": dict(self.listener_errors),
            "total_listeners": self.total_listeners,
            "error_rate": (
                sum(self.listener_errors.values()) / max(1, sum(self.events_published.values())) * 100
            )
        }


class EventBus:
    """
    Simple async pub/sub event bus for in-game events.
    
    ENHANCED: LogContext integration for audit trail compliance (RIKI LAW Article II)
    
    Features:
    - Priority-based listener execution
    - Error isolation (one failing listener doesn't affect others)
    - Comprehensive logging and metrics
    - One-time listeners
    - Duplicate prevention
    - Graceful error handling
    - Wildcard event patterns
    - Sync callback support (runs in executor)
    - Audit trail with event context in all logs
    
    Usage:
        EventBus.subscribe("player.level_up", handle_level_up)
        await EventBus.publish("player.level_up", {"player_id": 123})
    """
    
    _listeners: Dict[str, List[EventListener]] = {}
    _wildcard_listeners: List[tuple[str, EventListener]] = []
    _metrics: Optional[EventMetrics] = None
    _enable_metrics: bool = True
    _lock: Optional[asyncio.Lock] = None
    
    @classmethod
    def _ensure_initialized(cls):
        """Lazy initialization of class-level resources."""
        if cls._metrics is None and cls._enable_metrics:
            cls._metrics = EventMetrics()
        if cls._lock is None:
            cls._lock = asyncio.Lock()
    
    @classmethod
    def subscribe(
        cls,
        event_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        priority: ListenerPriority = ListenerPriority.NORMAL,
        identifier: Optional[str] = None,
        once: bool = False,
        allow_duplicates: bool = False
    ) -> str:
        """
        Subscribe a callback to an event.
        
        Args:
            event_name: Event to subscribe to (supports wildcards with '*')
            callback: Async or sync function to call when event fires
            priority: Execution priority (lower values execute first)
            identifier: Unique identifier for this listener (auto-generated if None)
            once: If True, automatically unsubscribe after first execution
            allow_duplicates: If False, prevents registering same callback twice
        
        Returns:
            Listener identifier for later unsubscription
        """
        cls._ensure_initialized()
        
        if identifier is None:
            identifier = f"{callback.__module__}.{callback.__qualname__}"
        
        listener = EventListener(
            callback=callback,
            priority=priority,
            identifier=identifier,
            once=once
        )
        
        # Check for duplicates if not allowed
        if not allow_duplicates:
            existing = cls._listeners.get(event_name, [])
            if any(l.identifier == listener.identifier for l in existing):
                logger.warning(
                    f"Duplicate listener prevented: {listener.identifier} for event {event_name}"
                )
                return listener.identifier
        
        # Handle wildcard patterns
        if '*' in event_name:
            cls._wildcard_listeners.append((event_name, listener))
            cls._wildcard_listeners.sort(key=lambda x: x[1].priority.value)
        else:
            if event_name not in cls._listeners:
                cls._listeners[event_name] = []
            cls._listeners[event_name].append(listener)
            cls._listeners[event_name].sort(key=lambda l: l.priority.value)
        
        if cls._metrics:
            cls._metrics.total_listeners += 1
        
        logger.debug(
            f"Subscribed {listener.identifier} to {event_name} "
            f"with priority {priority.name}"
        )
        
        return listener.identifier
    
    @classmethod
    def unsubscribe(cls, event_name: str, identifier: str) -> bool:
        """
        Unsubscribe a listener from an event.
        
        Args:
            event_name: Event name
            identifier: Listener identifier returned from subscribe()
        
        Returns:
            True if listener was found and removed
        """
        # Check regular listeners
        if event_name in cls._listeners:
            original_count = len(cls._listeners[event_name])
            cls._listeners[event_name] = [
                l for l in cls._listeners[event_name]
                if l.identifier != identifier
            ]
            if len(cls._listeners[event_name]) < original_count:
                if cls._metrics:
                    cls._metrics.total_listeners -= 1
                logger.debug(f"Unsubscribed {identifier} from {event_name}")
                return True
        
        # Check wildcard listeners
        original_count = len(cls._wildcard_listeners)
        cls._wildcard_listeners = [
            (pattern, l) for pattern, l in cls._wildcard_listeners
            if not (pattern == event_name and l.identifier == identifier)
        ]
        if len(cls._wildcard_listeners) < original_count:
            if cls._metrics:
                cls._metrics.total_listeners -= 1
            logger.debug(f"Unsubscribed {identifier} from wildcard {event_name}")
            return True
        
        return False
    
    @classmethod
    def clear(cls):
        """Remove all listeners from all events."""
        cls._listeners.clear()
        cls._wildcard_listeners.clear()
        if cls._metrics:
            cls._metrics.total_listeners = 0
        logger.info("EventBus cleared - all listeners removed")
    
    @classmethod
    async def publish(cls, event_name: str, data: Dict[str, Any]) -> List[Any]:
        """
        Publish an event to all subscribed listeners.
        
        ENHANCED: Sets event context in logs for audit trail.
        
        Args:
            event_name: Event to publish
            data: Event payload
        
        Returns:
            List of return values from listeners
        """
        cls._ensure_initialized()
        
        # Set event context for logging - RIKI LAW Article II
        set_log_context(event_name=event_name, event_data_keys=list(data.keys()))
        
        if cls._metrics:
            cls._metrics.record_publish(event_name)
        
        logger.debug(f"Publishing event: {event_name} with data keys: {list(data.keys())}")
        
        # Collect all applicable listeners
        listeners_to_execute: List[EventListener] = []
        
        # Direct listeners
        listeners_to_execute.extend(cls._listeners.get(event_name, []))
        
        # Wildcard listeners
        for pattern, listener in cls._wildcard_listeners:
            if cls._matches_wildcard(event_name, pattern):
                listeners_to_execute.append(listener)
        
        # Sort by priority
        listeners_to_execute.sort(key=lambda l: l.priority.value)
        
        if not listeners_to_execute:
            logger.debug(f"No listeners for event: {event_name}")
            return []
        
        logger.debug(
            f"Executing {len(listeners_to_execute)} listener(s) for {event_name}"
        )
        
        # Execute listeners
        return await cls._execute_listeners(event_name, data, listeners_to_execute)
    
    @classmethod
    async def _execute_listeners(
        cls,
        event_name: str,
        data: Dict[str, Any],
        listeners: List[EventListener]
    ) -> List[Any]:
        """Execute listeners sequentially with error isolation."""
        results = []
        listeners_to_remove = []
        
        for listener in listeners:
            try:
                logger.debug(
                    f"Executing listener {listener.identifier} for {event_name} "
                    f"(priority: {listener.priority.name})"
                )
                
                # Execute callback
                if asyncio.iscoroutinefunction(listener.callback):
                    result = await listener.callback(data)
                else:
                    # Run sync callbacks in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, listener.callback, data)
                
                results.append(result)
                
                # Mark for removal if once=True
                if listener.once:
                    listeners_to_remove.append(listener)
                    logger.debug(f"One-time listener {listener.identifier} will be removed")
                
            except Exception as e:
                if cls._metrics:
                    cls._metrics.record_error(event_name)
                
                logger.error(
                    f"Error in listener {listener.identifier} for event {event_name}: {e}\n"
                    f"{traceback.format_exc()}",
                    extra={
                        "event_name": event_name,
                        "listener_id": listener.identifier,
                        "error_type": type(e).__name__
                    }
                )
                results.append(None)
        
        # Remove one-time listeners
        for listener in listeners_to_remove:
            cls.unsubscribe(event_name, listener.identifier)
        
        return results
    
    @classmethod
    def _matches_wildcard(cls, event_name: str, pattern: str) -> bool:
        """Check if event name matches wildcard pattern."""
        if pattern == '*':
            return True
        
        if '*' not in pattern:
            return event_name == pattern
        
        # Simple wildcard matching
        parts = pattern.split('*')
        if not event_name.startswith(parts[0]):
            return False
        if not event_name.endswith(parts[-1]):
            return False
        
        return True
    
    @classmethod
    def get_metrics(cls) -> Optional[EventMetrics]:
        """Get event bus metrics."""
        return cls._metrics
    
    @classmethod
    def get_metrics_summary(cls) -> Dict[str, Any]:
        """
        Get formatted metrics summary.
        
        Returns:
            Dictionary with all metrics, or empty dict if metrics disabled
        """
        if cls._metrics:
            return cls._metrics.get_summary()
        return {}
    
    @classmethod
    def get_listener_count(cls, event_name: Optional[str] = None) -> int:
        """
        Get count of registered listeners.
        
        Args:
            event_name: If provided, count for specific event. Otherwise total count.
        """
        if event_name:
            count = len(cls._listeners.get(event_name, []))
            count += sum(
                1 for pattern, _ in cls._wildcard_listeners
                if cls._matches_wildcard(event_name, pattern)
            )
            return count
        else:
            return cls._metrics.total_listeners if cls._metrics else 0
    
    @classmethod
    def get_all_events(cls) -> List[str]:
        """
        Get list of all event names with registered listeners.
        
        Returns:
            List of event names
        """
        events = list(cls._listeners.keys())
        events.extend([pattern for pattern, _ in cls._wildcard_listeners])
        return sorted(set(events))
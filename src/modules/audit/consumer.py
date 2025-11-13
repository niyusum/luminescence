"""
Audit Event Consumer for Lumen (2025)

Purpose
-------
Subscribe to TransactionLogger events and persist them to the audit log
database with batch processing for performance.

This consumer is the **write path** for the audit system. It listens to
the canonical "audit.transaction.logged" event emitted by TransactionLogger
and persists those events to the AuditLog database table.

Consumes
--------
Primary event:
- "audit.transaction.logged" (from TransactionLogger)
    Payload shape:
    {
        "timestamp": ISO8601 string,
        "player_id": int,
        "transaction_type": str,  # e.g., "fusion_attempt", "resource_change_lumees"
        "details": dict,          # transaction-specific data
        "context": str,           # e.g., "/fuse", "background_task"
        "meta": dict,             # optional metadata (guild_id, shard_id, etc.)
    }

Optional domain events (if you want to capture non-TransactionLogger events):
- "fusion.completed"
- "summon.executed"
- "health.degraded"
- etc.

Responsibilities
----------------
- Subscribe to TransactionLogger's audit event
- Transform events into AuditLog database entries
- Batch write to database for performance
- Handle transient failures with retry
- Monitor consumer health and backlog
- Track metrics (events received, persisted, dropped)

Non-Responsibilities
--------------------
- No business logic
- No event routing (handled by EventBus)
- No querying (handled by service.py)
- No validation (TransactionLogger already validates)

Lumen 2025 Compliance
---------------------
- Strict layering: event consumer only
- Transaction discipline: batch atomic writes
- Observability: structured logging for processing
- Event-driven: subscribes via EventBus
- Graceful degradation: buffering on DB failure

Configuration Keys
------------------
- audit.consumer.batch_size           : int (default 100)
- audit.consumer.flush_interval_seconds: int (default 5)
- audit.consumer.max_buffer_size      : int (default 10000)
- audit.consumer.retry_attempts       : int (default 3)

Architecture Notes
------------------
- Uses in-memory buffer for batching
- Flushes on interval or buffer size threshold
- Automatically retries on transient DB failures
- Drops events if buffer overflows (logs warning)
- Runs as background asyncio task
- Maps TransactionLogger payload to AuditLog schema
- EventBus callback signature: single argument (payload dict)

Example Usage
-------------
>>> consumer = AuditConsumer(event_bus, audit_repo)
>>> await consumer.start()
>>> # TransactionLogger events are now being persisted
>>> status = consumer.get_status()
>>> await consumer.stop()
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.core.logging.logger import get_logger
from src.core.config.config_manager import ConfigManager
from src.modules.audit.model import AuditLog

if TYPE_CHECKING:
    from src.core.event.bus import EventBus
    from src.modules.audit.repository import AuditRepository

logger = get_logger(__name__)


class AuditConsumer:
    """
    Event consumer that persists TransactionLogger events to audit database.
    
    Subscribes to EventBus and batches audit log writes for
    high-performance event persistence.
    """
    
    # TransactionLogger's canonical event name
    TRANSACTION_LOGGER_EVENT = "audit.transaction.logged"
    
    def __init__(
        self,
        event_bus: EventBus,
        audit_repository: AuditRepository,
    ) -> None:
        """
        Initialize audit consumer.
        
        Parameters
        ----------
        event_bus : EventBus
            The event bus to subscribe to
        audit_repository : AuditRepository
            The repository for persisting audit logs
        """
        self._event_bus = event_bus
        self._audit_repo = audit_repository
        
        # Buffer for batching
        self._buffer: deque = deque()
        self._buffer_lock: asyncio.Lock = asyncio.Lock()
        
        # Background task
        self._is_running: bool = False
        self._flush_task: Optional[asyncio.Task] = None
        
        # Configuration
        self._batch_size = self._get_config_int("audit.consumer.batch_size", 100)
        self._flush_interval = self._get_config_int("audit.consumer.flush_interval_seconds", 5)
        self._max_buffer_size = self._get_config_int("audit.consumer.max_buffer_size", 10000)
        self._retry_attempts = self._get_config_int("audit.consumer.retry_attempts", 3)
        
        # Metrics
        self._events_received: int = 0
        self._events_persisted: int = 0
        self._events_dropped: int = 0
        self._flush_count: int = 0
        self._last_flush_time: Optional[float] = None
        
        logger.info(
            "AuditConsumer initialized",
            extra={
                "batch_size": self._batch_size,
                "flush_interval_seconds": self._flush_interval,
                "max_buffer_size": self._max_buffer_size,
                "retry_attempts": self._retry_attempts,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def start(self) -> None:
        """Start the audit consumer and subscribe to events."""
        if self._is_running:
            logger.warning("AuditConsumer already running")
            return
        
        self._is_running = True
        
        # Subscribe to TransactionLogger's canonical event
        await self._subscribe_to_events()
        
        # Start background flush task
        self._flush_task = asyncio.create_task(self._flush_loop())
        
        logger.info("AuditConsumer started")
    
    async def stop(self) -> None:
        """Stop the audit consumer and flush remaining events."""
        if not self._is_running:
            return
        
        self._is_running = False
        
        # Stop background task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        
        # Flush remaining events
        await self._flush_buffer()
        
        logger.info(
            "AuditConsumer stopped",
            extra={
                "events_received": self._events_received,
                "events_persisted": self._events_persisted,
                "events_dropped": self._events_dropped,
                "flush_count": self._flush_count,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # EVENT SUBSCRIPTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _subscribe_to_events(self) -> None:
        """Subscribe to TransactionLogger audit events."""
        # Primary subscription: TransactionLogger's canonical event
        # EventBus callback signature: single argument (payload dict)
        self._event_bus.subscribe(
            self.TRANSACTION_LOGGER_EVENT,
            self._handle_transaction_audit,
        )
        
        logger.info(
            "Subscribed to TransactionLogger audit events",
            extra={"event_name": self.TRANSACTION_LOGGER_EVENT},
        )
        
        # Optional: Subscribe to additional domain events if you want
        # to capture events that don't go through TransactionLogger
        # Uncomment if needed:
        #
        # additional_events = [
        #     "fusion.completed",
        #     "summon.executed",
        #     "health.degraded",
        #     "system.startup",
        #     "system.shutdown",
        # ]
        # 
        # for event_type in additional_events:
        #     self._event_bus.subscribe(event_type, self._handle_domain_event)
        # 
        # logger.info(
        #     "Subscribed to additional domain events",
        #     extra={"event_types": additional_events},
        # )
    
    # ═══════════════════════════════════════════════════════════════════════
    # EVENT HANDLING — TRANSACTION LOGGER EVENTS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _handle_transaction_audit(self, payload: Dict[str, Any]) -> None:
        """
        Handle audit events from TransactionLogger.
        
        EventBus callback signature: single argument (payload dict)
        
        Expected payload shape (from TransactionLogger):
        {
            "timestamp": "2025-01-01T12:00:00.123456",
            "player_id": 123456789,
            "transaction_type": "fusion_attempt",
            "details": {
                "success": true,
                "input_tier": 3,
                "result_tier": 4,
                "cost": 2500,
                ...
            },
            "context": "/fuse",
            "meta": {
                "guild_id": 987654321,
                "channel_id": 111222333,
                "shard_id": 0,
                ...
            }
        }
        
        Parameters
        ----------
        payload : Dict[str, Any]
            TransactionLogger event payload
        """
        self._events_received += 1
        
        # Event type is known (we subscribed to specific event)
        event_type = self.TRANSACTION_LOGGER_EVENT
        
        try:
            # Extract fields from TransactionLogger payload
            player_id = payload.get("player_id")
            transaction_type = payload.get("transaction_type", "UNKNOWN")
            details = payload.get("details", {})
            context_str = payload.get("context", "unknown")
            meta = payload.get("meta", {})
            
            # Extract optional IDs from meta
            guild_id = meta.get("guild_id")
            channel_id = meta.get("channel_id")
            
            # Determine success (check both top-level and details)
            success = details.get("success", True)
            if "outcome" in details:
                success = details["outcome"] == "success"
            
            # Extract error information if present
            error_type = details.get("error_type")
            error_message = details.get("error_message")
            
            # Extract duration if present
            duration_ms = details.get("duration_ms")
            
            # Categorize the transaction type
            category = self._categorize_transaction_type(transaction_type)
            
            # Create audit log entry
            audit_entry = AuditLog(
                user_id=player_id,
                guild_id=guild_id,
                channel_id=channel_id,
                category=category,
                operation_type=transaction_type.upper(),
                operation_name=transaction_type,
                event_data=details,
                metadata={
                    "context": context_str,
                    "source": "TransactionLogger",
                    "original_event_type": event_type,
                    **meta,
                },
                success=success,
                error_type=error_type,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            
            # Add to buffer
            async with self._buffer_lock:
                if len(self._buffer) >= self._max_buffer_size:
                    # Buffer overflow, drop oldest event
                    dropped = self._buffer.popleft()
                    self._events_dropped += 1
                    
                    logger.warning(
                        "Audit buffer overflow, dropping oldest event",
                        extra={
                            "buffer_size": len(self._buffer),
                            "max_buffer_size": self._max_buffer_size,
                            "events_dropped": self._events_dropped,
                            "dropped_transaction_type": dropped.operation_type,
                        },
                    )
                
                self._buffer.append(audit_entry)
                
                logger.debug(
                    "Audit event buffered",
                    extra={
                        "transaction_type": transaction_type,
                        "player_id": player_id,
                        "buffer_size": len(self._buffer),
                        "success": success,
                    },
                )
                
                # Flush if batch size reached
                if len(self._buffer) >= self._batch_size:
                    logger.debug(
                        "Batch size reached, triggering flush",
                        extra={"buffer_size": len(self._buffer)},
                    )
                    asyncio.create_task(self._flush_buffer())
        
        except Exception as exc:
            logger.error(
                "Failed to handle transaction audit event",
                extra={
                    "event_type": event_type,
                    "player_id": payload.get("player_id"),
                    "transaction_type": payload.get("transaction_type"),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
    
    # ═══════════════════════════════════════════════════════════════════════
    # EVENT HANDLING — OPTIONAL DOMAIN EVENTS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _handle_domain_event(self, payload: Dict[str, Any]) -> None:
        """
        Handle domain events that don't come through TransactionLogger.
        
        This is optional and can be used to capture events that are emitted
        directly by domain services without going through TransactionLogger.
        
        EventBus callback signature: single argument (payload dict)
        
        Parameters
        ----------
        payload : Dict[str, Any]
            Event payload (structure varies by event)
        """
        self._events_received += 1
        
        # Try to extract event type from payload metadata
        event_type = payload.get("meta", {}).get("event_type", "UNKNOWN")
        
        try:
            # Extract common fields
            user_id = payload.get("user_id") or payload.get("player_id")
            guild_id = payload.get("guild_id")
            success = payload.get("success", True)
            error = payload.get("error")
            duration_ms = payload.get("duration_ms")
            
            # Parse event type into category and operation
            if "." in event_type:
                parts = event_type.split(".", 1)
                operation_type = parts[0].upper()
                category = self._categorize_operation_type(operation_type)
            else:
                operation_type = "UNKNOWN"
                category = "OTHER"
            
            # Create audit log entry
            audit_entry = AuditLog(
                user_id=user_id,
                guild_id=guild_id,
                category=category,
                operation_type=operation_type,
                operation_name=event_type,
                event_data=payload,
                metadata={
                    "source": "DomainEvent",
                    "original_event_type": event_type,
                },
                success=success,
                error_type=type(error).__name__ if error else None,
                error_message=str(error) if error else None,
                duration_ms=duration_ms,
            )
            
            # Add to buffer
            async with self._buffer_lock:
                if len(self._buffer) >= self._max_buffer_size:
                    self._buffer.popleft()
                    self._events_dropped += 1
                    logger.warning("Audit buffer overflow, dropping oldest event")
                
                self._buffer.append(audit_entry)
                
                # Flush if batch size reached
                if len(self._buffer) >= self._batch_size:
                    asyncio.create_task(self._flush_buffer())
        
        except Exception as exc:
            logger.error(
                "Failed to handle domain audit event",
                extra={
                    "event_type": event_type,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
    
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORIZATION
    # ═══════════════════════════════════════════════════════════════════════
    
    @staticmethod
    def _categorize_transaction_type(transaction_type: str) -> str:
        """
        Map TransactionLogger transaction_type to audit category.
        
        Categories:
        - TRANSACTION: Game state changes (fusion, summon, resource, maiden)
        - COMMAND: User interactions (commands, buttons, modals)
        - SYSTEM: System events (health, startup, shutdown)
        - SECURITY: Security events (rate limits, bans, permissions)
        - OTHER: Everything else
        
        Parameters
        ----------
        transaction_type : str
            Transaction type from TransactionLogger
            (e.g., "fusion_attempt", "resource_change_lumees")
            
        Returns
        -------
        str
            Category name
        """
        transaction_type_lower = transaction_type.lower()
        
        # Transaction category
        if any(keyword in transaction_type_lower for keyword in [
            "fusion", "summon", "resource", "maiden", "transfer",
            "purchase", "sell", "craft", "upgrade", "reward",
        ]):
            return "TRANSACTION"
        
        # Command category
        if any(keyword in transaction_type_lower for keyword in [
            "command", "button", "modal", "select", "interaction",
        ]):
            return "COMMAND"
        
        # System category
        if any(keyword in transaction_type_lower for keyword in [
            "system", "health", "startup", "shutdown", "migration",
            "cleanup", "backup", "restore",
        ]):
            return "SYSTEM"
        
        # Security category
        if any(keyword in transaction_type_lower for keyword in [
            "auth", "permission", "ban", "kick", "mute",
            "security", "abuse", "rate_limit",
        ]):
            return "SECURITY"
        
        return "OTHER"
    
    @staticmethod
    def _categorize_operation_type(operation_type: str) -> str:
        """
        Categorize operation type for domain events.
        
        Parameters
        ----------
        operation_type : str
            Operation type from domain event
            
        Returns
        -------
        str
            Category name
        """
        operation_type_upper = operation_type.upper()
        
        transaction_types = {
            "FUSION", "SUMMON", "TRANSFER", "PURCHASE", "SELL",
            "CRAFT", "UPGRADE", "CONSUME", "REWARD", "MAIDEN", "RESOURCE",
        }
        command_types = {
            "COMMAND", "BUTTON", "MODAL", "SELECT", "INTERACTION",
        }
        system_types = {
            "SYSTEM", "HEALTH", "STARTUP", "SHUTDOWN", "MIGRATION",
            "CLEANUP", "BACKUP", "RESTORE",
        }
        security_types = {
            "AUTH", "PERMISSION", "BAN", "KICK", "MUTE",
            "SECURITY", "ABUSE", "RATE_LIMIT",
        }
        
        if operation_type_upper in transaction_types:
            return "TRANSACTION"
        elif operation_type_upper in command_types:
            return "COMMAND"
        elif operation_type_upper in system_types:
            return "SYSTEM"
        elif operation_type_upper in security_types:
            return "SECURITY"
        else:
            return "OTHER"
    
    # ═══════════════════════════════════════════════════════════════════════
    # BUFFER FLUSHING
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _flush_loop(self) -> None:
        """Background task that flushes buffer periodically."""
        logger.debug("Audit flush loop started")
        
        while self._is_running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_buffer()
                
            except asyncio.CancelledError:
                logger.debug("Audit flush loop cancelled")
                break
                
            except Exception as exc:
                logger.error(
                    "Error in audit flush loop",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                # Continue loop despite errors
    
    async def _flush_buffer(self) -> None:
        """Flush buffered audit entries to database."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            
            # Extract entries from buffer
            entries = list(self._buffer)
            self._buffer.clear()
        
        # Persist with retry
        for attempt in range(1, self._retry_attempts + 1):
            try:
                start_time = time.monotonic()
                
                count = await self._audit_repo.create_batch(entries)
                
                latency_ms = (time.monotonic() - start_time) * 1000
                
                self._events_persisted += count
                self._flush_count += 1
                self._last_flush_time = time.time()
                
                logger.info(
                    "Audit buffer flushed to database",
                    extra={
                        "count": count,
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 2),
                        "throughput_per_sec": round(count / (latency_ms / 1000), 2) if latency_ms > 0 else 0,
                        "buffer_remaining": len(self._buffer),
                        "total_persisted": self._events_persisted,
                    },
                )
                
                return  # Success
                
            except Exception as exc:
                logger.error(
                    "Failed to flush audit buffer",
                    extra={
                        "count": len(entries),
                        "attempt": attempt,
                        "max_attempts": self._retry_attempts,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                
                if attempt >= self._retry_attempts:
                    # All retries exhausted, drop events
                    self._events_dropped += len(entries)
                    logger.critical(
                        "Dropped audit events after all retry attempts",
                        extra={
                            "count": len(entries),
                            "total_dropped": self._events_dropped,
                        },
                    )
                    return
                
                # Wait before retry (exponential backoff)
                backoff_seconds = 2 ** attempt
                logger.info(
                    "Retrying audit flush after backoff",
                    extra={
                        "attempt": attempt,
                        "backoff_seconds": backoff_seconds,
                    },
                )
                await asyncio.sleep(backoff_seconds)
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATUS & METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get consumer status and metrics.
        
        Returns
        -------
        Dict[str, Any]
            Status information including metrics and buffer state
        """
        success_rate = (
            (self._events_persisted / self._events_received * 100)
            if self._events_received > 0
            else 0.0
        )
        
        drop_rate = (
            (self._events_dropped / self._events_received * 100)
            if self._events_received > 0
            else 0.0
        )
        
        return {
            "is_running": self._is_running,
            "buffer_size": len(self._buffer),
            "max_buffer_size": self._max_buffer_size,
            "batch_size": self._batch_size,
            "flush_interval_seconds": self._flush_interval,
            "events_received": self._events_received,
            "events_persisted": self._events_persisted,
            "events_dropped": self._events_dropped,
            "flush_count": self._flush_count,
            "last_flush_time": self._last_flush_time,
            "success_rate_pct": round(success_rate, 2),
            "drop_rate_pct": round(drop_rate, 2),
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════
    
    @staticmethod
    def _get_config_int(key: str, default: int) -> int:
        """Get integer config value with fallback."""
        try:
            val = ConfigManager.get(key)
            if isinstance(val, int):
                return val
        except Exception:
            pass
        return default
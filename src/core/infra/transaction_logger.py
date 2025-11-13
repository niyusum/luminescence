"""
Event-driven audit logging for all game transactions (Lumen 2025).

Purpose
-------
This module provides a **pure event producer** for structured audit logging.
Instead of writing directly to the database, it emits normalized audit events
onto the Lumen EventBus. A separate audit consumer service is responsible for
persisting these events to the database or any external sink.

Responsibilities
----------------
- Accept rich transaction context from domain services:
  - player_id / actor identifiers
  - transaction type (fusion_attempt, resource_change_lumees, etc.)
  - structured details payload
  - optional logical context (command name, subsystem, etc.)
- Validate audit payloads via TransactionValidator.
- Normalize payloads into a canonical audit event shape.
- Publish events to the EventBus topic:
    "audit.transaction.logged"
- Track local in-memory metrics for observability.

Non-Responsibilities
--------------------
- Database access or persistence.
- Querying audit history or analytics.
- Retention/cleanup of old audit data.

LUMEN LAW Compliance
--------------------
- Article II: Complete, structured audit trail for all state changes.
- Article VIII: Event-driven, decoupled architecture (no direct DB coupling).
- Article IX: Graceful error handling (validation errors explicit, others logged).
- Article X: Metrics for event production (counts, error rates, timings).

Design Decisions
----------------
- **Event-driven**: This module only publishes audit events; it never touches
  the database. Persistence belongs to a dedicated audit consumer service that
  subscribes to "audit.transaction.logged".
- **Canonical payloads**: All helpers (resource, maiden, fusion, etc.) are thin
  wrappers that shape domain data into a single canonical audit schema.
- **Validation-first**: TransactionValidator is used before publishing to ensure
  schema consistency, with explicit ValidationError for the caller.
- **Instance EventBus**: Uses the global `event_bus` instance from
  `src/core/event/event_bus.py`, which implements tiered concurrency and
  structured logging with LogContext.

Dependencies
------------
- src.core.logging.logger.get_logger
- src.core.validation.TransactionValidator
- src.core.exceptions.ValidationError
- src.core.event.event_bus.event_bus
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
import asyncio
import time

from src.core.logging.logger import get_logger
from src.core.validation import TransactionValidator
from src.core.exceptions import ValidationError
from src.core.event import event_bus, EventPayload

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


@dataclass
class TransactionLoggerMetrics:
    """In-memory metrics for transaction audit event production."""
    events_emitted: int = 0
    batch_events_emitted: int = 0
    validation_errors: int = 0
    publish_errors: int = 0
    total_log_time_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        total_events = max(self.events_emitted + self.batch_events_emitted, 1)
        error_events = self.validation_errors + self.publish_errors
        avg_time_ms = self.total_log_time_ms / total_events
        error_rate = (error_events / total_events) * 100.0

        return {
            "events_emitted": self.events_emitted,
            "batch_events_emitted": self.batch_events_emitted,
            "validation_errors": self.validation_errors,
            "publish_errors": self.publish_errors,
            "total_events": total_events,
            "error_rate": round(error_rate, 2),
            "avg_log_time_ms": round(avg_time_ms, 2),
        }


# Single metrics instance for this process
_metrics = TransactionLoggerMetrics()


# --------------------------------------------------------------------------- #
# TransactionLogger (Event Producer)
# --------------------------------------------------------------------------- #


class TransactionLogger:
    """
    Event-driven audit logger for all game transactions.

    This logger is **write-only**: it shapes and publishes audit events to the
    EventBus, but does not perform any persistence itself.

    Event name:
        "audit.transaction.logged"

    Canonical payload shape (EventPayload):
        {
            "timestamp": ISO8601 UTC string,
            "player_id": int,
            "transaction_type": str,
            "details": dict,
            "context": str,
            "meta": dict,           # optional additional metadata
        }

    Usage Examples
    --------------
        # Generic transaction
        await TransactionLogger.log_transaction(
            player_id=123,
            transaction_type="fusion_attempt",
            details={"success": True, "input_tier": 3, "result_tier": 4},
            context="/fuse",
        )

        # Resource change helper
        await TransactionLogger.log_resource_change(
            player_id=123,
            resource_type="lumees",
            old_value=10_000,
            new_value=7_500,
            reason="fusion_cost",
            context="/fuse",
        )

        # Maiden change helper
        await TransactionLogger.log_maiden_change(
            player_id=123,
            action="fused",
            maiden_id=42,
            maiden_name="Aurelia",
            tier=4,
            quantity_change=-2,
            context="/fuse",
        )
    """

    EVENT_NAME: str = "audit.transaction.logged"

    # ------------------------------------------------------------------ #
    # Core API
    # ------------------------------------------------------------------ #

    @classmethod
    async def log_transaction(
        cls,
        *,
        player_id: int,
        transaction_type: str,
        details: Mapping[str, Any],
        context: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        validate: bool = True,
    ) -> None:
        """
        Publish a canonical audit transaction event.

        Parameters
        ----------
        player_id:
            Discord ID of the player associated with this transaction.
        transaction_type:
            Logical type of transaction (e.g., "fusion_attempt",
            "resource_change_lumees", "maiden_fused", etc.).
        details:
            Structured transaction data (deltas, identifiers, flags, etc.).
        context:
            Optional logical origin/context (command name, subsystem, etc.).
        meta:
            Optional additional metadata (e.g., shard_id, guild_id, trace_id).
        validate:
            If True (default), validate the payload via TransactionValidator
            before publishing.
        """
        start_time = time.perf_counter()

        try:
            # Validation / normalization
            if validate:
                sanitized_details = TransactionValidator.validate_transaction(
                    transaction_type=transaction_type,
                    details=dict(details),
                    allow_unknown_types=True,
                )
                validated_context: str = TransactionValidator.validate_context(context)
            else:
                sanitized_details = dict(details)
                validated_context = context or "unknown"

            payload: EventPayload = {
                "timestamp": datetime.utcnow().isoformat(),
                "player_id": int(player_id),
                "transaction_type": transaction_type,
                "details": sanitized_details,
                "context": validated_context,
                "meta": dict(meta) if meta is not None else {},
            }

            # Emit onto EventBus (audit consumer will persist)
            await event_bus.publish(cls.EVENT_NAME, payload)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            _metrics.events_emitted += 1
            _metrics.total_log_time_ms += elapsed_ms

            logger.info(
                "AUDIT: transaction event emitted",
                extra={
                    "event_name": cls.EVENT_NAME,
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "context": validated_context,
                    "log_time_ms": round(elapsed_ms, 2),
                },
            )

        except ValidationError as exc:
            _metrics.validation_errors += 1
            logger.error(
                "Audit transaction validation failed",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "validation_error": str(exc),
                },
            )
            # Caller must decide whether to fail the operation or continue.
            raise

        except Exception as exc:
            _metrics.publish_errors += 1
            logger.error(
                "Failed to emit audit transaction event",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "context": context,
                },
                exc_info=True,
            )
            # Do not re-raise by default: audit logging should not bring down
            # the core gameplay flow unless explicitly required.

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #

    @classmethod
    async def log_resource_change(
        cls,
        *,
        player_id: int,
        resource_type: str,
        old_value: int,
        new_value: int,
        reason: str,
        context: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        validate: bool = True,
    ) -> None:
        """
        Convenience wrapper for resource change audit events.

        Emits transaction_type:
            "resource_change_<resource_type>"

        Example:
            resource_type = "lumees" -> "resource_change_lumees"
        """
        delta = new_value - old_value

        details: Dict[str, Any] = {
            "resource": resource_type,
            "old_value": old_value,
            "new_value": new_value,
            "delta": delta,
            "reason": reason,
        }

        await cls.log_transaction(
            player_id=player_id,
            transaction_type=f"resource_change_{resource_type}",
            details=details,
            context=context,
            meta=meta,
            validate=validate,
        )

    @classmethod
    async def log_maiden_change(
        cls,
        *,
        player_id: int,
        action: str,
        maiden_id: int,
        maiden_name: str,
        tier: int,
        quantity_change: int,
        context: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        validate: bool = True,
    ) -> None:
        """
        Convenience wrapper for maiden-related audit events.

        Emits transaction_type:
            "maiden_<action>"  (e.g., "maiden_acquired", "maiden_fused")
        """
        details: Dict[str, Any] = {
            "maiden_id": maiden_id,
            "maiden_name": maiden_name,
            "tier": tier,
            "quantity_change": quantity_change,
            "action": action,
        }

        await cls.log_transaction(
            player_id=player_id,
            transaction_type=f"maiden_{action}",
            details=details,
            context=context,
            meta=meta,
            validate=validate,
        )

    @classmethod
    async def log_fusion_attempt(
        cls,
        *,
        player_id: int,
        success: bool,
        tier: int,
        cost: int,
        result_tier: Optional[int] = None,
        context: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        validate: bool = True,
    ) -> None:
        """
        Convenience wrapper for fusion attempt audit events.

        Emits transaction_type:
            "fusion_attempt"
        """
        details: Dict[str, Any] = {
            "success": success,
            "input_tier": tier,
            "result_tier": result_tier,
            "cost": cost,
            "outcome": "success" if success else "failure",
        }

        await cls.log_transaction(
            player_id=player_id,
            transaction_type="fusion_attempt",
            details=details,
            context=context,
            meta=meta,
            validate=validate,
        )

    # ------------------------------------------------------------------ #
    # Batch API
    # ------------------------------------------------------------------ #

    @classmethod
    async def batch_log(
        cls,
        transactions: List[Dict[str, Any]],
        *,
        validate: bool = True,
    ) -> int:
        """
        Emit multiple audit events efficiently in a batch.

        Each item in `transactions` must contain:
            - player_id: int
            - transaction_type: str
            - details: Mapping[str, Any]
            - context: Optional[str]
            - meta: Optional[Mapping[str, Any]]

        Returns
        -------
        int
            Number of events successfully emitted (i.e., not skipped due to
            validation error).
        """
        start_time = time.perf_counter()
        emitted_count = 0

        async def _emit_single(txn: Dict[str, Any]) -> None:
            nonlocal emitted_count
            try:
                await cls.log_transaction(
                    player_id=txn["player_id"],
                    transaction_type=txn["transaction_type"],
                    details=txn.get("details", {}),
                    context=txn.get("context"),
                    meta=txn.get("meta"),
                    validate=validate,
                )
                emitted_count += 1
            except ValidationError as exc:
                # Skip invalid transaction but continue with others
                logger.warning(
                    "Skipping invalid audit transaction in batch",
                    extra={
                        "player_id": txn.get("player_id"),
                        "transaction_type": txn.get("transaction_type"),
                        "validation_error": str(exc),
                    },
                )

        await asyncio.gather(*[_emit_single(txn) for txn in transactions])

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        _metrics.batch_events_emitted += emitted_count
        _metrics.total_log_time_ms += elapsed_ms

        logger.info(
            "AUDIT: batch transaction events emitted",
            extra={
                "batch_size": len(transactions),
                "emitted": emitted_count,
                "log_time_ms": round(elapsed_ms, 2),
            },
        )

        return emitted_count

    # ------------------------------------------------------------------ #
    # Metrics API
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get current TransactionLogger metrics snapshot.

        Returns
        -------
        Dict[str, Any]
            Counts, error rates, average timings.
        """
        return _metrics.as_dict()

    @staticmethod
    def reset_metrics() -> None:
        """Reset all TransactionLogger metrics counters."""
        global _metrics
        _metrics = TransactionLoggerMetrics()
        logger.info("TransactionLogger metrics reset")


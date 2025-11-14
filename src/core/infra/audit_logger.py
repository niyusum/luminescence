"""
Audit Trail Logger for Lumen (2025)

Purpose
-------
Focused audit trail logging for all game state changes and transactions.
Emits structured audit events to the EventBus for decoupled persistence.

This module is **purely** about audit trail production - it shapes and validates
audit events, then publishes them to the event bus. No database writes, no event
sourcing logic, no bootstrapping.

Responsibilities
----------------
- Accept transaction context (player, type, details, context)
- Validate audit payloads via TransactionValidator
- Normalize into canonical audit event shape
- Publish to EventBus: "audit.transaction.logged"
- Track local audit metrics (counts, errors, timings)

Non-Responsibilities
--------------------
- Database persistence (handled by audit consumer)
- Event sourcing (separate concern if needed)
- Audit history queries (separate concern)
- Bootstrap/initialization logic
- Business logic of any kind

LUMEN LAW Compliance
--------------------
- Article II: Complete, structured audit trail for all state changes
- Article VIII: Event-driven, decoupled architecture
- Article IX: Graceful error handling (validation explicit, publish non-blocking)
- Article X: Metrics for audit production (counts, error rates, timings)

Canonical Event Shape
---------------------
Event name: "audit.transaction.logged"

Payload (EventPayload):
    {
        "timestamp": ISO8601 UTC string,
        "player_id": int,
        "transaction_type": str,  # e.g., "fusion_attempt", "resource_change_lumees"
        "details": dict,           # structured transaction data
        "context": str,            # command/subsystem origin
        "meta": dict,              # optional metadata (guild_id, trace_id, etc.)
    }

Usage Examples
--------------
# Generic transaction
await AuditLogger.log(
    player_id=123,
    transaction_type="fusion_attempt",
    details={"success": True, "input_tier": 3, "result_tier": 4},
    context="/fuse",
)

# Resource change
await AuditLogger.log_resource_change(
    player_id=123,
    resource_type="lumees",
    old_value=10_000,
    new_value=7_500,
    reason="fusion_cost",
    context="/fuse",
)

# Maiden change
await AuditLogger.log_maiden_change(
    player_id=123,
    action="fused",
    maiden_id=42,
    maiden_name="Aurelia",
    tier=4,
    quantity_change=-2,
    context="/fuse",
)

Architecture Notes
------------------
- Pure event producer: publishes to EventBus, never touches database
- Validation-first: TransactionValidator ensures schema consistency
- Non-blocking: audit failures logged but don't crash gameplay
- Metrics-tracked: comprehensive observability for audit production
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from src.core.event import EventPayload, event_bus
from src.core.exceptions import ValidationError
from src.core.logging.logger import get_logger
from src.core.validation import TransactionValidator

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT METRICS
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class AuditMetrics:
    """In-memory metrics for audit event production."""

    events_emitted: int = 0
    batch_events_emitted: int = 0
    validation_errors: int = 0
    publish_errors: int = 0
    total_log_time_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        """Get metrics as dictionary for monitoring."""
        total_events = max(self.events_emitted + self.batch_events_emitted, 1)
        error_events = self.validation_errors + self.publish_errors
        avg_time_ms = self.total_log_time_ms / total_events
        error_rate = (error_events / total_events) * 100.0

        return {
            "events_emitted": self.events_emitted,
            "batch_events_emitted": self.batch_events_emitted,
            "total_events": total_events,
            "validation_errors": self.validation_errors,
            "publish_errors": self.publish_errors,
            "error_rate": round(error_rate, 2),
            "avg_log_time_ms": round(avg_time_ms, 2),
        }


# Global metrics instance
_metrics = AuditMetrics()


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT LOGGER
# ═════════════════════════════════════════════════════════════════════════════


class AuditLogger:
    """
    Audit trail logger for all game transactions.

    This logger is **write-only**: it shapes and publishes audit events to the
    EventBus, but performs no persistence itself. A separate audit consumer
    service subscribes to "audit.transaction.logged" and handles persistence.

    All audit events flow through this class to ensure:
    - Consistent event shape
    - Validation before emission
    - Comprehensive metrics tracking
    - Structured logging
    """

    EVENT_NAME: str = "audit.transaction.logged"

    # ═════════════════════════════════════════════════════════════════════════
    # CORE API
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    async def log(
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
        player_id : int
            Discord ID of the player associated with this transaction
        transaction_type : str
            Logical type of transaction (e.g., "fusion_attempt",
            "resource_change_lumees", "maiden_fused")
        details : Mapping[str, Any]
            Structured transaction data (deltas, identifiers, flags, etc.)
        context : Optional[str]
            Logical origin/context (command name, subsystem, etc.)
        meta : Optional[Mapping[str, Any]]
            Additional metadata (shard_id, guild_id, trace_id, etc.)
        validate : bool
            If True (default), validate payload before publishing

        Raises
        ------
        ValidationError
            If validate=True and payload fails validation
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

            # Build canonical payload
            payload: EventPayload = {
                "timestamp": datetime.utcnow().isoformat(),
                "player_id": int(player_id),
                "transaction_type": transaction_type,
                "details": sanitized_details,
                "context": validated_context,
                "meta": dict(meta) if meta is not None else {},
            }

            # Emit to EventBus (audit consumer will persist)
            await event_bus.publish(cls.EVENT_NAME, payload)

            # Track metrics
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
            # Re-raise: caller must decide whether to fail operation or continue
            raise

        except Exception as exc:
            _metrics.publish_errors += 1
            logger.error(
                "Failed to emit audit transaction event",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "context": context,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            # Do NOT re-raise: audit logging should not bring down gameplay flow

    # ═════════════════════════════════════════════════════════════════════════
    # CONVENIENCE HELPERS
    # ═════════════════════════════════════════════════════════════════════════

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

        Emits transaction_type: "resource_change_<resource_type>"
        Example: resource_type="lumees" -> "resource_change_lumees"

        Parameters
        ----------
        player_id : int
            Player's Discord ID
        resource_type : str
            Type of resource (lumees, auric_coin, energy, etc.)
        old_value : int
            Previous resource value
        new_value : int
            New resource value
        reason : str
            Reason for change (fusion_cost, daily_reward, etc.)
        context : Optional[str]
            Command or subsystem context
        meta : Optional[Mapping[str, Any]]
            Additional metadata
        validate : bool
            Whether to validate before emitting
        """
        delta = new_value - old_value

        details: Dict[str, Any] = {
            "resource": resource_type,
            "old_value": old_value,
            "new_value": new_value,
            "delta": delta,
            "reason": reason,
        }

        await cls.log(
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

        Emits transaction_type: "maiden_<action>"
        Example: action="fused" -> "maiden_fused"

        Parameters
        ----------
        player_id : int
            Player's Discord ID
        action : str
            Action performed (acquired, fused, upgraded, etc.)
        maiden_id : int
            Maiden base ID
        maiden_name : str
            Maiden display name
        tier : int
            Maiden tier
        quantity_change : int
            Change in quantity (positive for gain, negative for loss)
        context : Optional[str]
            Command or subsystem context
        meta : Optional[Mapping[str, Any]]
            Additional metadata
        validate : bool
            Whether to validate before emitting
        """
        details: Dict[str, Any] = {
            "maiden_id": maiden_id,
            "maiden_name": maiden_name,
            "tier": tier,
            "quantity_change": quantity_change,
            "action": action,
        }

        await cls.log(
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

        Emits transaction_type: "fusion_attempt"

        Parameters
        ----------
        player_id : int
            Player's Discord ID
        success : bool
            Whether fusion succeeded
        tier : int
            Input maiden tier
        cost : int
            Lumees cost for fusion
        result_tier : Optional[int]
            Resulting maiden tier (if successful)
        context : Optional[str]
            Command or subsystem context
        meta : Optional[Mapping[str, Any]]
            Additional metadata
        validate : bool
            Whether to validate before emitting
        """
        details: Dict[str, Any] = {
            "success": success,
            "input_tier": tier,
            "result_tier": result_tier,
            "cost": cost,
            "outcome": "success" if success else "failure",
        }

        await cls.log(
            player_id=player_id,
            transaction_type="fusion_attempt",
            details=details,
            context=context,
            meta=meta,
            validate=validate,
        )

    # ═════════════════════════════════════════════════════════════════════════
    # BATCH API
    # ═════════════════════════════════════════════════════════════════════════

    @classmethod
    async def batch_log(
        cls,
        transactions: List[Dict[str, Any]],
        *,
        validate: bool = True,
    ) -> int:
        """
        Emit multiple audit events efficiently in a batch.

        Each transaction dict must contain:
        - player_id: int
        - transaction_type: str
        - details: Mapping[str, Any]
        - context: Optional[str]
        - meta: Optional[Mapping[str, Any]]

        Parameters
        ----------
        transactions : List[Dict[str, Any]]
            List of transaction dictionaries
        validate : bool
            Whether to validate each transaction

        Returns
        -------
        int
            Number of events successfully emitted (excludes validation failures)
        """
        start_time = time.perf_counter()
        emitted_count = 0

        async def _emit_single(txn: Dict[str, Any]) -> None:
            nonlocal emitted_count
            try:
                await cls.log(
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

    # ═════════════════════════════════════════════════════════════════════════
    # METRICS API
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get current audit metrics snapshot.

        Returns
        -------
        Dict[str, Any]
            Metrics including counts, error rates, average timings
        """
        return _metrics.as_dict()

    @staticmethod
    def reset_metrics() -> None:
        """Reset all audit metrics counters."""
        global _metrics
        _metrics = AuditMetrics()
        logger.info("AuditLogger metrics reset")

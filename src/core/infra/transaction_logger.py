"""
TransactionLogger - Backward Compatibility Alias (Lumen 2025).

Purpose
-------
This module provides a backward-compatible alias to AuditLogger for existing
code that imports TransactionLogger. This ensures zero breaking changes while
consolidating the implementation.

DEPRECATION NOTICE
------------------
This module is maintained for backward compatibility only. New code should use
AuditLogger directly from src.core.infra.audit_logger.

The TransactionLogger and AuditLogger implementations were identical duplicates.
They have been consolidated into a single implementation (AuditLogger) with this
compatibility shim to prevent breaking existing code.

Migration Path
--------------
Old code (still works):
    from src.core.infra.transaction_logger import TransactionLogger
    await TransactionLogger.log_transaction(...)

Recommended new code:
    from src.core.infra.audit_logger import AuditLogger
    await AuditLogger.log(...)

API Mapping
-----------
TransactionLogger.log_transaction() → AuditLogger.log()
TransactionLogger.log_resource_change() → AuditLogger.log_resource_change()
TransactionLogger.log_maiden_change() → AuditLogger.log_maiden_change()
TransactionLogger.log_fusion_attempt() → AuditLogger.log_fusion_attempt()
TransactionLogger.batch_log() → AuditLogger.batch_log()
TransactionLogger.get_metrics() → AuditLogger.get_metrics()
TransactionLogger.reset_metrics() → AuditLogger.reset_metrics()

Architecture Notes
------------------
This is a pure compatibility shim. All functionality is implemented in
AuditLogger. This file exists solely to prevent import errors in existing
code (e.g., ConfigManager, services, etc.).

Once all code has been migrated to use AuditLogger directly, this file can
be safely removed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# Import the actual implementation
from src.core.infra.audit_logger import AuditLogger, AuditMetrics

# Re-export metrics for backward compatibility
__all__ = ["TransactionLogger", "TransactionLoggerMetrics"]

# Alias for metrics (backward compatibility)
TransactionLoggerMetrics = AuditMetrics


class TransactionLogger:
    """
    Backward-compatible alias to AuditLogger.
    
    DEPRECATED: Use AuditLogger directly.
    
    This class provides the same API as the old TransactionLogger but delegates
    all calls to the consolidated AuditLogger implementation.
    """

    EVENT_NAME: str = AuditLogger.EVENT_NAME

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
        
        DEPRECATED: Use AuditLogger.log() instead.
        
        This method delegates to AuditLogger.log() for backward compatibility.
        """
        await AuditLogger.log(
            player_id=player_id,
            transaction_type=transaction_type,
            details=details,
            context=context,
            meta=meta,
            validate=validate,
        )

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
        
        Delegates to AuditLogger.log_resource_change().
        """
        await AuditLogger.log_resource_change(
            player_id=player_id,
            resource_type=resource_type,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
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
        
        Delegates to AuditLogger.log_maiden_change().
        """
        await AuditLogger.log_maiden_change(
            player_id=player_id,
            action=action,
            maiden_id=maiden_id,
            maiden_name=maiden_name,
            tier=tier,
            quantity_change=quantity_change,
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
        
        Delegates to AuditLogger.log_fusion_attempt().
        """
        await AuditLogger.log_fusion_attempt(
            player_id=player_id,
            success=success,
            tier=tier,
            cost=cost,
            result_tier=result_tier,
            context=context,
            meta=meta,
            validate=validate,
        )

    @classmethod
    async def batch_log(
        cls,
        transactions: List[Dict[str, Any]],
        *,
        validate: bool = True,
    ) -> int:
        """
        Emit multiple audit events efficiently in a batch.
        
        Delegates to AuditLogger.batch_log().
        """
        return await AuditLogger.batch_log(transactions, validate=validate)

    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get current audit metrics snapshot.
        
        Delegates to AuditLogger.get_metrics().
        """
        return AuditLogger.get_metrics()

    @staticmethod
    def reset_metrics() -> None:
        """
        Reset all audit metrics counters.
        
        Delegates to AuditLogger.reset_metrics().
        """
        AuditLogger.reset_metrics()
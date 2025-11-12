"""
Centralized audit logging for all game transactions.

Features:
- Database-backed audit trails for all state changes
- Batch logging for efficiency
- Transaction history queries
- Automatic log retention management
- Performance metrics tracking
- Structured logging with context propagation

LUMEN LAW Compliance:
- Complete audit trails for all state changes (Article II)
- Discord context in all transaction logs (Article II)
- Graceful error handling (Article IX)
- Performance metrics and monitoring (Article X)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
import time

from src.database.models.economy.transaction_log import TransactionLog
from src.core.logging.logger import get_logger
from src.core.validation import TransactionValidator
from src.core.exceptions import ValidationError

logger = get_logger(__name__)


class TransactionLogger:
    """
    Centralized audit logging for all game transactions (LUMEN LAW Article II).
    
    Records every significant player action for debugging, support tickets,
    anti-cheat, and compliance. All logs stored in database for long-term retention.
    
    Transaction Types:
        - resource_change_* (lumees, auric coin, energy, etc.)
        - maiden_* (acquired, fused, consumed)
        - fusion_attempt
        - summon_attempt
        - drop_performed
        - level_up
        - quest_completed
    """
    
    # Metrics tracking
    _metrics = {
        "transactions_logged": 0,
        "log_errors": 0,
        "batch_logs": 0,
        "total_log_time_ms": 0.0,
    }
    
    @staticmethod
    async def log_transaction(
        session: AsyncSession,
        player_id: int,
        transaction_type: str,
        details: Dict[str, Any],
        context: Optional[str] = None,
        validate: bool = True
    ) -> None:
        """
        Log a transaction to the database with validation.

        Args:
            session: Database session (must be part of active transaction)
            player_id: Discord ID of the player
            transaction_type: Type of transaction (fusion_attempt, resource_change, etc.)
            details: Structured data about the transaction
            context: Where the transaction originated (command name, event, etc.)
            validate: If True, validate transaction before logging (default True)

        Raises:
            ValidationError: If validation fails (only if validate=True)
        """
        start_time = time.perf_counter()

        try:
            # SEC-07: Validate transaction data before logging
            if validate:
                sanitized_details = TransactionValidator.validate_transaction(
                    transaction_type=transaction_type,
                    details=details,
                    allow_unknown_types=True  # Allow schema evolution
                )
                validated_context = TransactionValidator.validate_context(context)
            else:
                sanitized_details = details
                validated_context = context or "unknown"

            log_entry = TransactionLog(
                player_id=player_id,
                transaction_type=transaction_type,
                details=sanitized_details,
                context=validated_context,
                timestamp=datetime.utcnow()
            )

            session.add(log_entry)

            TransactionLogger._metrics["transactions_logged"] += 1

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionLogger._metrics["total_log_time_ms"] += elapsed_ms

            logger.info(
                f"TRANSACTION: player={player_id} type={transaction_type}",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "details": sanitized_details,
                    "context": validated_context,
                    "log_time_ms": round(elapsed_ms, 2)
                }
            )

        except ValidationError as e:
            # Validation failed - re-raise to caller
            TransactionLogger._metrics["log_errors"] += 1
            logger.error(
                f"Transaction validation failed: player={player_id} type={transaction_type} error={e}",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "validation_error": str(e)
                }
            )
            raise

        except Exception as e:
            TransactionLogger._metrics["log_errors"] += 1
            logger.error(
                f"Failed to log transaction: player={player_id} type={transaction_type} error={e}",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "details": details
                },
                exc_info=True
            )
    
    @staticmethod
    async def log_resource_change(
        session: AsyncSession,
        player_id: int,
        resource_type: str,
        old_value: int,
        new_value: int,
        reason: str,
        context: Optional[str] = None
    ) -> None:
        """
        Log a resource change (lumees, auric coin, energy, stamina, etc.).
        
        Args:
            session: Database session
            player_id: Discord ID
            resource_type: Type of resource (lumees, auric coin, energy, etc.)
            old_value: Value before change
            new_value: Value after change
            reason: Why the change occurred
            context: Command/event that triggered the change
        """
        delta = new_value - old_value
        
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type=f"resource_change_{resource_type}",
            details={
                "resource": resource_type,
                "old_value": old_value,
                "new_value": new_value,
                "delta": delta,
                "reason": reason
            },
            context=context
        )
    
    @staticmethod
    async def log_maiden_change(
        session: AsyncSession,
        player_id: int,
        action: str,
        maiden_id: int,
        maiden_name: str,
        tier: int,
        quantity_change: int,
        context: Optional[str] = None
    ) -> None:
        """
        Log maiden acquisition, fusion, or consumption.
        
        Args:
            session: Database session
            player_id: Discord ID
            action: Action type (acquired, fused, consumed)
            maiden_id: Database ID of the maiden
            maiden_name: Name of the maiden
            tier: Current tier
            quantity_change: Change in quantity (positive = gained, negative = lost)
            context: Command/event that triggered the change
        """
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type=f"maiden_{action}",
            details={
                "maiden_id": maiden_id,
                "maiden_name": maiden_name,
                "tier": tier,
                "quantity_change": quantity_change,
                "action": action
            },
            context=context
        )
    
    @staticmethod
    async def log_fusion_attempt(
        session: AsyncSession,
        player_id: int,
        success: bool,
        tier: int,
        cost: int,
        result_tier: Optional[int] = None,
        context: Optional[str] = None
    ) -> None:
        """
        Log fusion attempt with outcome.
        
        Args:
            session: Database session
            player_id: Discord ID
            success: Whether fusion succeeded
            tier: Input maiden tier
            cost: Lumees cost
            result_tier: Output maiden tier (if successful)
            context: Command that triggered fusion
        """
        await TransactionLogger.log_transaction(
            session=session,
            player_id=player_id,
            transaction_type="fusion_attempt",
            details={
                "success": success,
                "input_tier": tier,
                "result_tier": result_tier,
                "cost": cost,
                "outcome": "success" if success else "failure"
            },
            context=context
        )
    
    @staticmethod
    async def batch_log(
        session: AsyncSession,
        transactions: List[Dict[str, Any]],
        validate: bool = True
    ) -> int:
        """
        Log multiple transactions efficiently in a batch with validation.

        More efficient than individual log_transaction calls when logging
        many transactions at once.

        Args:
            session: Database session
            transactions: List of transaction dicts with keys:
                - player_id: Discord ID
                - transaction_type: Type of transaction
                - details: Transaction details dict
                - context: Optional context string
            validate: If True, validate each transaction before logging (default True)

        Returns:
            Number of transactions successfully logged

        Example:
            >>> await TransactionLogger.batch_log(session, [
            ...     {
            ...         "player_id": 123,
            ...         "transaction_type": "resource_change_lumees",
            ...         "details": {"delta": 100},
            ...         "context": "daily_reward"
            ...     },
            ...     {
            ...         "player_id": 456,
            ...         "transaction_type": "resource_change_lumees",
            ...         "details": {"delta": 100},
            ...         "context": "daily_reward"
            ...     }
            ... ])
        """
        start_time = time.perf_counter()

        try:
            log_entries = []
            for txn in transactions:
                # SEC-07: Validate each transaction in batch
                if validate:
                    try:
                        sanitized_details = TransactionValidator.validate_transaction(
                            transaction_type=txn["transaction_type"],
                            details=txn["details"],
                            allow_unknown_types=True
                        )
                        validated_context = TransactionValidator.validate_context(
                            txn.get("context")
                        )
                    except ValidationError as e:
                        # Log validation error but continue with other transactions
                        logger.warning(
                            f"Skipping invalid transaction in batch: "
                            f"player={txn.get('player_id')} type={txn.get('transaction_type')} error={e}"
                        )
                        continue
                else:
                    sanitized_details = txn["details"]
                    validated_context = txn.get("context", "unknown")

                log_entry = TransactionLog(
                    player_id=txn["player_id"],
                    transaction_type=txn["transaction_type"],
                    details=sanitized_details,
                    context=validated_context,
                    timestamp=datetime.utcnow()
                )
                log_entries.append(log_entry)
            
            session.add_all(log_entries)
            
            TransactionLogger._metrics["transactions_logged"] += len(log_entries)
            TransactionLogger._metrics["batch_logs"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionLogger._metrics["total_log_time_ms"] += elapsed_ms
            
            logger.info(
                f"BATCH TRANSACTION: count={len(log_entries)} time={elapsed_ms:.2f}ms",
                extra={
                    "batch_size": len(log_entries),
                    "log_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return len(log_entries)
            
        except Exception as e:
            TransactionLogger._metrics["log_errors"] += 1
            logger.error(
                f"Failed to batch log transactions: count={len(transactions)} error={e}",
                extra={"batch_size": len(transactions)},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def flush(session: AsyncSession) -> None:
        """
        Flush pending transaction logs to database.
        
        Normally not needed as logs are added to session during transaction.
        """
        try:
            await session.flush()
            logger.debug("Transaction logs flushed to database")
        except Exception as e:
            logger.error(f"Failed to flush transaction logs: {e}", exc_info=True)
            raise
    
    # =========================================================================
    # QUERY METHODS
    # =========================================================================
    
    @staticmethod
    async def get_player_history(
        session: AsyncSession,
        player_id: int,
        transaction_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TransactionLog]:
        """
        Get transaction history for a player.
        
        Args:
            session: Database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
            limit: Maximum number of records to return
            offset: Number of records to skip (for pagination)
        
        Returns:
            List of TransactionLog entries (newest first)
        
        Example:
            >>> # Get last 50 fusion attempts for player
            >>> history = await TransactionLogger.get_player_history(
            ...     session,
            ...     player_id=123,
            ...     transaction_type="fusion_attempt",
            ...     limit=50
            ... )
        """
        try:
            stmt = select(TransactionLog).where(TransactionLog.player_id == player_id)
            
            if transaction_type:
                stmt = stmt.where(TransactionLog.transaction_type == transaction_type)
            
            stmt = stmt.order_by(TransactionLog.timestamp.desc()).limit(limit).offset(offset)
            
            result = await session.execute(stmt)
            return list(result.scalars().all())
            
        except Exception as e:
            logger.error(
                f"Failed to get player history: player={player_id} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return []
    
    @staticmethod
    async def get_player_stats(
        session: AsyncSession,
        player_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get transaction statistics for a player.
        
        Args:
            session: Database session
            player_id: Discord ID of player
            days: Number of days to analyze (default 30)
        
        Returns:
            Dictionary with transaction counts by type
        
        Example:
            >>> stats = await TransactionLogger.get_player_stats(session, 123)
            >>> # {"fusion_attempt": 50, "summon_attempt": 100, ...}
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            stmt = (
                select(
                    TransactionLog.transaction_type,
                    func.count(TransactionLog.id).label("count")
                )
                .where(TransactionLog.player_id == player_id)
                .where(TransactionLog.timestamp >= cutoff_date)
                .group_by(TransactionLog.transaction_type)
            )
            
            result = await session.execute(stmt)
            stats = {row.transaction_type: row.count for row in result}
            
            return stats
            
        except Exception as e:
            logger.error(
                f"Failed to get player stats: player={player_id} error={e}",
                extra={"player_id": player_id, "days": days},
                exc_info=True
            )
            return {}
    
    # =========================================================================
    # MAINTENANCE
    # =========================================================================
    
    @staticmethod
    async def cleanup_old_logs(cutoff_days: int = 90) -> int:
        """
        Delete transaction logs older than specified days.
        
        Automatically manages its own database transaction.
        Safe to call standalone (used by SystemTasksCog daily cleanup task).
        
        Args:
            cutoff_days: Delete logs older than this many days (default 90)
        
        Returns:
            Number of logs deleted
        """
        from src.core.infra.database_service import DatabaseService
        
        cutoff_date = datetime.utcnow() - timedelta(days=cutoff_days)
        
        try:
            async with DatabaseService.get_transaction() as session:
                stmt = delete(TransactionLog).where(TransactionLog.timestamp < cutoff_date)
                result = await session.execute(stmt)
                deleted_count = result.rowcount
                
                logger.info(
                    f"Cleaned up transaction logs: deleted={deleted_count} older_than={cutoff_days}d",
                    extra={
                        "deleted_count": deleted_count,
                        "cutoff_days": cutoff_days,
                        "cutoff_date": cutoff_date
                    }
                )
                
                return deleted_count
                
        except Exception as e:
            logger.error(
                f"Failed to cleanup old logs: cutoff_days={cutoff_days} error={e}",
                extra={"cutoff_days": cutoff_days},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_log_count(session: AsyncSession, days: Optional[int] = None) -> int:
        """
        Get total count of transaction logs.
        
        Args:
            session: Database session
            days: Optional filter for last N days
        
        Returns:
            Total number of transaction logs
        """
        try:
            stmt = select(func.count(TransactionLog.id))
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(TransactionLog.timestamp >= cutoff_date)
            
            result = await session.execute(stmt)
            return result.scalar() or 0
            
        except Exception as e:
            logger.error(
                f"Failed to get log count: days={days} error={e}",
                exc_info=True
            )
            return 0
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get transaction logging metrics.
        
        Returns:
            Dictionary with transaction counts, errors, timing
        
        Example:
            >>> metrics = TransactionLogger.get_metrics()
            >>> print(f"Logged: {metrics['transactions_logged']}")
            >>> print(f"Avg time: {metrics['avg_log_time_ms']:.2f}ms")
        """
        avg_log_time = (
            TransactionLogger._metrics["total_log_time_ms"] / 
            max(TransactionLogger._metrics["transactions_logged"], 1)
        )
        
        error_rate = (
            (TransactionLogger._metrics["log_errors"] / 
             max(TransactionLogger._metrics["transactions_logged"] + 
                 TransactionLogger._metrics["log_errors"], 1)) * 100
        )
        
        return {
            "transactions_logged": TransactionLogger._metrics["transactions_logged"],
            "log_errors": TransactionLogger._metrics["log_errors"],
            "batch_logs": TransactionLogger._metrics["batch_logs"],
            "error_rate": round(error_rate, 2),
            "avg_log_time_ms": round(avg_log_time, 2),
        }
    
    @staticmethod
    def reset_metrics() -> None:
        """Reset all metrics counters."""
        TransactionLogger._metrics = {
            "transactions_logged": 0,
            "log_errors": 0,
            "batch_logs": 0,
            "total_log_time_ms": 0.0,
        }
        logger.info("TransactionLogger metrics reset")
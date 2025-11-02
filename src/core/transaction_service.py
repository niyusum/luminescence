"""
Service for logging player transactions and resource changes.

Features:
- Database-backed rikis transaction tracking
- Batch transaction logging for efficiency
- Comprehensive query methods (history, analytics, aggregates)
- Automatic cleanup of old transactions
- Performance metrics tracking
- Structured logging with context

RIKI LAW Compliance:
- Complete audit trails for resource changes (Article II)
- Graceful error handling (Article IX)
- Performance metrics and monitoring (Article X)
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlmodel import Field, SQLModel, Column, BigInteger, select
from sqlalchemy import Index, func, delete
import json
import time

from src.core.logger import get_logger

logger = get_logger(__name__)


class Transaction(SQLModel, table=True):
    """
    Audit log for all resource changes and player actions.
    
    Tracks every rikis change, summon, fusion, and other significant
    player actions for debugging, analytics, and potential rollbacks.
    
    Attributes:
        player_id: Discord ID of player
        transaction_type: Type of action (summon, fusion, daily_claim, etc.)
        rikis_change: Amount of rikis gained/spent (negative for spending)
        timestamp: When action occurred
        details: JSON field with additional context
    
    Indexes:
        - player_id (for player history queries)
        - timestamp (for time-range queries)
        - transaction_type (for analytics)
    """
    
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_player_id", "player_id"),
        Index("ix_transactions_timestamp", "timestamp"),
        Index("ix_transactions_type", "transaction_type"),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(
        sa_column=Column(BigInteger, nullable=False, index=True)
    )
    transaction_type: str = Field(max_length=50, nullable=False, index=True)
    rikis_change: int = Field(default=0, sa_column=Column(BigInteger))
    timestamp: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    details: Optional[str] = Field(default=None)


class TransactionService:
    """
    Service for logging all player transactions and resource changes.
    
    Every action that changes player resources or state should be logged
    through this service for audit trails, analytics, and debugging.
    """
    
    # Metrics tracking
    _metrics = {
        "transactions_logged": 0,
        "log_errors": 0,
        "batch_logs": 0,
        "queries_executed": 0,
        "total_log_time_ms": 0.0,
        "total_query_time_ms": 0.0,
    }
    
    @staticmethod
    async def log(
        session,
        player_id: int,
        transaction_type: str,
        rikis_change: int = 0,
        details: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Log a transaction to the database.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Type of transaction (summon, fusion, daily_claim, etc.)
            rikis_change: Amount of rikis changed (negative for spending)
            details: Additional context as dictionary (will be JSON serialized)
        
        Returns:
            Created Transaction object
        
        Example:
            >>> await TransactionService.log(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="fusion",
            ...     rikis_change=-5000,
            ...     details={
            ...         "maiden_base_id": 10,
            ...         "from_tier": 3,
            ...         "to_tier": 4,
            ...         "success": True
            ...     }
            ... )
        """
        start_time = time.perf_counter()
        
        details_json = None
        if details:
            try:
                details_json = json.dumps(details)
            except (TypeError, ValueError) as e:
                logger.error(
                    f"Failed to serialize transaction details: {e}",
                    extra={"player_id": player_id, "transaction_type": transaction_type},
                    exc_info=True
                )
                details_json = json.dumps({"error": "serialization_failed"})
        
        try:
            transaction = Transaction(
                player_id=player_id,
                transaction_type=transaction_type,
                rikis_change=rikis_change,
                details=details_json
            )
            
            session.add(transaction)
            
            TransactionService._metrics["transactions_logged"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_log_time_ms"] += elapsed_ms
            
            logger.debug(
                f"Transaction logged: type={transaction_type} player={player_id} rikis={rikis_change}",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "rikis_change": rikis_change,
                    "log_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return transaction
            
        except Exception as e:
            TransactionService._metrics["log_errors"] += 1
            logger.error(
                f"Failed to log transaction: player={player_id} type={transaction_type} error={e}",
                extra={
                    "player_id": player_id,
                    "transaction_type": transaction_type,
                    "rikis_change": rikis_change
                },
                exc_info=True
            )
            raise
    
    @staticmethod
    async def batch_log(
        session,
        transactions: List[Dict[str, Any]]
    ) -> int:
        """
        Log multiple transactions efficiently in a batch.
        
        More efficient than individual log() calls for bulk operations.
        
        Args:
            session: Active database session
            transactions: List of transaction dicts with keys:
                - player_id: Discord ID
                - transaction_type: Type of transaction
                - rikis_change: Amount of rikis changed
                - details: Optional details dict
        
        Returns:
            Number of transactions successfully logged
        
        Example:
            >>> await TransactionService.batch_log(session, [
            ...     {
            ...         "player_id": 123,
            ...         "transaction_type": "daily_claim",
            ...         "rikis_change": 100,
            ...         "details": {"streak": 5}
            ...     },
            ...     {
            ...         "player_id": 456,
            ...         "transaction_type": "daily_claim",
            ...         "rikis_change": 100,
            ...         "details": {"streak": 3}
            ...     }
            ... ])
        """
        start_time = time.perf_counter()
        
        try:
            transaction_objs = []
            
            for txn in transactions:
                details_json = None
                if txn.get("details"):
                    try:
                        details_json = json.dumps(txn["details"])
                    except (TypeError, ValueError):
                        details_json = json.dumps({"error": "serialization_failed"})
                
                transaction_obj = Transaction(
                    player_id=txn["player_id"],
                    transaction_type=txn["transaction_type"],
                    rikis_change=txn.get("rikis_change", 0),
                    details=details_json
                )
                transaction_objs.append(transaction_obj)
            
            session.add_all(transaction_objs)
            
            TransactionService._metrics["transactions_logged"] += len(transaction_objs)
            TransactionService._metrics["batch_logs"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_log_time_ms"] += elapsed_ms
            
            logger.info(
                f"Batch transactions logged: count={len(transaction_objs)} time={elapsed_ms:.2f}ms",
                extra={
                    "batch_size": len(transaction_objs),
                    "log_time_ms": round(elapsed_ms, 2)
                }
            )
            
            return len(transaction_objs)
            
        except Exception as e:
            TransactionService._metrics["log_errors"] += 1
            logger.error(
                f"Failed to batch log transactions: count={len(transactions)} error={e}",
                extra={"batch_size": len(transactions)},
                exc_info=True
            )
            return 0
    
    # =========================================================================
    # QUERY METHODS
    # =========================================================================
    
    @staticmethod
    async def get_player_history(
        session,
        player_id: int,
        limit: int = 50,
        offset: int = 0,
        transaction_type: Optional[str] = None
    ) -> List[Transaction]:
        """
        Get transaction history for a player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            limit: Maximum number of transactions to return
            offset: Number of records to skip (for pagination)
            transaction_type: Optional filter by transaction type
        
        Returns:
            List of Transaction objects, newest first
        
        Example:
            >>> history = await TransactionService.get_player_history(
            ...     session=session,
            ...     player_id=123456789,
            ...     limit=20,
            ...     transaction_type="summon"
            ... )
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(Transaction).where(Transaction.player_id == player_id)
            
            if transaction_type:
                stmt = stmt.where(Transaction.transaction_type == transaction_type)
            
            stmt = stmt.order_by(Transaction.timestamp.desc()).limit(limit).offset(offset)
            
            result = await session.exec(stmt)
            transactions = list(result.all())
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return transactions
            
        except Exception as e:
            logger.error(
                f"Failed to get player history: player={player_id} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return []
    
    @staticmethod
    async def get_total_spent(
        session,
        player_id: int,
        transaction_type: Optional[str] = None,
        days: Optional[int] = None
    ) -> int:
        """
        Calculate total rikis spent by player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
            days: Optional filter for last N days
        
        Returns:
            Total rikis spent (positive number)
        
        Example:
            >>> total = await TransactionService.get_total_spent(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="summon"
            ... )
            >>> print(f"Spent {total} rikis on summons")
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(func.sum(Transaction.rikis_change)).where(
                Transaction.player_id == player_id,
                Transaction.rikis_change < 0
            )
            
            if transaction_type:
                stmt = stmt.where(Transaction.transaction_type == transaction_type)
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(Transaction.timestamp >= cutoff_date)
            
            result = await session.exec(stmt)
            total = result.one_or_none()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return abs(total) if total else 0
            
        except Exception as e:
            logger.error(
                f"Failed to get total spent: player={player_id} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_total_earned(
        session,
        player_id: int,
        transaction_type: Optional[str] = None,
        days: Optional[int] = None
    ) -> int:
        """
        Calculate total rikis earned by player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
            days: Optional filter for last N days
        
        Returns:
            Total rikis earned
        
        Example:
            >>> total = await TransactionService.get_total_earned(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="daily_claim"
            ... )
            >>> print(f"Earned {total} rikis from dailies")
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(func.sum(Transaction.rikis_change)).where(
                Transaction.player_id == player_id,
                Transaction.rikis_change > 0
            )
            
            if transaction_type:
                stmt = stmt.where(Transaction.transaction_type == transaction_type)
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(Transaction.timestamp >= cutoff_date)
            
            result = await session.exec(stmt)
            total = result.one_or_none()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return total if total else 0
            
        except Exception as e:
            logger.error(
                f"Failed to get total earned: player={player_id} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_action_count(
        session,
        player_id: int,
        transaction_type: str,
        days: Optional[int] = None
    ) -> int:
        """
        Count how many times player performed an action.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Type of transaction to count
            days: Optional filter for last N days
        
        Returns:
            Count of transactions
        
        Example:
            >>> summon_count = await TransactionService.get_action_count(
            ...     session=session,
            ...     player_id=123456789,
            ...     transaction_type="summon"
            ... )
            >>> print(f"Summoned {summon_count} times")
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(func.count(Transaction.id)).where(
                Transaction.player_id == player_id,
                Transaction.transaction_type == transaction_type
            )
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(Transaction.timestamp >= cutoff_date)
            
            result = await session.exec(stmt)
            count = result.one()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return count
            
        except Exception as e:
            logger.error(
                f"Failed to get action count: player={player_id} type={transaction_type} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_net_change(
        session,
        player_id: int,
        transaction_type: Optional[str] = None,
        days: Optional[int] = None
    ) -> int:
        """
        Calculate net rikis change (earned - spent).
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            transaction_type: Optional filter by transaction type
            days: Optional filter for last N days
        
        Returns:
            Net rikis change (can be negative)
        
        Example:
            >>> net = await TransactionService.get_net_change(
            ...     session, player_id=123, days=7
            ... )
            >>> print(f"Net change this week: {net:+,} rikis")
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(func.sum(Transaction.rikis_change)).where(
                Transaction.player_id == player_id
            )
            
            if transaction_type:
                stmt = stmt.where(Transaction.transaction_type == transaction_type)
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(Transaction.timestamp >= cutoff_date)
            
            result = await session.exec(stmt)
            total = result.one_or_none()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return total if total else 0
            
        except Exception as e:
            logger.error(
                f"Failed to get net change: player={player_id} error={e}",
                extra={"player_id": player_id, "transaction_type": transaction_type},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_transaction_stats(
        session,
        player_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get comprehensive transaction statistics for a player.
        
        Args:
            session: Active database session
            player_id: Discord ID of player
            days: Number of days to analyze (default 30)
        
        Returns:
            Dictionary with transaction statistics by type
        
        Example:
            >>> stats = await TransactionService.get_transaction_stats(session, 123)
            >>> # {
            >>> #     "summon": {"count": 50, "rikis_spent": 5000},
            >>> #     "fusion": {"count": 30, "rikis_spent": 15000},
            >>> #     "daily_claim": {"count": 25, "rikis_earned": 2500}
            >>> # }
        """
        start_time = time.perf_counter()
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            stmt = (
                select(
                    Transaction.transaction_type,
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.rikis_change).label("total_change")
                )
                .where(Transaction.player_id == player_id)
                .where(Transaction.timestamp >= cutoff_date)
                .group_by(Transaction.transaction_type)
            )
            
            result = await session.exec(stmt)
            
            stats = {}
            for row in result:
                stats[row.transaction_type] = {
                    "count": row.count,
                    "total_change": row.total_change or 0
                }
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            TransactionService._metrics["total_query_time_ms"] += elapsed_ms
            
            return stats
            
        except Exception as e:
            logger.error(
                f"Failed to get transaction stats: player={player_id} error={e}",
                extra={"player_id": player_id, "days": days},
                exc_info=True
            )
            return {}
    
    # =========================================================================
    # MAINTENANCE
    # =========================================================================
    
    @staticmethod
    async def cleanup_old_transactions(cutoff_days: int = 90) -> int:
        """
        Delete transactions older than specified days.
        
        Automatically manages its own database transaction.
        Safe to call standalone (used by maintenance tasks).
        
        Args:
            cutoff_days: Delete transactions older than this many days (default 90)
        
        Returns:
            Number of transactions deleted
        """
        from src.core.database_service import DatabaseService
        
        cutoff_date = datetime.utcnow() - timedelta(days=cutoff_days)
        
        try:
            async with DatabaseService.get_transaction() as session:
                stmt = delete(Transaction).where(Transaction.timestamp < cutoff_date)
                result = await session.execute(stmt)
                deleted_count = result.rowcount
                
                logger.info(
                    f"Cleaned up transactions: deleted={deleted_count} older_than={cutoff_days}d",
                    extra={
                        "deleted_count": deleted_count,
                        "cutoff_days": cutoff_days,
                        "cutoff_date": cutoff_date
                    }
                )
                
                return deleted_count
                
        except Exception as e:
            logger.error(
                f"Failed to cleanup old transactions: cutoff_days={cutoff_days} error={e}",
                extra={"cutoff_days": cutoff_days},
                exc_info=True
            )
            return 0
    
    @staticmethod
    async def get_transaction_count(
        session,
        player_id: Optional[int] = None,
        days: Optional[int] = None
    ) -> int:
        """
        Get total count of transactions.
        
        Args:
            session: Active database session
            player_id: Optional filter for specific player
            days: Optional filter for last N days
        
        Returns:
            Total number of transactions
        """
        TransactionService._metrics["queries_executed"] += 1
        
        try:
            stmt = select(func.count(Transaction.id))
            
            if player_id:
                stmt = stmt.where(Transaction.player_id == player_id)
            
            if days:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                stmt = stmt.where(Transaction.timestamp >= cutoff_date)
            
            result = await session.exec(stmt)
            return result.one()
            
        except Exception as e:
            logger.error(
                f"Failed to get transaction count: player={player_id} days={days} error={e}",
                exc_info=True
            )
            return 0
    
    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """
        Get transaction service metrics.
        
        Returns:
            Dictionary with transaction counts, errors, timing
        
        Example:
            >>> metrics = TransactionService.get_metrics()
            >>> print(f"Logged: {metrics['transactions_logged']}")
            >>> print(f"Avg log time: {metrics['avg_log_time_ms']:.2f}ms")
        """
        avg_log_time = (
            TransactionService._metrics["total_log_time_ms"] / 
            max(TransactionService._metrics["transactions_logged"], 1)
        )
        
        avg_query_time = (
            TransactionService._metrics["total_query_time_ms"] / 
            max(TransactionService._metrics["queries_executed"], 1)
        )
        
        error_rate = (
            (TransactionService._metrics["log_errors"] / 
             max(TransactionService._metrics["transactions_logged"] + 
                 TransactionService._metrics["log_errors"], 1)) * 100
        )
        
        return {
            "transactions_logged": TransactionService._metrics["transactions_logged"],
            "log_errors": TransactionService._metrics["log_errors"],
            "batch_logs": TransactionService._metrics["batch_logs"],
            "queries_executed": TransactionService._metrics["queries_executed"],
            "error_rate": round(error_rate, 2),
            "avg_log_time_ms": round(avg_log_time, 2),
            "avg_query_time_ms": round(avg_query_time, 2),
        }
    
    @staticmethod
    def reset_metrics() -> None:
        """Reset all metrics counters."""
        TransactionService._metrics = {
            "transactions_logged": 0,
            "log_errors": 0,
            "batch_logs": 0,
            "queries_executed": 0,
            "total_log_time_ms": 0.0,
            "total_query_time_ms": 0.0,
        }
        logger.info("TransactionService metrics reset")
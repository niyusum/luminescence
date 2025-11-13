"""
Audit Repository for Lumen (2025)

Purpose
-------
Data access layer for audit logs with efficient batch writes,
query optimization, and retention management.

Responsibilities
----------------
- Write audit logs in batches for performance
- Provide efficient query methods for analytics
- Handle retention policies and cleanup
- Support complex filtering and aggregation
- Maintain data integrity

Non-Responsibilities
--------------------
- No business logic
- No event consumption (handled by consumer.py)
- No analytics computation (handled by service.py)

Lumen 2025 Compliance
---------------------
- Strict layering: pure data access
- Transaction discipline: atomic batch writes
- Observability: structured logging for DB operations
- Performance: batch inserts, indexed queries

Architecture Notes
------------------
- Uses batch inserts for high-throughput writes
- All queries use indexes for performance
- Supports pagination for large result sets
- Automatic retry on transient DB failures
- Structured logging for all operations
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging.logger import get_logger
from src.modules.audit.model import AuditLog

if TYPE_CHECKING:
    from src.core.database.service import DatabaseService

logger = get_logger(__name__)


class AuditRepository:
    """
    Data access layer for audit logs.
    
    Provides efficient batch writes and query methods with
    automatic indexing and retention management.
    """
    
    def __init__(self, database_service: DatabaseService) -> None:
        """
        Initialize audit repository.
        
        Parameters
        ----------
        database_service : DatabaseService
            The database service for transactions
        """
        self._db_service = database_service
        
        logger.debug("AuditRepository initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # WRITE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def create(self, audit_entry: AuditLog) -> AuditLog:
        """
        Create a single audit log entry.
        
        Parameters
        ----------
        audit_entry : AuditLog
            The audit log entry to create
            
        Returns
        -------
        AuditLog
            The created audit log with ID populated
        """
        start_time = time.monotonic()
        
        try:
            async with self._db_service.get_transaction() as session:
                session.add(audit_entry)
                await session.flush()
                await session.refresh(audit_entry)
            
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.debug(
                "Audit log entry created",
                extra={
                    "audit_id": audit_entry.id,
                    "category": audit_entry.category,
                    "operation_type": audit_entry.operation_type,
                    "latency_ms": round(latency_ms, 2),
                },
            )
            
            return audit_entry
            
        except Exception as exc:
            logger.error(
                "Failed to create audit log entry",
                extra={
                    "category": audit_entry.category,
                    "operation_type": audit_entry.operation_type,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def create_batch(self, audit_entries: List[AuditLog]) -> int:
        """
        Create multiple audit log entries in a single transaction.
        
        Parameters
        ----------
        audit_entries : List[AuditLog]
            List of audit log entries to create
            
        Returns
        -------
        int
            Number of entries created
        """
        if not audit_entries:
            return 0
        
        start_time = time.monotonic()
        
        try:
            async with self._db_service.get_transaction() as session:
                session.add_all(audit_entries)
                await session.flush()
            
            latency_ms = (time.monotonic() - start_time) * 1000
            
            logger.info(
                "Batch audit log entries created",
                extra={
                    "count": len(audit_entries),
                    "latency_ms": round(latency_ms, 2),
                    "throughput_per_sec": round(len(audit_entries) / (latency_ms / 1000), 2),
                },
            )
            
            return len(audit_entries)
            
        except Exception as exc:
            logger.error(
                "Failed to create batch audit log entries",
                extra={
                    "count": len(audit_entries),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # QUERY OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def get_by_id(self, audit_id: int) -> Optional[AuditLog]:
        """
        Get audit log entry by ID.
        
        Parameters
        ----------
        audit_id : int
            Audit log entry ID
            
        Returns
        -------
        Optional[AuditLog]
            Audit log entry if found, None otherwise
        """
        try:
            async with self._db_service.get_transaction() as session:
                result = await session.execute(
                    select(AuditLog).where(AuditLog.id == audit_id)
                )
                return result.scalar_one_or_none()
                
        except Exception as exc:
            logger.error(
                "Failed to get audit log by ID",
                extra={
                    "audit_id": audit_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def get_by_user(
        self,
        user_id: int,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None,
        success_only: bool = False,
    ) -> List[AuditLog]:
        """
        Get audit logs for a specific user.
        
        Parameters
        ----------
        user_id : int
            Discord user ID
        limit : int
            Maximum number of entries to return
        offset : int
            Number of entries to skip
        category : Optional[str]
            Filter by category
        success_only : bool
            Only return successful operations
            
        Returns
        -------
        List[AuditLog]
            List of audit log entries
        """
        try:
            async with self._db_service.get_transaction() as session:
                query = select(AuditLog).where(AuditLog.user_id == user_id)
                
                if category:
                    query = query.where(AuditLog.category == category)
                
                if success_only:
                    query = query.where(AuditLog.success == True)
                
                query = query.order_by(desc(AuditLog.created_at))
                query = query.limit(limit).offset(offset)
                
                result = await session.execute(query)
                return list(result.scalars().all())
                
        except Exception as exc:
            logger.error(
                "Failed to get audit logs by user",
                extra={
                    "user_id": user_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def get_by_guild(
        self,
        guild_id: int,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None,
    ) -> List[AuditLog]:
        """
        Get audit logs for a specific guild.
        
        Parameters
        ----------
        guild_id : int
            Discord guild ID
        limit : int
            Maximum number of entries to return
        offset : int
            Number of entries to skip
        category : Optional[str]
            Filter by category
            
        Returns
        -------
        List[AuditLog]
            List of audit log entries
        """
        try:
            async with self._db_service.get_transaction() as session:
                query = select(AuditLog).where(AuditLog.guild_id == guild_id)
                
                if category:
                    query = query.where(AuditLog.category == category)
                
                query = query.order_by(desc(AuditLog.created_at))
                query = query.limit(limit).offset(offset)
                
                result = await session.execute(query)
                return list(result.scalars().all())
                
        except Exception as exc:
            logger.error(
                "Failed to get audit logs by guild",
                extra={
                    "guild_id": guild_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def get_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        category: Optional[str] = None,
        operation_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[AuditLog]:
        """
        Get audit logs within a time range.
        
        Parameters
        ----------
        start_time : datetime
            Start of time range
        end_time : datetime
            End of time range
        category : Optional[str]
            Filter by category
        operation_type : Optional[str]
            Filter by operation type
        limit : int
            Maximum number of entries to return
            
        Returns
        -------
        List[AuditLog]
            List of audit log entries
        """
        try:
            async with self._db_service.get_transaction() as session:
                query = select(AuditLog).where(
                    and_(
                        AuditLog.created_at >= start_time,
                        AuditLog.created_at <= end_time,
                    )
                )
                
                if category:
                    query = query.where(AuditLog.category == category)
                
                if operation_type:
                    query = query.where(AuditLog.operation_type == operation_type)
                
                query = query.order_by(desc(AuditLog.created_at))
                query = query.limit(limit)
                
                result = await session.execute(query)
                return list(result.scalars().all())
                
        except Exception as exc:
            logger.error(
                "Failed to get audit logs by time range",
                extra={
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def get_recent(
        self,
        limit: int = 100,
        category: Optional[str] = None,
        success_only: bool = False,
    ) -> List[AuditLog]:
        """
        Get most recent audit logs.
        
        Parameters
        ----------
        limit : int
            Maximum number of entries to return
        category : Optional[str]
            Filter by category
        success_only : bool
            Only return successful operations
            
        Returns
        -------
        List[AuditLog]
            List of audit log entries
        """
        try:
            async with self._db_service.get_transaction() as session:
                query = select(AuditLog)
                
                if category:
                    query = query.where(AuditLog.category == category)
                
                if success_only:
                    query = query.where(AuditLog.success == True)
                
                query = query.order_by(desc(AuditLog.created_at))
                query = query.limit(limit)
                
                result = await session.execute(query)
                return list(result.scalars().all())
                
        except Exception as exc:
            logger.error(
                "Failed to get recent audit logs",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # AGGREGATION & ANALYTICS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def count_by_user(
        self,
        user_id: int,
        category: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """
        Count audit logs for a user.
        
        Parameters
        ----------
        user_id : int
            Discord user ID
        category : Optional[str]
            Filter by category
        start_time : Optional[datetime]
            Start of time range
        end_time : Optional[datetime]
            End of time range
            
        Returns
        -------
        int
            Number of audit log entries
        """
        try:
            async with self._db_service.get_transaction() as session:
                query = select(func.count(AuditLog.id)).where(AuditLog.user_id == user_id)
                
                if category:
                    query = query.where(AuditLog.category == category)
                
                if start_time:
                    query = query.where(AuditLog.created_at >= start_time)
                
                if end_time:
                    query = query.where(AuditLog.created_at <= end_time)
                
                result = await session.execute(query)
                return result.scalar_one()
                
        except Exception as exc:
            logger.error(
                "Failed to count audit logs by user",
                extra={
                    "user_id": user_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    async def get_error_rate(
        self,
        category: Optional[str] = None,
        hours: int = 24,
    ) -> float:
        """
        Calculate error rate for operations.
        
        Parameters
        ----------
        category : Optional[str]
            Filter by category
        hours : int
            Time window in hours
            
        Returns
        -------
        float
            Error rate as percentage (0-100)
        """
        try:
            start_time = datetime.utcnow() - timedelta(hours=hours)
            
            async with self._db_service.get_transaction() as session:
                # Total count
                total_query = select(func.count(AuditLog.id)).where(
                    AuditLog.created_at >= start_time
                )
                
                if category:
                    total_query = total_query.where(AuditLog.category == category)
                
                total_result = await session.execute(total_query)
                total_count = total_result.scalar_one()
                
                if total_count == 0:
                    return 0.0
                
                # Error count
                error_query = select(func.count(AuditLog.id)).where(
                    and_(
                        AuditLog.created_at >= start_time,
                        AuditLog.success == False,
                    )
                )
                
                if category:
                    error_query = error_query.where(AuditLog.category == category)
                
                error_result = await session.execute(error_query)
                error_count = error_result.scalar_one()
                
                return (error_count / total_count) * 100
                
        except Exception as exc:
            logger.error(
                "Failed to calculate error rate",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # CLEANUP & RETENTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def delete_older_than(self, days: int) -> int:
        """
        Delete audit logs older than specified days.
        
        Parameters
        ----------
        days : int
            Number of days to retain
            
        Returns
        -------
        int
            Number of entries deleted
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=days)
            
            async with self._db_service.get_transaction() as session:
                # Count before delete
                count_result = await session.execute(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.created_at < cutoff_time
                    )
                )
                count = count_result.scalar_one()
                
                if count == 0:
                    return 0
                
                # Delete old entries
                await session.execute(
                    AuditLog.__table__.delete().where(
                        AuditLog.created_at < cutoff_time
                    )
                )
            
            logger.info(
                "Deleted old audit log entries",
                extra={
                    "count": count,
                    "cutoff_days": days,
                    "cutoff_time": cutoff_time.isoformat(),
                },
            )
            
            return count
            
        except Exception as exc:
            logger.error(
                "Failed to delete old audit logs",
                extra={
                    "days": days,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
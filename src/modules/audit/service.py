"""
Audit Service for Lumen (2025)

Purpose
-------
High-level service for querying and analyzing audit logs with
aggregations, filtering, and export capabilities.

Responsibilities
----------------
- Provide user-friendly query methods
- Aggregate audit data for analytics
- Generate reports and summaries
- Export audit logs in various formats
- Enforce retention policies

Non-Responsibilities
--------------------
- No event consumption (handled by consumer.py)
- No direct database access (uses repository.py)
- No business logic beyond audit queries

Lumen 2025 Compliance
---------------------
- Strict layering: business logic layer
- Transaction discipline: read-only queries
- Observability: structured logging
- Domain separation: audit-specific logic only
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.core.logging.logger import get_logger

if TYPE_CHECKING:
    from src.modules.audit.repository import AuditRepository
    from src.modules.audit.model import AuditLog

logger = get_logger(__name__)


class AuditService:
    """
    High-level audit query and analytics service.
    
    Provides convenient methods for querying, aggregating,
    and analyzing audit log data.
    """
    
    def __init__(self, audit_repository: AuditRepository) -> None:
        """
        Initialize audit service.
        
        Parameters
        ----------
        audit_repository : AuditRepository
            The repository for accessing audit data
        """
        self._audit_repo = audit_repository
        
        logger.debug("AuditService initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # USER ACTIVITY
    # ═══════════════════════════════════════════════════════════════════════
    
    async def get_user_activity_summary(
        self,
        user_id: int,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get activity summary for a user.
        
        Parameters
        ----------
        user_id : int
            Discord user ID
        days : int
            Number of days to analyze
            
        Returns
        -------
        Dict[str, Any]
            Activity summary with counts by category
        """
        try:
            start_time = datetime.utcnow() - timedelta(days=days)
            end_time = datetime.utcnow()
            
            # Get all logs for user in time range
            logs = await self._audit_repo.get_by_user(
                user_id=user_id,
                limit=10000,
            )

            # Filter by time range
            filtered_logs = []
            for log in logs:
                if log.created_at is not None and start_time <= log.created_at <= end_time:  # type: ignore[misc]
                    filtered_logs.append(log)
            logs = filtered_logs

            # Aggregate by category
            category_counts = {}
            operation_counts = {}
            error_count = 0

            for log in logs:
                # Count by category
                category_counts[log.category] = category_counts.get(log.category, 0) + 1

                # Count by operation
                operation_counts[log.operation_type] = operation_counts.get(log.operation_type, 0) + 1

                # Count errors
                if log.success is False:
                    error_count += 1

            return {
                "user_id": user_id,
                "days": days,
                "total_actions": len(logs),
                "error_count": error_count,
                "success_rate": ((len(logs) - error_count) / len(logs) * 100) if logs else 0.0,
                "categories": category_counts,
                "operations": operation_counts,
                "most_common_operation": max(operation_counts, key=lambda k: operation_counts[k]) if operation_counts else None,
            }
            
        except Exception as exc:
            logger.error(
                "Failed to get user activity summary",
                extra={
                    "user_id": user_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # ERROR ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def get_error_report(
        self,
        hours: int = 24,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get error report for recent operations.
        
        Parameters
        ----------
        hours : int
            Number of hours to analyze
        category : Optional[str]
            Filter by category
            
        Returns
        -------
        Dict[str, Any]
            Error report with breakdowns by type and operation
        """
        try:
            start_time = datetime.utcnow() - timedelta(hours=hours)
            end_time = datetime.utcnow()
            
            # Get logs in time range
            logs = await self._audit_repo.get_by_time_range(
                start_time=start_time,
                end_time=end_time,
                category=category,
                limit=10000,
            )
            
            # Filter errors
            errors = [log for log in logs if log.success is False]  # type: ignore[misc]

            # Aggregate error types
            error_types = {}
            error_operations = {}

            for error in errors:
                if error.error_type is not None:  # type: ignore[misc]
                    error_types[error.error_type] = error_types.get(error.error_type, 0) + 1

                error_operations[error.operation_type] = error_operations.get(error.operation_type, 0) + 1

            # Calculate error rate
            error_rate = await self._audit_repo.get_error_rate(
                category=category,
                hours=hours,
            )

            return {
                "hours": hours,
                "category": category,
                "total_operations": len(logs),
                "total_errors": len(errors),
                "error_rate_pct": round(error_rate, 2),
                "error_types": error_types,
                "error_operations": error_operations,
                "most_common_error": max(error_types, key=lambda k: error_types[k]) if error_types else None,
                "most_error_prone_operation": max(error_operations, key=lambda k: error_operations[k]) if error_operations else None,
            }
            
        except Exception as exc:
            logger.error(
                "Failed to generate error report",
                extra={
                    "hours": hours,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # GUILD ANALYTICS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def get_guild_activity_summary(
        self,
        guild_id: int,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Get activity summary for a guild.
        
        Parameters
        ----------
        guild_id : int
            Discord guild ID
        days : int
            Number of days to analyze
            
        Returns
        -------
        Dict[str, Any]
            Guild activity summary
        """
        try:
            start_time = datetime.utcnow() - timedelta(days=days)
            end_time = datetime.utcnow()
            
            # Get all logs for guild in time range
            logs = await self._audit_repo.get_by_guild(
                guild_id=guild_id,
                limit=10000,
            )

            # Filter by time range
            filtered_logs = []
            for log in logs:
                if log.created_at is not None and start_time <= log.created_at <= end_time:  # type: ignore[misc]
                    filtered_logs.append(log)
            logs = filtered_logs

            # Count unique users
            unique_users = len(set(log.user_id for log in logs if log.user_id is not None))
            
            # Aggregate by category
            category_counts = {}
            for log in logs:
                category_counts[log.category] = category_counts.get(log.category, 0) + 1
            
            return {
                "guild_id": guild_id,
                "days": days,
                "total_actions": len(logs),
                "unique_users": unique_users,
                "avg_actions_per_user": (len(logs) / unique_users) if unique_users > 0 else 0,
                "categories": category_counts,
            }
            
        except Exception as exc:
            logger.error(
                "Failed to get guild activity summary",
                extra={
                    "guild_id": guild_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # DATA EXPORT
    # ═══════════════════════════════════════════════════════════════════════
    
    async def export_logs(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        category: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Export audit logs as JSON-serializable dictionaries.
        
        Parameters
        ----------
        user_id : Optional[int]
            Filter by user ID
        guild_id : Optional[int]
            Filter by guild ID
        start_time : Optional[datetime]
            Start of time range
        end_time : Optional[datetime]
            End of time range
        category : Optional[str]
            Filter by category
        limit : int
            Maximum number of logs to export
            
        Returns
        -------
        List[Dict[str, Any]]
            List of audit log dictionaries
        """
        try:
            # Get logs based on filters
            if user_id:
                logs = await self._audit_repo.get_by_user(
                    user_id=user_id,
                    category=category,
                    limit=limit,
                )
            elif guild_id:
                logs = await self._audit_repo.get_by_guild(
                    guild_id=guild_id,
                    category=category,
                    limit=limit,
                )
            elif start_time and end_time:
                logs = await self._audit_repo.get_by_time_range(
                    start_time=start_time,
                    end_time=end_time,
                    category=category,
                    limit=limit,
                )
            else:
                logs = await self._audit_repo.get_recent(
                    category=category,
                    limit=limit,
                )
            
            # Convert to dictionaries
            return [log.to_dict() for log in logs]
            
        except Exception as exc:
            logger.error(
                "Failed to export audit logs",
                extra={
                    "user_id": user_id,
                    "guild_id": guild_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
    
    # ═══════════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════════
    
    async def cleanup_old_logs(self, retention_days: int = 90) -> int:
        """
        Delete audit logs older than retention period.
        
        Parameters
        ----------
        retention_days : int
            Number of days to retain logs
            
        Returns
        -------
        int
            Number of logs deleted
        """
        try:
            count = await self._audit_repo.delete_older_than(days=retention_days)
            
            logger.info(
                "Cleaned up old audit logs",
                extra={
                    "retention_days": retention_days,
                    "deleted_count": count,
                },
            )
            
            return count
            
        except Exception as exc:
            logger.error(
                "Failed to cleanup old audit logs",
                extra={
                    "retention_days": retention_days,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
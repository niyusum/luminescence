"""
Audit Log Model for Lumen (2025)

Purpose
-------
SQLAlchemy model for persistent audit logging of all state-changing
operations in the Lumen system.

Stores:
- User actions (commands, button clicks, modal submissions)
- State mutations (resource changes, fusion, summoning)
- System events (errors, degradations, recovery)
- Transaction metadata (user_id, guild_id, timestamps)

Responsibilities
----------------
- Define audit log schema with indexed fields
- Support efficient querying by user, guild, operation, timestamp
- Store structured event data as JSON
- Maintain referential integrity
- Provide model-level validation

Non-Responsibilities
--------------------
- No business logic
- No event consumption (handled by consumer.py)
- No querying logic (handled by service.py)

Lumen 2025 Compliance
---------------------
- Strict layering: pure data model
- Database discipline: proper indexes and constraints
- Observability: audit trail for compliance
- Performance: indexed queries for analytics

Schema Design
-------------
- Partitionable by timestamp for long-term storage
- Indexed by user_id, guild_id, operation_type, category
- JSON field for flexible event payload storage
- Supports full-text search on operation_name
- Retention policies via timestamp-based cleanup
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class AuditLog(Base):
    """
    Audit log entry for all state-changing operations.
    
    Stores comprehensive audit trail for compliance, debugging,
    analytics, and security monitoring.
    """
    
    __tablename__ = "audit_logs"
    
    # ═══════════════════════════════════════════════════════════════════════
    # PRIMARY KEY
    # ═══════════════════════════════════════════════════════════════════════
    
    id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Unique audit log entry ID",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # TEMPORAL DATA
    # ═══════════════════════════════════════════════════════════════════════
    
    created_at = Column(
        DateTime,
        nullable=False,
        default=func.now(),
        index=True,
        comment="Timestamp when event occurred",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # ACTOR IDENTIFICATION
    # ═══════════════════════════════════════════════════════════════════════
    
    user_id = Column(
        BigInteger,
        nullable=True,
        index=True,
        comment="Discord user ID (if user-initiated)",
    )
    
    guild_id = Column(
        BigInteger,
        nullable=True,
        index=True,
        comment="Discord guild ID (if guild-scoped)",
    )
    
    channel_id = Column(
        BigInteger,
        nullable=True,
        comment="Discord channel ID (if relevant)",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # OPERATION CLASSIFICATION
    # ═══════════════════════════════════════════════════════════════════════
    
    category = Column(
        String(50),
        nullable=False,
        index=True,
        comment="High-level category (TRANSACTION, COMMAND, SYSTEM, SECURITY)",
    )
    
    operation_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Specific operation type (FUSION, SUMMON, TRANSFER, etc.)",
    )
    
    operation_name = Column(
        String(200),
        nullable=False,
        comment="Detailed operation name (e.g., fusion.perform, summon.execute)",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # EVENT DATA
    # ═══════════════════════════════════════════════════════════════════════
    
    event_data = Column(
        JSONB,
        nullable=True,
        comment="Structured event payload (operation-specific data)",
    )
    
    metadata = Column(
        JSONB,
        nullable=True,
        comment="Additional metadata (request context, environment, etc.)",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # OUTCOME
    # ═══════════════════════════════════════════════════════════════════════
    
    success = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether operation succeeded",
    )
    
    error_type = Column(
        String(200),
        nullable=True,
        comment="Error type if operation failed",
    )
    
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if operation failed",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # SECURITY & COMPLIANCE
    # ═══════════════════════════════════════════════════════════════════════
    
    ip_address = Column(
        String(45),
        nullable=True,
        comment="IP address of actor (if available)",
    )
    
    user_agent = Column(
        String(500),
        nullable=True,
        comment="User agent string (if available)",
    )
    
    session_id = Column(
        String(100),
        nullable=True,
        comment="Session identifier for correlation",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # PERFORMANCE TRACKING
    # ═══════════════════════════════════════════════════════════════════════
    
    duration_ms = Column(
        Integer,
        nullable=True,
        comment="Operation duration in milliseconds",
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # INDEXES
    # ═══════════════════════════════════════════════════════════════════════
    
    __table_args__ = (
        # Composite indexes for common query patterns
        Index(
            "idx_audit_user_created",
            "user_id",
            "created_at",
            postgresql_using="btree",
        ),
        Index(
            "idx_audit_guild_created",
            "guild_id",
            "created_at",
            postgresql_using="btree",
        ),
        Index(
            "idx_audit_category_type",
            "category",
            "operation_type",
            postgresql_using="btree",
        ),
        Index(
            "idx_audit_category_created",
            "category",
            "created_at",
            postgresql_using="btree",
        ),
        Index(
            "idx_audit_success_created",
            "success",
            "created_at",
            postgresql_using="btree",
        ),
        # GIN index for JSONB full-text search
        Index(
            "idx_audit_event_data_gin",
            "event_data",
            postgresql_using="gin",
        ),
        Index(
            "idx_audit_metadata_gin",
            "metadata",
            postgresql_using="gin",
        ),
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # REPRESENTATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, "
            f"category={self.category}, "
            f"operation_type={self.operation_type}, "
            f"user_id={self.user_id}, "
            f"success={self.success}, "
            f"created_at={self.created_at})>"
        )
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert audit log entry to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of audit log
        """
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "category": self.category,
            "operation_type": self.operation_type,
            "operation_name": self.operation_name,
            "event_data": self.event_data,
            "metadata": self.metadata,
            "success": self.success,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "session_id": self.session_id,
            "duration_ms": self.duration_ms,
        }
    
    @classmethod
    def from_event(
        cls,
        event_type: str,
        event_data: Dict[str, Any],
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        success: bool = True,
        error: Optional[Exception] = None,
        duration_ms: Optional[int] = None,
    ) -> AuditLog:
        """
        Create audit log entry from event data.
        
        Parameters
        ----------
        event_type : str
            Event type string (e.g., "fusion.completed", "summon.executed")
        event_data : Dict[str, Any]
            Event payload
        user_id : Optional[int]
            Discord user ID
        guild_id : Optional[int]
            Discord guild ID
        success : bool
            Whether operation succeeded
        error : Optional[Exception]
            Exception if operation failed
        duration_ms : Optional[int]
            Operation duration
            
        Returns
        -------
        AuditLog
            New audit log entry
        """
        # Parse event type into category and operation
        parts = event_type.split(".", 1)
        if len(parts) == 2:
            operation_type = parts[0].upper()
            operation_name = event_type
        else:
            operation_type = "UNKNOWN"
            operation_name = event_type
        
        # Determine category
        category = cls._categorize_operation(operation_type)
        
        # Extract metadata
        metadata = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return cls(
            user_id=user_id,
            guild_id=guild_id,
            category=category,
            operation_type=operation_type,
            operation_name=operation_name,
            event_data=event_data,
            metadata=metadata,
            success=success,
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            duration_ms=duration_ms,
        )
    
    @staticmethod
    def _categorize_operation(operation_type: str) -> str:
        """Categorize operation type into high-level category."""
        transaction_types = {
            "FUSION", "SUMMON", "TRANSFER", "PURCHASE", "SELL",
            "CRAFT", "UPGRADE", "CONSUME", "REWARD",
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
        
        if operation_type in transaction_types:
            return "TRANSACTION"
        elif operation_type in command_types:
            return "COMMAND"
        elif operation_type in system_types:
            return "SYSTEM"
        elif operation_type in security_types:
            return "SECURITY"
        else:
            return "OTHER"